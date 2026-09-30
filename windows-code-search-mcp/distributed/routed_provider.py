from __future__ import annotations

from copy import deepcopy

from fastmcp.exceptions import ToolError
from fastmcp.server.providers import Provider
from fastmcp.tools.tool import Tool


_GATEWAY_TOOL_NAMES = {
    "list_devices",
    "device_health",
    "distributed_code_search",
    "node_health",
}


class RoutedNodeTool(Tool):
    """Expose one host tool schema while allowing explicit routing to another node."""

    def __init__(self, source: Tool, provider: "RoutedNodeProvider") -> None:
        parameters = deepcopy(source.parameters)
        properties = parameters.setdefault("properties", {})
        if "device_id" in properties:
            raise ValueError(f"Node tool {source.name} uses reserved parameter device_id")
        properties["device_id"] = {
            "type": "string",
            "description": (
                f"Optional target device ID. Omit to use the gateway host node "
                f"({provider.host_device_id}); set it only to run this tool on another configured PC."
            ),
        }

        super().__init__(
            name=source.name,
            version=source.version,
            title=source.title,
            description=source.description,
            icons=source.icons,
            tags=source.tags,
            meta=source.meta,
            task_config=source.task_config,
            parameters=parameters,
            output_schema=source.output_schema,
            annotations=source.annotations,
            execution=source.execution,
            serializer=source.serializer,
            auth=source.auth,
            timeout=source.timeout,
        )
        self._provider = provider

    async def run(self, arguments: dict, context=None):
        routed_arguments = dict(arguments)
        device_id = routed_arguments.pop("device_id", None)
        connection = self._provider.connection_for(device_id)
        target = await connection.get_tool(self.name)
        if target is None:
            raise ToolError(
                f"Tool {self.name} is not available on device {connection.device.device_id}"
            )
        return await target.run(routed_arguments, context)


class RoutedNodeProvider(Provider):
    """Publish host-node tools once and route calls to host or an explicit remote node."""

    def __init__(self, connections: dict[str, Provider], host_device_id: str) -> None:
        super().__init__()
        if host_device_id not in connections:
            raise ValueError(f"Unknown host device: {host_device_id}")
        self.connections = connections
        self.host_device_id = host_device_id

    def connection_for(self, device_id: str | None):
        target_id = self.host_device_id if device_id is None else device_id
        connection = self.connections.get(target_id)
        if connection is None:
            raise ToolError(f"Unknown or disabled device: {target_id}")
        return connection

    async def _list_tools(self):
        host = self.connections[self.host_device_id]
        tools = await host.list_tools()
        return [
            RoutedNodeTool(tool, self)
            for tool in tools
            if tool.name not in _GATEWAY_TOOL_NAMES
        ]

    async def _get_tool(self, name, version=None):
        if name in _GATEWAY_TOOL_NAMES:
            return None
        host = self.connections[self.host_device_id]
        source = await host.get_tool(name, version=version)
        if source is None:
            return None
        return RoutedNodeTool(source, self)

    async def get_tasks(self):
        return []
