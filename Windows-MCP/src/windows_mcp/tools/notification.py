"""Notification tool — Windows toast notifications."""

from mcp.types import ToolAnnotations
from windows_mcp.analytics import with_analytics
from fastmcp import Context


def register(mcp, *, get_desktop, get_analytics):
    @mcp.tool(
        name="Notification",
        description="Sends a Windows toast notification with a title and message. Useful for alerting the user remotely.",
        annotations=ToolAnnotations(
            title="Notification",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    @with_analytics(get_analytics(), "Notification-Tool")
    def notification_tool(title: str, message: str, ctx: Context = None) -> str:
        try:
            return get_desktop().send_notification(title, message)
        except Exception as e:
            return f"Error sending notification: {str(e)}"
