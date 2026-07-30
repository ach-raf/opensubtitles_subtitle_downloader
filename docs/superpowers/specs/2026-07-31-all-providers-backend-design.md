# All-Providers Backend Design

## Goal

Make `all-providers` a first-class backend mode alongside `opensubtitles`,
`subdl`, `subsource`, `auto`, and `ask`. The mode must be selectable from
`config.yaml`, the CLI, and the TUI, and it must work in both TUI and no-TUI
execution.

## Public interface

Configuration:

```yaml
general:
  preferred_backend: all-providers
```

CLI:

```bash
python download_subs.py --backend all-providers "movie.mkv"
python download_subs.py --no-tui --backend all-providers "season"
```

The accepted backend values become:

- `opensubtitles`
- `subdl`
- `subsource`
- `auto`
- `ask`
- `all-providers`

An explicit `--backend` continues to override `preferred_backend` for the
current run in every interface.

## Mode semantics

`auto` and `all-providers` remain distinct:

- `auto` searches configured providers in priority order and stops after the
  first provider that returns candidates.
- `all-providers` searches every configured provider, combines the candidates,
  applies the existing visibility filters and scoring, and returns the shared
  ranking used by the TUI.

The implementation must reuse `SearchCoordinator.merge()` and its existing
ranking logic. TUI and no-TUI must not implement separate scoring rules.

## Canonical state and legacy compatibility

Add `ALL_PROVIDERS = "all-providers"` to both backend-mode enums used at the
CLI and TUI boundaries.

`preferred_backend: all-providers` is the canonical saved representation. The
existing `general.merge_results` setting becomes a deprecated compatibility
input:

- When an old configuration has `merge_results: true`, load it as the
  `all-providers` runtime mode.
- A canonical `preferred_backend: all-providers` takes precedence over a
  contradictory `merge_results: false`.
- When configuration is saved from the TUI, write
  `preferred_backend: all-providers` and normalize `merge_results` to `false`.
- Concrete, `auto`, and `ask` modes also save with `merge_results: false`.

The TUI may retain its internal `merge_mode` display/layout flag during the
transition, but it must be derived from `EngineMode.ALL_PROVIDERS`; it must not
remain an independent source of truth.

## TUI behavior

The engine selector shows All providers as a first-class option backed by
`EngineMode.ALL_PROVIDERS`.

When selected:

- Search calls `SearchCoordinator.merge()`.
- `auto_selection: false` displays the combined ranked candidate list for
  manual selection.
- `auto_selection: true` downloads the first candidate from that same list.
- The top bar, status bar, configuration view, and saved configuration display
  the canonical All providers mode.

Changing away from All providers immediately disables merged searching and
saves the newly selected mode.

## No-TUI behavior

The existing legacy single-provider clients cannot provide a combined ranking.
Add a focused headless all-providers runner that reuses the TUI-domain
components without starting Textual:

- Load configured provider adapters.
- Create one `SearchRequest` per normalized media file.
- Call `SearchCoordinator.merge()`.
- Select the first candidate from the returned ranked list.
- Download it through `JobCoordinator`.
- Apply the configured cleaning, UTF-8, output-directory, and synchronization
  policies through the existing job boundary.

No-TUI always downloads the best merged candidate, regardless of
`auto_selection`, because it has no candidate-selection screen. This is the
explicit exception to the TUI meaning of `auto_selection`.

Synchronization remains noninteractive: `sync_audio_to_subs: true` runs it,
`false` skips it, and `ask` skips it with a concise notice recommending an
explicit setting for unattended runs.

For an existing subtitle conflict, do not overwrite silently. Report the
conflict for that file and continue the batch. Provider errors, no candidates,
download errors, and post-processing errors are reported per file without
blocking later files. If no providers are configured, exit cleanly before
processing.

The headless runner returns a nonzero process status when no file completes
successfully. Partial batch success is reported clearly and does not discard
successful downloads.

## Language behavior

The existing language precedence remains unchanged:

1. `--lang`
2. `general.default_language`
3. The first configured language fallback

For `all-providers`, the fallback is the first language from the first
configured provider in the application's established provider order.
An explicit language remains valid even if it is absent from one provider's
display mapping; each adapter receives the normalized code through the shared
request.

## Error handling

- Invalid backend values are rejected by argparse or normalized to `ask` when
  loaded from legacy configuration, matching current behavior.
- All-providers with zero configured adapters exits with an actionable error.
- Partial provider failures retain candidates from healthy providers and print
  concise provider-specific warnings.
- No merged candidates for one file prints a no-results message and advances.
- No-TUI never opens a backend, language, or candidate-selection prompt when
  `all-providers` is selected.

## Documentation and migration

Update `config.yaml.sample`, CLI help, and README to list `all-providers`.
Explain the difference between `auto` and `all-providers`, the no-TUI
best-match rule, and the deprecated `merge_results` migration.

Do not rewrite the user's local `config.yaml` automatically. It is migrated
only when explicitly saved through the application.

## Test strategy

Add tests proving:

- Both enums accept and label `all-providers`.
- `--backend all-providers` parses and overrides configuration.
- `preferred_backend: all-providers` survives a configuration round trip.
- Legacy `merge_results: true` loads as All providers and saves canonically.
- Contradictory legacy fields resolve to the canonical backend value.
- The TUI selector, top bar, status, configuration view, and search dispatch use
  the canonical mode.
- TUI auto-selection false displays merged candidates; true downloads the
  highest-ranked candidate.
- No-TUI searches all configured adapters, chooses the first shared-ranked
  candidate, downloads exactly one subtitle per file, and ignores
  `auto_selection: false`.
- No-TUI handles partial provider failures, zero providers, no candidates,
  conflicts, download failures, and batch continuation.
- Language and explicit CLI precedence remain unchanged.
- CLI help, sample configuration, and README expose the new mode.

The complete TUI suite and focused headless integration tests are the final
regression gate.
