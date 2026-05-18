from .desktop import WindowsDesktopExtension
from .search import SearchExtension
from .workspace import WorkspaceSummaryExtension
from .vscode_edits import VSCodeEditExtension
from .vscode_sessions import VSCodeSessionExtension

__all__ = [
    "SearchExtension",
    "WorkspaceSummaryExtension",
    "VSCodeEditExtension",
    "VSCodeSessionExtension",
    "WindowsDesktopExtension",
]
