from .desktop import WindowsDesktopExtension
from .search import SearchExtension
from .vscode_edits import VSCodeEditExtension
from .vscode_sessions import VSCodeSessionExtension

__all__ = [
    "SearchExtension",
    "VSCodeEditExtension",
    "VSCodeSessionExtension",
    "WindowsDesktopExtension",
]
