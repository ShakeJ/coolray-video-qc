# Report interpretation

## Media

`report.json` contains `schema_version`, `scope`, `findings`, `structural_errors`, `warnings`, `checks_run`, and `not_checked`. Findings have `level`, `code`, and `detail`. Input paths and stream metadata are preserved for diagnosis.

- Missing video/audio, requested format mismatches, decode/filter failure, and frame extraction failures are errors.
- Black/freeze/silence events are candidates. `detail.time` is seconds; black events also have end and duration. Check boundaries against the source.
- `signal_scan.loudness` contains FFmpeg loudnorm input measurements. The default target is −16 LUFS; a difference greater than 2 LU or true peak above −1 dBTP warns. This is a local target, not a platform mandate. Silent input can have no finite loudness value.
- `av_boundary_delta_ms` compares stream start/end times, not spoken or visual sync.
- `frames[].requested_time` is the requested extraction time. Images are 640 pixels wide, sheet tiles 320. These are previews, not resolution certification. `reviewed: false` means extraction alone has not established visual review. Record actual observations separately.
- PQ/HLG transfer metadata signals HDR; SDR JPEG sampling is skipped. Metadata can be wrong and no HDR grading validation is performed.

`scan.log` records FFmpeg output. `error.json` means an incomplete run. Failed output directories are preserved; use a fresh directory for retry. `--timeout` applies per subprocess, not to the whole run. The file/pipe protocol restriction prevents network fetching but does not sandbox untrusted media.

## Captions

`captions` contains normalized text, `startMs`/`endMs`, weighted widths/CPS, and optional `frame_range_exclusive`. Frame ranges floor the start and ceil the exclusive end at the requested fps; input timings are unchanged. Text normalization/HTML stripping affects the report only.

Findings identify a 1-based `cue`; timing details are milliseconds. Overlap, reversed/negative time, empty text, invalid characters, and cues beyond a supplied duration are errors. Reading speed, long lines, duplicate IDs, and short duration are warnings.

| Preset | Max weighted CPS | Max weighted width/line | Max lines |
|---|---:|---:|---:|
| ko | 12 | 16 | 2 |
| ko-kids | 9 | 16 | 2 |
| latin | 17 | 42 | 2 |

The short-duration warning defaults to below 0.6 seconds. Korean width counts ASCII/Latin and punctuation/spacing as half, other characters as one, excluding combining marks. NFC normalization avoids inflated decomposed Hangul counts. This is not pixel measurement or full grapheme segmentation. Emojis and shaped text need rendered inspection. Basic WebVTT cue tracks are supported; styling/position semantics are not validated.

Use `--duration` in seconds for the final video boundary. Without it, this check is unavailable. JSON times must be finite numbers in milliseconds; seconds are not inferred. Audit simultaneous tracks separately or interpret intentional overlaps explicitly.
