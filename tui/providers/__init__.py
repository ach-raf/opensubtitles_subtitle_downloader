"""Provider adapter exports."""

from tui.providers.factory import create_adapters
from tui.providers.opensubtitles import OpenSubtitlesAdapter
from tui.providers.subdl import SubDLAdapter
from tui.providers.subsource import SubSourceAdapter

__all__ = [
    "OpenSubtitlesAdapter",
    "SubDLAdapter",
    "SubSourceAdapter",
    "create_adapters",
]
