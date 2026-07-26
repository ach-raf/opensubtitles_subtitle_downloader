"""Small compatibility types for supported Python runtimes."""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        """Python 3.10 equivalent of :class:`enum.StrEnum`."""

        def __str__(self) -> str:
            return str(self.value)


__all__ = ["StrEnum"]
