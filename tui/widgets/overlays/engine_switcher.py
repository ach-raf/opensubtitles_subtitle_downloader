"""Compact engine picker with advisory health and merge control."""

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from tui.domain import EngineMode, HealthResult, Provider


class EngineSwitcher(ModalScreen[tuple[EngineMode, bool] | None]):
    DEFAULT_CSS = """
    EngineSwitcher {
        align: center middle;
        background: rgba(3, 6, 11, 0.72);
    }
    EngineSwitcher > Vertical {
        width: 72;
        max-width: 92%;
        height: 18;
        background: #111820;
        border: round #75a7ff;
        padding: 1 2;
    }
    EngineSwitcher .overlay-title {
        text-style: bold;
        color: #eef5ff;
        height: 2;
    }
    EngineSwitcher .overlay-help {
        color: #8493a8;
        height: 2;
    }
    EngineSwitcher OptionList {
        height: 9;
        border: none;
        background: #111820;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "select", "Select", show=False),
    ]

    def __init__(
        self,
        current: EngineMode,
        health: dict[Provider, HealthResult],
        merge_mode: bool,
        configured: set[Provider] | None = None,
    ) -> None:
        super().__init__()
        self.current = current
        self.health = health
        self.merge_mode = merge_mode
        self.configured = configured if configured is not None else set(Provider)
        self.choices = [
            (EngineMode.OPENSUBTITLES, False),
            (EngineMode.SUBDL, False),
            (EngineMode.SUBSOURCE, False),
            (EngineMode.AUTO, False),
            (EngineMode.AUTO, True),
        ]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Subtitle engine", classes="overlay-title")
            yield Static(
                "Auto stops at the first source with matches. All providers "
                "combines every configured source.",
                classes="overlay-help",
            )
            yield OptionList(
                *[
                    Option(
                        self._label(mode, merge),
                        id="all-providers" if merge else mode.value,
                        disabled=(
                            mode.provider is not None
                            and mode.provider not in self.configured
                        ),
                    )
                    for mode, merge in self.choices
                ],
                id="engine-options",
            )

    def on_mount(self) -> None:
        options = self.query_one("#engine-options", OptionList)
        target = (EngineMode.AUTO, True) if self.merge_mode else (self.current, False)
        try:
            options.highlighted = self.choices.index(target)
        except ValueError:
            options.highlighted = 0
        options.focus()

    def _label(self, mode: EngineMode, merge: bool = False) -> str:
        if merge:
            return "All providers  ·  concurrent combined results"
        if mode is EngineMode.AUTO:
            return (
                "Auto fallback  ·  stops after first source with matches  ·  "
                "SubSource → OpenSubtitles → SubDL"
            )
        provider = mode.provider
        if provider not in self.configured:
            return f"{mode.label}  ·  credentials missing"
        health = self.health.get(provider)
        if health is None:
            status = "not checked"
        elif health.reachable:
            latency = (
                f" · {health.latency_ms} ms" if health.latency_ms is not None else ""
            )
            status = f"reachable{latency}"
        else:
            status = f"probe unavailable · {health.reason or 'unknown'}"
        return f"{mode.label}  ·  {status}"

    def action_select(self) -> None:
        options = self.query_one("#engine-options", OptionList)
        index = options.highlighted
        if index is None:
            return
        self.dismiss(self.choices[index])

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(OptionList.OptionSelected, "#engine-options")
    def on_option_selected(self) -> None:
        self.action_select()
