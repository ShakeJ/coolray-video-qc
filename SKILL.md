---
name: coolray-video-qc
description: Inspect local videos and SRT/WebVTT/JSON subtitles for technical defects, timing errors, and readability warnings. Use before delivery or to diagnose a render; produces reports and review frames without editing inputs.
license: MIT
---

# Coolray Video QC

Run the bundled helpers from this skill's directory. Python 3.10+ is required; video checks also need `ffmpeg` and `ffprobe` on PATH. Caption checks use only the Python standard library. Report missing dependencies instead of silently skipping checks.

## Video

Use an unused output directory. Add size, fps, duration, or audio requirements only when the user or delivery specification provides them.

```bash
python3 scripts/media_audit.py /path/to/video.mp4 --out /path/to/qa/video-v1
# Only when this delivery format was specified:
python3 scripts/media_audit.py /path/to/video.mp4 --out /path/to/qa/video-v2 \
  --expect-size 1080x1920 --expect-fps 30 --require-audio
```

Read `report.json`. A full run decodes the video, scans for signal issues, and extracts review frames. `--metadata-only` omits those checks; say so. Open the contact sheet and relevant frames when image inspection is available. Extraction alone is not visual review. Small previews do not prove native detail. HDR JPEG extraction is skipped to avoid misleading SDR images.

Black, frozen, silent, and loudness warnings are review candidates. Holds, fades, and pauses may be intentional. Stream boundary agreement does not establish lip sync. Resolve decode failures before relying on later findings.

## Subtitles

```bash
python3 scripts/captions.py /path/to/captions.srt --duration 60 --fps 30 \
  --profile ko --out /path/to/qa/captions.json
```

Choose `ko`, `ko-kids`, or `latin` for the material. Adjust `--max-cps`, `--max-width`, `--max-lines`, and `--min-duration` to the project; presets are heuristics, not delivery standards. Supply actual video duration when checking cues against its end. JSON requires explicit `startMs`, `endMs`, and `text`; never guess units. Checks assume one track; intentional overlapping speakers/tracks need separate interpretation.

## Report

Both tools use exit code **0** for no structural errors (warnings may remain), **1** for detected structural errors, and **2** for an incomplete run or invalid input. Check both the exit code and report. Never convert a failed run into a pass.

Summarize errors first, then actionable warnings with times/cue numbers, output files, and unchecked items. These tools do not certify story quality, ASR accuracy, lip sync, fonts, true source resolution, or rights. They do not rewrite, retime, play, or upload media. Reports contain source material and local paths; share them only as requested.

Read [references/reports.md](references/reports.md) for fields and thresholds. Run either script with `--help` for all options.
