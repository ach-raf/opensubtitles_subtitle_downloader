# Provider Configuration Capabilities

## Goal

Make `opt_force_utf8`, `hearing_impaired`, and `show_ai_translated` behave
truthfully across the TUI and headless flows, while respecting differences in
provider APIs and metadata.

## Design

### UTF-8 normalization

`opt_force_utf8` remains a provider-independent post-download operation. Both
interactive post-processing paths and the headless runner already pass the
setting to `JobCoordinator`; that data flow will stay unchanged.

The decoder will retain deterministic handling for UTF-8 (with or without a
BOM) and UTF-16, then use the existing `chardet` dependency for legacy subtitle
encodings before falling back to CP1252. The normalized file will continue to
be written atomically with UTF-8 encoding and LF newlines. A failed conversion
must be reported as `utf8_error` without preventing cleaning or synchronization.

### Hearing-impaired policy

The application-level policy remains `include`, `exclude`, or `only`, with the
search coordinator as the final, provider-neutral filter.

OpenSubtitles must be queried inclusively so it cannot discard HI candidates
before the coordinator applies the requested policy. Its response includes a
`hearing_impaired` marker, allowing all three policies to work reliably.

SubDL and SubSource will continue returning the broadest result set supported
by their current clients. Their normalized `hi`/`hearingImpaired` metadata will
drive the same coordinator filter. Provider-side filtering will not replace the
coordinator filter because provider behavior and metadata availability differ.

### AI-translated visibility

`show_ai_translated` remains a local visibility filter. OpenSubtitles exposes
`ai_translated` and `machine_translated`; either marker classifies a candidate
as AI translated. SubSource maps its machine production type to the same
candidate flag.

SubDL search results do not currently expose a documented, dependable
AI-translation marker in the client response. SubDL candidates will therefore
remain unclassified rather than guessed; the setting is best-effort for that
provider. Documentation will state this limitation.

## Validation and tests

Tests will prove that:

- provider adapters request broad results without losing the search policy;
- OpenSubtitles sends `hearing_impaired=include` for TUI-managed searches;
- normalized OpenSubtitles and SubSource flags feed the coordinator filters;
- SubDL's absent AI marker remains false rather than being inferred;
- UTF-8, UTF-16, and a non-CP1252 legacy encoding normalize to valid UTF-8;
- disabling `opt_force_utf8` leaves downloaded bytes unchanged;
- existing search, provider, post-processing, headless, and configuration tests
  continue to pass.

## Scope boundaries

This change does not add provider translation features, inspect subtitle text
to guess whether it was AI-generated or intended for hearing-impaired viewers,
or alter result ranking. It will not modify unrelated working-tree changes.
