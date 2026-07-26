"""Post-download toast — clean / sync / both / done, inline (spec §6.4 / §04).

Slides in when a download completes. Four actions:
    ↵  Clean + Sync
    c  Clean only
    s  Sync only
    d  Done (no postprocessing)
Auto-pick rule (firm): if run_policy.audio_sync is 'always' or 'never', the
toast auto-runs the default action after 5 seconds; if 'ask', it waits
indefinitely for a keypress. 'A' pins the chosen action as the new default.
Sync failure turns the toast amber and offers 'retry without sync'.

The toast is a ModalScreen that dismisses with a chosen PostAction; the App
runs the actual postprocessing (DownloadWorker.postprocess) and records the
HistoryEntry.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

if TYPE_CHECKING:
    from tui.services import DownloadResult


class PostAction(str, Enum):
    """What the user chose for the just-downloaded subtitle."""

    CLEAN_SYNC = "clean_sync"
    CLEAN = "clean"
    SYNC = "sync"
    DONE = "done"

    @property
    def do_clean(self) -> bool:
        return self in (PostAction.CLEAN_SYNC, PostAction.CLEAN)

    @property
    def do_sync(self) -> bool:
        return self in (PostAction.CLEAN_SYNC, PostAction.SYNC)


AUTO_PICK_SECONDS = 5


class PostDownloadToast(ModalScreen):
    """The post-download choice toast."""

    DEFAULT_CSS = """
    PostDownloadToast {
        align: center bottom;
        padding-bottom: 2;
    }
    PostDownloadToast > Vertical {
        width: 70;
        max-width: 95%;
        background: #14181f;
        border: solid #4ddb9a;
    }
    PostDownloadToast.amber > Vertical {
        border: solid #d9a441;
    }
    PostDownloadToast #toast-head {
        padding: 1 2;
        border-bottom: solid #2a3140;
        color: #d8dde6;
    }
    PostDownloadToast #toast-head .ok {
        color: #4ddb9a;
        text-style: bold;
    }
    PostDownloadToast #toast-head .path {
        color: #6a7280;
    }
    PostDownloadToast #toast-body {
        padding: 1 2;
    }
    PostDownloadToast #toast-q {
        color: #8a93a3;
    }
    PostDownloadToast #toast-foot {
        padding: 0 2;
        border-top: solid #2a3140;
        color: #6a7280;
    }
    PostDownloadToast #toast-foot .count {
        color: #d8dde6;
    }
    """

    BINDINGS = [
        Binding("escape", "skip", "Skip", show=False),
        Binding("enter", "clean_sync", "Clean+Sync", show=False),
        Binding("c", "clean", "Clean", show=False),
        Binding("s", "sync", "Sync", show=False),
        Binding("d", "done", "Done", show=False),
        Binding("A", "pin_default", "Pin default", show=False),
    ]

    def __init__(
        self,
        result: "DownloadResult",
        audio_sync_policy: str,
        amber: bool = False,
    ) -> None:
        super().__init__()
        self.result = result
        self.audio_sync_policy = audio_sync_policy  # always | never | ask
        self.amber = amber
        self._auto_timer = None
        self._pinned: bool = False

    @property
    def default_action(self) -> PostAction:
        """The action the 5-second auto-pick would run, per the policy."""
        if self.audio_sync_policy == "always":
            return PostAction.CLEAN_SYNC
        if self.audio_sync_policy == "never":
            return PostAction.CLEAN
        # 'ask' has no default; the toast waits.
        return PostAction.DONE

    @property
    def auto_picks(self) -> bool:
        """True iff the 5-second auto-pick is armed (policy is always/never)."""
        return self.audio_sync_policy in ("always", "never")

    # ---- Compose ----------------------------------------------------------
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._head_markup(), id="toast-head", markup=True)
            yield Static(self._body_markup(), id="toast-body", markup=True)
            yield Static(self._foot_markup(), id="toast-foot", markup=True)

    def on_mount(self) -> None:
        if self.amber:
            self.add_class("amber")
        if self.auto_picks:
            # Arm the 5-second auto-pick. Per spec §6.4, ask waits indefinitely.
            self._auto_timer = self.set_timer(
                AUTO_PICK_SECONDS, self._auto_pick
            )

    def on_unmount(self) -> None:
        if self._auto_timer is not None:
            self._auto_timer.stop()

    # ---- Markups ----------------------------------------------------------
    def _head_markup(self) -> str:
        sub_name = _basename(self.result.subtitle_path) or "(unsaved)"
        sub_dir = _dirname(self.result.subtitle_path) or ""
        return f"[#4ddb9a]✓[/] [b]{sub_name}[/]   [dim]→ {sub_dir}[/]"

    def _body_markup(self) -> str:
        if self.amber:
            return (
                "[#d9a441]Audio sync is unavailable[/] (no ffs/ffmpeg on PATH).\n\n"
                "[b]↵[/] Clean only   [b]s[/] retry sync   [b]d[/] done   [b]esc[/] skip"
            )
        return (
            "[dim]Downloaded. What next?[/]\n\n"
            "[b][#4ddb9a]↵[/][/] Clean + Sync   "
            "[b]c[/] Clean only   "
            "[b]s[/] Sync only   "
            "[b]d[/] Done"
        )

    def _foot_markup(self) -> str:
        if self.amber:
            return "[dim][b]A[/b] pin default   [b]esc[/b] skip[/]"
        if self.auto_picks:
            verb = {
                PostAction.CLEAN_SYNC: "Clean + Sync",
                PostAction.CLEAN: "Clean",
            }.get(self.default_action, "Done")
            return (
                f"[dim]auto-picks in[/dim] [b]{AUTO_PICK_SECONDS}s[/]"
                f" [dim]from your default: [b]{verb}[/]"
                f"   ·   [b]A[/b] pin default   [b]esc[/b] skip[/]"
            )
        # 'ask' — wait indefinitely.
        return "[dim]policy is[/] [b]ask[/][dim] — waiting for your keypress.   "
        "[b]A[/b] pin default   [b]esc[/b] skip[/]"

    # ---- Actions ----------------------------------------------------------
    def action_clean_sync(self) -> None:
        self._choose(PostAction.CLEAN_SYNC)

    def action_clean(self) -> None:
        self._choose(PostAction.CLEAN)

    def action_sync(self) -> None:
        self._choose(PostAction.SYNC)

    def action_done(self) -> None:
        self._choose(PostAction.DONE)

    def action_skip(self) -> None:
        self._choose(PostAction.DONE)

    def action_pin_default(self) -> None:
        """Pin the next chosen action as the new default; the App writes config."""
        self._pinned = True
        # Don't dismiss yet — let the user pick the action to pin.
        self._update_foot("[#4ddb9a]pin armed — choose the action to set as default[/]")

    def _auto_pick(self) -> None:
        if self.auto_picks:
            self._choose(self.default_action, auto=True)

    def _choose(self, action: PostAction, auto: bool = False) -> None:
        if self._auto_timer is not None:
            self._auto_timer.stop()
            self._auto_timer = None
        # Carry the pinned flag so the App can persist the new default.
        self.dismiss((action, self._pinned, auto))

    def _update_foot(self, markup: str) -> None:
        try:
            self.query_one("#toast-foot", Static).update(markup)
        except Exception:  # noqa: BLE001
            pass


def _basename(path: Optional[str]) -> str:
    if not path:
        return ""
    return path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _dirname(path: Optional[str]) -> str:
    if not path:
        return ""
    # Cross-platform split (handles both / and \).
    parts = path.replace("\\", "/").rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""
