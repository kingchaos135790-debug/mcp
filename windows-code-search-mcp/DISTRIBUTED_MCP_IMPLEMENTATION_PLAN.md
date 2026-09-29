# Distributed MCP Implementation Plan

## Reviewed design and implementation scope

The gateway/node architecture is retained. Each node owns its Windows tools, repositories,
search engine, indexes and watchers. The gateway owns OAuth, device configuration, SSH
supervision, namespaced proxy tools and aggregate search. Standalone remains the default.

The implementation covers the first functional milestone and distributed search, with
local launchers and deployment checks. Remote bootstrap, SSH key provisioning, service
installation and automatic LAN discovery remain outside this milestone. Actual deployment
to a second physical Windows machine requires operator-provided device configuration.

```text
MCP client -> public gateway + OAuth
                    |
                    +-- localhost:18101 -> SSH -> main_desktop localhost:18000
                    +-- localhost:18102 -> SSH -> laptop       localhost:18000
                                                   |
                                          full local MCP runtime
```

## Review findings and resolutions

| Gap in the original proposal | Implemented resolution |
| --- | --- |
| Mounting only healthy nodes at startup leaves late nodes absent | Mount every enabled device immediately; independently refresh verified schemas in the background |
| Live discovery can make one unavailable node delay all tool listings | Serve in-memory schema snapshots; never contact nodes during tools/list |
| A forwarded port might point to the wrong node | Verify device_id, role and protocol_version on every new client session before executing a tool |
| Gateway imports could initialize Windows desktop dependencies | Select the role before importing ServerApp or extensions; gateway creates no local runtime |
| Retry behavior for mutable tools was unspecified | Retry SSH connections only; never replay MCP tool calls |
| Shutdown cancellation could skip child cleanup | Shield gateway/node cleanup; cancel monitors and terminate owned SSH children, killing after a bounded wait |
| Proxy HTTP behavior could expose gateway credentials or use an HTTP proxy | Keep only logical chat identity in forwarded headers; strip auth, cookies and gateway transport IDs; disable environment proxies and redirects for private hops |
| Capability policy had no enforcement model | Optional exact tool allowlist is enforced in schema discovery, namespaced calls and aggregate search |
| Cross-device repository identity and scoring were underspecified | Require {deviceId, repoId} for repository-scoped aggregate queries; preserve original scores and use deterministic round-robin node ranking |
| Deep async health checks could block node heartbeats | Offload the deep health subprocess to a thread; regular synchronous search tools already use FastMCP's worker threads |
| Machine-specific installation paths prevented copying to another device | Derive sibling source/search paths from the installation; retain explicit environment overrides |

## Roles and ownership

- `MCP_ROLE=standalone`: existing integrated tools and OAuth behavior; default.
- `MCP_ROLE=node`: the same integrated runtime plus `node_health`; Streamable HTTP,
  loopback-only listener, no public OAuth. `MCP_DEVICE_ID` is required.
- `MCP_ROLE=gateway`: Streamable HTTP gateway with no desktop, search engine or indexer.
  OAuth is required unless explicitly allowing an unauthenticated loopback test server.

`LocalNodeRuntime` owns the existing `ServerContext`, search bridge, auto-indexer,
desktop, watchdog and analytics. Extensions continue to receive the same context.
Optional extension-owned state remains on that context. Partial startup is cleaned up,
and one extension's shutdown error does not skip the remaining cleanup.

`PublicServerMixin` shares OAuth discovery routes between gateway and standalone.
Node identity returns device ID, hostname, application version, distribution protocol
version, role, local search readiness, managed repository count and capabilities.
`node_health` is intentionally lightweight; `server_health` supplies deep search diagnostics.
Readiness means local runtime/prerequisites exist, not that every repository index is current.

## Device registry contract

`devices.json` is ignored machine-local state. Version 1 contains only `version` and
`devices`; unknown fields, credentials, invalid types, duplicate IDs and duplicate
forwarded ports are rejected. Writes replace the file atomically. Runtime status is never
written into configuration. Configuration changes take effect after gateway restart.

Each device has `device_id`, `name`, `host`, `ssh_user`, `local_forward_port`, optional
`remote_mcp_port` (18000), `ssh_port` (22), `enabled` (true), and `allowed_tools` (null).
Null means all tools; an empty list exposes no node tools. Internal identity checks always
use `node_health`, even if it is not in the public allowlist.

IDs are 1-24 lowercase letters/digits/underscores/hyphens, starting with a letter.
Overlapping namespace prefixes such as `pc` and `pc_work` are rejected. Generated tool
names must fit 64 characters and must not collide with gateway management tool names.
SSH host and username values are validated and passed as separate arguments without a shell.
Keys, known_hosts and optional IdentityFile selection remain in the operating system's SSH
configuration, outside the device registry.

## SSH lifecycle

Each enabled device gets an independent OpenSSH supervisor. The command uses:

- public-key authentication only, BatchMode, strict host-key checking;
- `-N -T`, explicit `127.0.0.1:local_port:127.0.0.1:remote_port` forwarding;
- exit on forwarding failure, connect timeout and keepalives;
- no agent/X11 forwarding, local command execution or shared control master.

Failure restarts use exponential backoff from 1 second up to 30 seconds. A connection
that survives 60 seconds resets the backoff. Failures remain device-local. SSH exit state
is included in device health, without capturing credentials or unlimited subprocess output.
HTTP proxy settings do not affect the private hop; explicit SSH config such as ProxyJump
remains an operator choice. Node processes are started independently, not by the tunnel.

## Proxy composition and recovery

The validated dependency is FastMCP 3.0.1, matching this repository's installed environment.
Use native `ProxyTool` schemas and execution, a narrow snapshot `Provider` per device,
and `gateway.mount(node, namespace=device_id)`. A bare live `create_proxy()` does not
provide the required local discovery cache/identity/policy boundary, so composition is
adapted at the provider level. There is no generic call_remote_tool escape hatch.

Each call creates a fresh verified backend client. Input/output schemas, annotations,
content blocks and structured results are preserved. Logical chat identity is forwarded,
while gateway OAuth remains at the gateway. This does not provide per-chat desktop isolation.

Health checks and tool-schema discovery run at startup and every 15 seconds, with a
5-second health deadline. Discovery failures retain the last verified schemas. Calls always
recheck identity; cached schemas are not an authorization bypass. Tool calls have a separate
600-second deadline and an eight-call concurrency bound per device. A timeout does not
prove a remote mutation failed; callers must inspect its outcome before retrying.

Nodes unavailable from first startup have no known schemas until first successful discovery.
Clients must refresh their tool list to see newly discovered or changed tools. Existing tool
names resume without gateway restart or OAuth reset. No proactive list-change notifications
or persistent cross-restart schema cache are promised in this milestone.

The current integrated node registers tools only. Remote resources/prompts and MCP background
task forwarding are not added by this implementation.

## Gateway tools and aggregate search

- `list_devices`: cached status for all configured devices, including disabled nodes.
- `device_health(device_id)`: bounded refresh for one enabled device.
- `distributed_code_search(query, device_ids=None, repo=None, limit=8)`.

An omitted device selection means all enabled devices; an empty selection means none.
Unknown/disabled IDs are validation errors. `repo` requires both `deviceId` and `repoId`,
and its device must belong to the selection. Limit is 1-50 across the merged response.

Search fans out at most four nodes concurrently, with a 60-second deadline for each active
node search. Cancellation stops waiting, but a node-side subprocess may finish independently.
Failures produce per-device errors and `partial=true`; healthy responses and backend warnings
remain available, including when every selected node fails. The gateway never copies indexes.

Within a node, exact matches precede fused hits, with lexical/graph fallback and duplicate
location suppression. Across nodes, round robin preserves each node's ordering without
comparing uncalibrated scores. Every hit contains deviceId, repoId, repoName, filePath,
source, nodeRank and nodeSection, preserving all original node fields including scores.
If an upstream backend omitted repository/path metadata, the corresponding field is null;
the gateway does not invent an identity. Duplicate names on different devices stay distinct.

## Implementation map

- `local_node_runtime.py`, `server_app.py`: local runtime and lifecycle.
- `server_public.py`: shared OAuth discovery routes.
- `server.py`, `config/`: explicit role selection and configuration.
- `distributed/models.py`, `registry.py`: validated desired configuration and status.
- `distributed/tunnel_manager.py`: managed OpenSSH children and retry behavior.
- `distributed/node_connection.py`: identity verification, private HTTP boundary, cached proxies.
- `distributed/health.py`, `gateway.py`, `search.py`: node health, composition, fan-out.
- `distributed/preflight.py`, `launch_node.bat`, `launch_gateway.bat`,
  `launch_distributed.ps1`: deployment checks and Windows PowerShell 5.1-compatible launching.
- `DISTRIBUTED_MCP_SETUP.md`, `devices.example.json`: operator setup.

## Verification and deployment acceptance

Automated checks cover configuration validation, strict tunnel arguments, premature exit,
bounded retries and cleanup, role authentication boundaries, two real HTTP MCP test nodes,
namespaced schemas and routing, qualified repositories, origin/score preservation, denied
tools, deadlines, partial results, initially offline nodes, restart/recovery, identity mismatch,
credential stripping and no mutation retries. Existing tests are run in isolated processes
because several legacy test modules replace global imported packages with stubs.

Before production acceptance, run the operator checklist on two physical Windows devices:
start their full runtimes, validate known_hosts/key authentication, start the gateway, search
a repository unique to each device, read the returned file through that device's namespace,
run hostname through both PowerShell tools, restart one node, and verify the other remains
usable and the restarted node recovers. No live credentials or machine addresses are guessed.

## Deferred work

Automatic remote install/update, discovery, live registry reload, proactive schema-change
notifications, shared filesystems/indexes, global cross-device GitNexus graphs, workload
migration, desktop streaming, per-chat virtualization and SSH key provisioning remain separate.

## API reference

Implementation is checked against the installed FastMCP 3.0.1 source. The upstream
[FastMCP proxy/provider documentation](https://github.com/PrefectHQ/fastmcp/blob/main/docs/servers/providers/proxy.mdx)
describes the composition model; current upstream documentation may describe newer behavior.
