# Compact Search Preview

## Goal

Give the search results table enough horizontal space to show longer subtitle
release names and an unambiguous numeric match score. Reduce the selected-result
preview to the space its content actually needs.

## Layout

- On wide terminals, allocate approximately 72% of the search workspace to the
  results panel and 28% to the preview pane.
- Keep the preview pane visible while there is enough room to present it
  legibly.
- Preserve the existing narrow-terminal behavior: hide the preview before
  compressing the results table into illegibility.
- Keep the gap and square bordered workbench treatment from the current design
  system.

## Results Table

- Keep one result per row so vertical capacity does not decrease.
- Give the release-name column first claim on reclaimed width.
- Keep the numeric match score visible and visually distinct.
- Retain language, flags, download count, and provider information where the
  available terminal width permits.
- Remove the low-value row-number column and decorative score bar when their
  cells are needed to preserve the full release name and numeric score.
- Continue using the current row selection and keyboard navigation behavior.

## Preview Pane

- Treat the pane as a compact inspector rather than a second primary panel.
- Keep the selected release title, provider/language identity, metadata, and
  Download, Preview, and Copy URL actions.
- Tighten vertical spacing and remove redundant presentation where the same
  information is already communicated nearby.
- Allow long release titles to wrap instead of forcing the pane wider.
- Keep actions keyboard-accessible and preserve their existing IDs and event
  behavior.

## Responsive Behavior

- The results table remains the primary surface at every width.
- At intermediate widths, the preview keeps its minimum usable width while the
  results receive the remaining space.
- At the existing narrow breakpoint, the preview is removed from layout and the
  results panel uses the full workspace.

## Scope

Expected production changes:

- `tui/style.tcss`
- `tui/widgets/results_table.py`
- `tui/widgets/detail_pane.py`

Focused tests may be added or updated under `tui/tests/`. No production files or
components will be deleted.

## Verification

- Run focused tests for result rendering, detail refresh, and responsive layout.
- Run the complete TUI test suite.
- Render a representative wide-terminal screenshot and confirm that long names
  and numeric scores remain visible while the preview stays compact.
