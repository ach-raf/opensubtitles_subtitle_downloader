# Provider Configuration Capabilities

## Goal

Make `opt_force_utf8`, `hearing_impaired`, and `show_ai_translated` behave
truthfully across the TUI and headless flows, while respecting differences in
provider APIs and metadata. Consolidate video-media discovery so individual
files and folder expansion use one extensible allowlist.

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

### Media extension discovery

`tui.media` will own one canonical `DEFAULT_MEDIA_EXTENSIONS` set. It will
cover common containers and raw video streams, including `mkv`, `mp4`, `avi`,
and `av1`. Both TUI and headless discovery will resolve their effective set
from this same source before expanding input files or folders.

Configuration may extend or reduce the defaults without copying the entire
list:

```yaml
general:
  media_extensions:
    include: []
    exclude: []
```

Values are normalized to lowercase and may be written with or without a
leading dot. Empty entries are ignored. Exclusion wins when an extension is in
both lists. Omitting the section uses all built-in defaults. The same effective
set applies to direct files, non-recursive folders, and recursive folders.

`cleaning_subtitles.supported_media` remains the list of subtitle formats the
cleaner supports; it is not used for video discovery.

## Validation and tests

Tests will prove that:

- provider adapters request broad results without losing the search policy;
- OpenSubtitles sends `hearing_impaired=include` for TUI-managed searches;
- normalized OpenSubtitles and SubSource flags feed the coordinator filters;
- SubDL's absent AI marker remains false rather than being inferred;
- UTF-8, UTF-16, and a non-CP1252 legacy encoding normalize to valid UTF-8;
- disabling `opt_force_utf8` leaves downloaded bytes unchanged;
- the default media set accepts representative containers and raw AV1 input;
- configured extensions can be added and excluded with exclusion precedence;
- TUI and headless discovery receive the same resolved media extension set;
- existing search, provider, post-processing, headless, and configuration tests
  continue to pass.

## Scope boundaries

This change does not add provider translation features, inspect subtitle text
to guess whether it was AI-generated or intended for hearing-impaired viewers,
inspect file contents to guess whether an unsupported extension is a video, or
alter result ranking. It will not modify unrelated working-tree changes.
