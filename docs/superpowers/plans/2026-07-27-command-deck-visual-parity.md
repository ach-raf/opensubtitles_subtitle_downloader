# Command Deck Visual Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the production Textual TUI visibly match the approved Command Deck mockup while preserving all existing behavior.

**Architecture:** Keep Textual and the existing view/widget ownership. Encode the mockup as a compact Workbench design system in `style.tcss`, then make small presentation-only widget changes where CSS cannot supply labels or content. Protect the design with geometry/content tests and fresh SVG screenshots at wide and narrow terminal sizes.

**Tech Stack:** Python 3.10, Textual 8.x, TCSS, pytest

---

### Task 1: Lock the presentation contract

**Files:**
- Create: `design.md`
- Modify: `tui/tests/test_app.py`

- [ ] Add tests asserting the wide layout has a three-row chrome stack, visible result and preview panels, labeled live-control chips, a compact query row, and a settings-aware status rail.
- [ ] Run the focused tests and confirm they fail against the current generic presentation.
- [ ] Record the Workbench/Terminal design tokens and responsive rules in `design.md`.

### Task 2: Rebuild command-deck chrome

**Files:**
- Modify: `tui/style.tcss`
- Modify: `tui/widgets/topbar.py`
- Modify: `tui/widgets/query_bar.py`
- Modify: `tui/widgets/status_bar.py`

- [ ] Replace oversized button chrome with one-cell labels, thin square rules, compact chips, and mockup-matched green/amber/blue state accents.
- [ ] Expose `ENGINE`, `LANG`, command-palette, provider health, queue progress, and live post-processing settings in the existing chrome.
- [ ] Run focused tests and confirm the new contract passes.

### Task 3: Rebuild the workbench panels

**Files:**
- Modify: `tui/style.tcss`
- Modify: `tui/widgets/views.py`
- Modify: `tui/widgets/results_table.py`
- Modify: `tui/widgets/detail_pane.py`
- Test: `tui/tests/test_app.py`

- [ ] Add failing assertions for mockup panel headings, preview actions, score visualization, and wide/narrow proportions.
- [ ] Implement compact panel headers, a denser results table, semantic flags, score bars, structured preview metadata, and all three preview actions.
- [ ] Preserve the narrow-terminal rule that hides only the preview panel.

### Task 4: Unify secondary views and overlays

**Files:**
- Modify: `tui/style.tcss`
- Modify only if required by visual verification: `tui/widgets/overlays/*.py`

- [ ] Apply the same rules, selection treatment, spacing, and control voice to Queue, History, Config, and modal screens.
- [ ] Avoid logic changes; add tests only for presentation content or geometry that can regress.

### Task 5: Verify

**Files:**
- Modify: `tui/tests/test_app.py` as required by validated behavior

- [ ] Run `pytest tui/tests -q`.
- [ ] Run `ruff check tui`.
- [ ] Export fresh Textual SVG screenshots at `140x42`, `100x32`, and `80x24`.
- [ ] Compare the wide screenshot with `docs/tui-redesign/02-command-deck-live.html`; check narrow screenshots for clipping and lost primary actions.
- [ ] Run the Hallmark self-critique and slop test, fixing any failed presentation gate before handoff.
