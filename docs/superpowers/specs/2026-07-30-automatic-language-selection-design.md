# Automatic Language Selection Design

## Goal

Make language selection deterministic and automation-friendly across the
Textual TUI and legacy CLI. An explicit command-line language must work in
every interface, configuration may define a default language, and batch or
no-TUI runs must never wait for language input.

## Configuration and precedence

Add an optional `general.default_language` setting. Its value is an ISO
language code such as `ar` or `en`. An empty value means that no explicit
configuration default is set.

Resolve one language for the run using this precedence:

1. The normalized value supplied through `--lang CODE`.
2. The normalized non-empty value of `general.default_language`.
3. The first configured language code supported by the effective provider.

The selected provider determines the fallback language list. For SubDL and
SubSource, use that provider's configured `languages` mapping. For
OpenSubtitles, Auto, or Ask, retain the existing OpenSubtitles fallback. YAML
mapping order determines which supported language is first.

An explicit CLI or configuration default is allowed even when it is not
already present in the provider's configured language mapping. This preserves
the current TUI behavior that accepts an ISO code directly and allows
one-off/provider-supported codes without requiring a YAML list edit.

## Shared resolution boundary

Introduce one small, pure language-resolution function in the CLI startup
module. It accepts the CLI language, raw configuration, and effective backend,
then returns both the normalized language code and its source (`cli`,
`config`, `provider`, or `missing`). Both launch paths consume this result so
precedence cannot drift.

The Textual application receives the resolution result at startup. A `cli`
source remains an explicit override. A `config` or `provider` source supplies
the initial selected language but does not by itself suppress the picker for an
interactive single-file run. The legacy `run_legacy` entry point receives the
same result explicitly instead of ignoring `--lang` or independently re-reading
the first provider language.

## Interaction rules

- `--lang CODE` confirms the language in both TUI and no-TUI modes.
- Every no-TUI run uses the resolved language without showing the numbered
  language menu.
- A TUI run with more than one queued media file is a batch and uses the
  resolved language without showing the startup language picker.
- A single-file TUI run may retain the startup picker when no `--lang` was
  supplied and `general.skip_interactive_menu` is false, regardless of whether
  the starting value came from `general.default_language` or provider order.
  The picker starts on the resolved default.
- `general.skip_interactive_menu: true` continues to suppress startup choices.
- Manual language changes made after startup retain the existing
  current-file/all-remaining scope choice.

Backend selection is outside this change. If an existing mode still requires a
backend choice, this feature does not silently choose a different backend.

## Error handling

If resolution reaches the provider-language fallback and the effective
provider has no configured languages, automation cannot continue safely. Batch
and no-TUI runs exit with a concise error stating that no default or supported
language is configured and recommending `--lang` or
`general.default_language`.

An explicit language containing only whitespace is treated as absent. All
resolved codes are stripped and lowercased before dispatch.

## Configuration and documentation

Add `default_language: ""` to `config.yaml.sample` and support it in the typed
TUI configuration model and round-trip writer. Document its precedence in the
README. Update `--lang` help and usage text to state that it applies to both
interfaces instead of only seeding the TUI.

The user's local `config.yaml` is not rewritten automatically. Existing
configurations remain valid and fall back to the first supported language.

## Test strategy

Add focused tests proving:

- `--lang` overrides both `general.default_language` and provider ordering.
- `general.default_language` overrides provider ordering when CLI input is
  absent.
- The first provider language is used when neither explicit default exists.
- Values are stripped and lowercased.
- A no-TUI run passes the resolved language to provider dispatch without
  invoking the language menu.
- A multi-file TUI run starts searching with the resolved language without
  opening the language picker.
- A single-file interactive TUI may still open the picker.
- Missing language data fails clearly in noninteractive execution.
- The new configuration field survives load/save round trips.

The full TUI test suite remains the regression gate after the focused tests
pass.
