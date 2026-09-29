# Distributed MCP setup

Keep the existing standalone launcher for single-machine use. The new launchers live
beside `server.py`; neither changes the root launcher's settings or existing OAuth state.

## Install each full Windows node

Copy this repository layout to the device, preserving the sibling `Windows-MCP`,
`windows-code-search-mcp` and `ripgrep-treesitter-qdrant-mcp` directories. Use Python 3.13+
and the existing Windows-MCP environment/dependency installation procedure. This release
is validated against FastMCP 3.0.1. Build the search core using `npm ci` and `npm run build`
in its directory; Node.js, ripgrep, GitNexus and native tree-sitter dependencies are required.

Install Windows OpenSSH Server on each remote node and configure key authentication for
the gateway account. Verify the server host key independently and add it to the gateway
account's known_hosts. Confirm `ssh -o BatchMode=yes user@hostname hostname` succeeds
without prompts. SSH setup is intentionally manual; the launcher never accepts unknown
host keys, provisions keys, changes firewall rules or installs services.

From a PowerShell console in `windows-code-search-mcp` on the laptop:

```powershell
$env:INDEX_ROOT = 'C:\mcp-index-data'
$env:AUTO_INDEX_CONFIG_PATH = 'C:\mcp-config\managed-repositories.json'
.\launch_node.bat -DeviceId laptop -Port 18000 -CheckOnly
.\launch_node.bat -DeviceId laptop -Port 18000
```

Use `main_desktop` as the other node's ID. IDs must match the gateway registry exactly.
The node listener is always loopback; binding to a LAN address is rejected. Node role
ignores inherited public OAuth settings. Without an explicit index path the launcher uses
`%LOCALAPPDATA%\windows-code-search-mcp\indexes`. Configure managed repositories normally
on each node; paths and indexes belong to that device. The desktop tools require the
appropriate logged-in interactive Windows session. An SSH tunnel does not start the node.

For optional SSH server installation checks:

```powershell
$env:MCP_DEVICE_ID = 'laptop'
& '..\Windows-MCP\.venv\Scripts\python.exe' -m distributed.preflight --role node --require-ssh
```

Preflight checks Python, Windows dependencies, Node.js, search build, GitNexus, tree-sitter,
ripgrep and index-root writability. It checks availability, not a full repository reindex
or whether sshd is running and accessible from the gateway.

## Configure the gateway

The gateway can use the existing Python environment, or a separate environment with
`requirements-gateway.txt` installed. Keep the sibling Windows-MCP source for its OAuth
provider; Windows desktop dependencies, Node.js and indexes are not used by the gateway.
Set `PYTHON_EXE` or pass `-PythonExe` when using a different environment.

Copy `devices.example.json` to `devices.json` and replace the example host addresses and
SSH usernames. Machine-specific `devices.json` is ignored by Git. Each device may use
`"transport": "ssh"` (the default) or `"transport": "local"`.

For `ssh`, `local_forward_port` is the gateway-side SSH forward and `remote_mcp_port` is the
node's loopback listener. Do not run manual tunnels on the same forwarded ports while the
gateway's supervisors own them. Use `ssh_port` for nondefault SSH ports and the gateway
account's SSH config/agent for IdentityFile/key selection.

For `local`, the node is already on the gateway machine: set `host` to `127.0.0.1`, set
`ssh_user` to a harmless local label such as `local`, and set `local_forward_port` equal to
`remote_mcp_port`. No SSH process is created. This is the preferred way to expose the
gateway PC's own shell, desktop and code-search runtime without SSHing back into itself.
The gateway HTTP port must differ from every node/forwarded port.

Do not place passwords, private keys or OAuth secrets in the device registry. Optional `allowed_tools` accepts an exact list such as:

```json
"allowed_tools": ["hybrid_code_search", "get_file_range", "list_indexed_repositories"]
```

Omitting it permits all node tools. An empty list permits none. This restricts tools,
not filesystem paths or the authority of a permitted PowerShell tool.

Set the existing OAuth environment variables for the public gateway, then launch:

```powershell
$env:OAUTH_ENABLED = 'true'
$env:OAUTH_BASE_URL = 'https://your-existing-mcp-domain.example'
# Supply your existing OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET and redirect/scope settings.
.\launch_gateway.bat -DevicesPath '.\devices.json' -Port 18000 -CheckOnly
.\launch_gateway.bat -DevicesPath '.\devices.json' -Port 18000
```

Point the public reverse tunnel at the gateway only. Do not run the existing standalone
server on the same port. Gateway OAuth uses the existing persistent provider; the default
OAuth state path is unchanged so switching roles can preserve credentials. For concurrent
independent gateways, assign separate `OAUTH_STATE_PATH` values.

An unauthenticated local test requires both `OAUTH_ENABLED=false` and
`MCP_GATEWAY_ALLOW_NO_AUTH=true`. This override works only for loopback listeners and
must not be used with a public reverse tunnel. For example:

```powershell
$env:OAUTH_ENABLED = 'false'
$env:MCP_GATEWAY_ALLOW_NO_AUTH = 'true'
.\launch_gateway.bat -DevicesPath '.\devices.json' -Port 19000
```

The role can also be selected directly with `MCP_ROLE` when running `server.py`. Node and
gateway roles select Streamable HTTP automatically. Source/search paths derive from the
installation directory; existing `WINDOWS_MCP_DIR`, `SEARCH_ENGINE_DIR`, `NODE_EXE` and
`AUTO_INDEX_CONFIG_PATH` overrides remain available.

## Operation and limits

The gateway exposes `list_devices`, `device_health` and `distributed_code_search`, plus
names such as `laptop_PowerShell`, `laptop_hybrid_code_search` and
`main_desktop_get_file_range`. Use the same namespace for a search result's file reads/edits.

```json
{
  "query": "configuration loader",
  "device_ids": ["laptop", "main_desktop"],
  "limit": 8
}
```

For a particular repository, add `"repo": {"deviceId": "laptop", "repoId": "actual-repo-id"}`.
Get the ID from `laptop_list_indexed_repositories`. Repository names and paths can overlap
across devices. Original scores and backend warnings are preserved; merge order interleaves
node rankings rather than comparing scores from unrelated indexes.

| Setting | Default | Meaning |
| --- | --- | --- |
| `MCP_DEVICES_PATH` | adjacent `devices.json` | Gateway registry |
| `MCP_SSH_EXE` | resolved system ssh | Absolute OpenSSH executable override |
| `MCP_HEALTH_INTERVAL_SECONDS` | 15 | Background refresh interval per node |
| `MCP_HEALTH_TIMEOUT_SECONDS` | 5 | Identity/schema refresh deadline |
| `MCP_NODE_CALL_TIMEOUT_SECONDS` | 600 | Overall namespaced call deadline |
| `MCP_DISTRIBUTED_SEARCH_TIMEOUT_SECONDS` | 60 | Per-active-node aggregate search deadline |
| `MCP_LOG_KEEP_COUNT` | 3 | Launcher log retention per role/type |

Unreachable nodes do not block tool listing. Previously discovered schemas stay visible,
and calls recover after the node returns. A node that has never connected has no known tool
schemas: refresh the client's tool list after its first successful health check. Background
schema-change notifications and persistent schema caching are not implemented. Restart the
gateway after registry/policy changes.

The gateway never retries a tool call automatically. A timeout or dropped connection can
occur after an edit/shell operation succeeded; inspect the remote outcome before retrying.
Aggregate searches return partial results and per-device errors. Cancelling a request stops
waiting but may not terminate a search subprocess already running on the node.

Chat identity is forwarded across the private hop; gateway OAuth tokens, cookies and gateway
transport IDs are not. Desktop, clipboard and shell state remain shared within each machine.
The loopback boundary trusts local processes and the SSH account. This is not tenant isolation.

The launchers use Windows PowerShell 5.1-compatible APIs and absolute executable paths.
Logs go under the repository's root `logs` directory with per-run timestamps and role-specific
prefixes. Preflight failures and server exits return their actual exit status. Stop the
gateway normally to let its supervisors terminate their SSH child processes.

## Verification

Run the new tests from `windows-code-search-mcp`:

```powershell
& '..\Windows-MCP\.venv\Scripts\python.exe' -m unittest discover -s distributed/tests -v
```

Legacy tests in `tests` should be run one file per interpreter because they install global
package stubs. The new integration suite starts actual loopback HTTP MCP test servers, with
synthetic tool implementations and a fake tunnel supervisor; it does not provision live SSH.

Before connecting the public gateway, check both physical nodes:

1. `list_devices` and `device_health` report the expected IDs and local search readiness.
2. Search a repository unique to each device through its namespaced search tool.
3. Read a returned file through the same device's `get_file_range` tool.
4. Run `hostname` through both namespaced PowerShell tools and compare the machines.
5. Stop/restart one node; the other remains usable, and the restarted node recovers.
6. Run aggregate search during an outage and confirm results identify the reachable device.

If SSH fails, check the known host key, key authentication, username, sshd availability and
local port ownership. An identity mismatch means the configured ID does not match
`MCP_DEVICE_ID`, or the forward points at the wrong node. Fix it rather than bypassing the check.
