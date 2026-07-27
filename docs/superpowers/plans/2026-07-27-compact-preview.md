# Compact Search Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reallocate the wide search workspace to a 72/28 results/preview split so long subtitle names and numeric match scores remain visible while the preview becomes a compact inspector.

**Architecture:** Keep the existing `SearchView`, `ResultsTable`, and `DetailPane` ownership. Express panel geometry and button density in `style.tcss`; keep table cells and preview content in their existing widgets. Preserve the current `App.on_resize` breakpoint that hides the preview below 115 columns.

**Tech Stack:** Python 3.10, Textual, Rich `Text`, TCSS, pytest.

---

### Task 1: Protect the wide workspace proportions

**Files:**
- Modify: `tui/tests/test_app.py`
- Modify: `tui/style.tcss`

- [ ] **Step 1: Strengthen the failing geometry test**

In `test_search_workbench_exposes_mockup_panel_content`, replace the loose
`results_panel.region.width > detail_panel.region.width` assertion with:

```python
assert results_panel.region.width >= detail_panel.region.width * 2
assert 30 <= detail_panel.region.width <= 42
```

This encodes the approved wide-screen hierarchy while allowing for borders and
Textual's integer cell rounding.

- [ ] **Step 2: Run the geometry test and verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests/test_app.py::test_search_workbench_exposes_mockup_panel_content -v
```

Expected: FAIL because the current `11fr / 9fr` split makes the result panel
less than twice the preview width.

- [ ] **Step 3: Implement the minimal 72/28 layout**

In the command-deck section of `tui/style.tcss`, use:

```tcss
#results-panel {
    width: 18fr;
}

DetailPane {
    width: 7fr;
    min-width: 30;
}
```

Keep all existing height, border, padding, background, and margin rules intact.

- [ ] **Step 4: Run the geometry and narrow-layout tests**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests/test_app.py::test_search_workbench_exposes_mockup_panel_content tui/tests/test_app.py::test_narrow_terminal_hides_detail_without_hiding_results -v
```

Expected: both tests PASS.

### Task 2: Let release names consume reclaimed width

**Files:**
- Modify: `tui/tests/test_app.py`
- Modify: `tui/widgets/results_table.py`

- [ ] **Step 1: Write a failing result-column contract test**

Add:

```python
def test_results_table_keeps_release_and_numeric_score_visible(configured_app):
    app, coordinator = configured_app
    coordinator.candidates = [
        Candidate(
            provider=Provider.SUBDL,
            provider_id="long-release",
            release=(
                "Inception.2010.2160p.UHD.BluRay.REMUX."
                "HDR.HEVC.TrueHD.Atmos-FullReleaseName"
            ),
            language="en",
            download_count=48213,
            score=96,
        )
    ]

    async def run():
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause(0.3)

            table = app.query_one(ResultsTable)
            release_column = list(table.columns.values())[1]
            assert list(table.columns.values())[0].label.plain == "Release"
            release_column = list(table.columns.values())[0]
            assert release_column.width >= 75
            rendered_score = table.get_cell_at((0, len(table.columns) - 1))
            assert rendered_score.plain == "96"
            assert table.max_scroll_x == 0

    asyncio.run(run())
```

Use the existing `Candidate` and `Provider` imports already established in the
test module.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests/test_app.py::test_results_table_keeps_release_and_numeric_score_visible -v
```

Expected: FAIL because the Release column is currently fixed at 38 cells.

- [ ] **Step 3: Expand the release column**

In `ResultsTable._set_columns`, change only the Release column declaration:

```python
self.add_column("Release", width=67 if merge_mode else 75)
```

Remove the low-value row-number column, use compact widths of `2`, `6`, `5`,
and `4` for language, flags, downloads, and match, and render the match as a
yellow numeric value without a decorative bar. This keeps the full 75-cell
release name and score visible without horizontal scrolling.

- [ ] **Step 4: Run the new result test**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests/test_app.py::test_results_table_keeps_release_and_numeric_score_visible -v
```

Expected: PASS.

### Task 3: Streamline the compact preview inspector

**Files:**
- Modify: `tui/tests/test_app.py`
- Modify: `tui/widgets/detail_pane.py`
- Modify: `tui/style.tcss`

- [ ] **Step 1: Write a failing compact-preview content test**

Extend the existing populated-detail test with:

```python
detail = str(app.query_one("#detail-kv", Static).content)
assert "Match" in detail
assert "94" in detail
assert detail.count("\n") <= 3
assert str(app.query_one("#copy-url", Button).label) == "URL  y"
```

Use the score already assigned to that test's candidate, adjusting the expected
number to match the fixture if it is not `96`.

- [ ] **Step 2: Run the detail test and verify RED**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests/test_app.py::test_results_and_multilingual_detail_are_visible -v
```

Expected: FAIL because the current inspector uses six metadata lines, omits the
score, and labels the final action `Copy URL  y`.

- [ ] **Step 3: Condense preview content and action labels**

In `DetailPane.compose`, keep widget IDs and change only labels:

```python
yield Button("Get  ↵", id="download-selected", variant="primary")
yield Button("View  p", id="preview-selected")
yield Button("URL  y", id="copy-url")
```

In `refresh_from_state`, replace the metadata update with four lines:

```python
detail.update(
    f"[dim]Uploader[/dim]   {candidate.author or '—'}\n"
    f"[dim]Downloads[/dim]  {candidate.download_count:,}\n"
    f"[dim]Match[/dim]      [yellow]{candidate.score:.0f}[/yellow]"
    f"{' · [green]exact hash[/green]' if candidate.hash_match else ''}\n"
    f"[dim]Flags[/dim]      "
    f"HI {'yes' if candidate.hearing_impaired else 'no'} · "
    f"AI {'yes' if candidate.ai_translated else 'no'}"
)
```

- [ ] **Step 4: Fit all actions into the narrow inspector**

In `tui/style.tcss`, replace the shared button minimum with explicit widths:

```tcss
#detail-actions Button {
    width: 1fr;
    min-width: 8;
}

#download-selected {
    min-width: 11;
}
```

Keep the existing height, margin, padding, border, background, colors, and state
rules.

- [ ] **Step 5: Run the focused preview and workbench tests**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests/test_app.py::test_results_and_multilingual_detail_are_visible tui/tests/test_app.py::test_search_workbench_exposes_mockup_panel_content -v
```

Expected: both tests PASS.

### Task 4: Verify the complete TUI

**Files:**
- Verify: `tui/tests/`
- Verify: `tui/style.tcss`

- [ ] **Step 1: Run formatting and static checks**

Run:

```powershell
.\venv\Scripts\python.exe -m ruff check tui
```

Expected: PASS with no diagnostics.

- [ ] **Step 2: Run the full TUI suite**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tui/tests -q
```

Expected: all tests PASS.

- [ ] **Step 3: Render and inspect a wide screenshot**

Run the repository's existing TUI screenshot helper or Textual test driver at
`140x42`, then verify:

- the result panel is at least twice the preview width;
- the long Release value receives 75 cells in single-provider mode;
- the numeric Match score remains visible without horizontal scrolling;
- the compact preview has four metadata lines and three usable actions;
- there is no horizontal clipping inside the preview.

- [ ] **Step 4: Review the final diff**

Run:

```powershell
git diff --check
git diff -- tui/style.tcss tui/widgets/results_table.py tui/widgets/detail_pane.py tui/tests/test_app.py
```

Expected: no whitespace errors and only changes that trace to the compact
preview request.
