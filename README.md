# Coolray Video QC

[![Checks](https://github.com/ShakeJ/coolray-video-qc/actions/workflows/ci.yml/badge.svg)](https://github.com/ShakeJ/coolray-video-qc/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A small agent skill and command-line toolkit for checking local video and subtitle files. Python standard library + FFmpeg. No account, API key, upload, or playback.

[한국어 안내](README.ko.md) · [Download v0.1.0](https://github.com/ShakeJ/coolray-video-qc/releases/tag/v0.1.0) · MIT

## What it checks

- Video: decode failures, requested dimensions/fps/duration, missing audio, stream boundaries, color metadata, black/frozen/silent candidates, loudness, and review frames.
- Subtitles: SRT, WebVTT, or millisecond JSON; invalid timing, overlaps, cues past the video end, reading speed, and line length. Korean, Korean children, and Latin-script presets are adjustable heuristics.
- Output: JSON reports, scan logs, and an SDR contact sheet. Source files are not modified.

It wraps existing FFmpeg capabilities and adds consistent reports and subtitle checks. A clean report is not a certificate of creative quality, lip sync, accessibility compliance, or media rights.

## Requirements

Python **3.10+**. Video auditing additionally needs `ffmpeg` and `ffprobe` on PATH, with `blackdetect`, `freezedetect`, `vfrdet`, `silencedetect`, `loudnorm`, and JPEG support. The demo/tests also use `libx264`, AAC, and `h264_metadata`. No pip packages are required.

For example, install FFmpeg with your usual package manager (`brew install ffmpeg` on macOS or `sudo apt install ffmpeg` on Debian/Ubuntu). Install Python separately if necessary. The scripts never install dependencies themselves.

macOS is locally tested. A Linux CI workflow is included; Windows has not been validated. The contact-sheet command requires an FFmpeg build with glob support.

## Get the code

Download the ZIP from [Releases](https://github.com/ShakeJ/coolray-video-qc/releases), or clone this repository:

```bash
git clone https://github.com/ShakeJ/coolray-video-qc.git
cd coolray-video-qc
```

## Try without an agent

Run from the extracted `coolray-video-qc` directory:

```bash
python3 scripts/captions.py examples/clean.en.srt --duration 3 --profile latin
python3 scripts/captions.py examples/overlap.srt --duration 3 --profile ko
# The second command intentionally exits 1: overlapping cues are errors.

python3 examples/make_demo.py --out /tmp/coolray-video-qc-demo
python3 scripts/media_audit.py /tmp/coolray-video-qc-demo/demo.mp4 \
  --out /tmp/coolray-video-qc-demo/review --expect-size 320x180 --require-audio
```

The demo creates an original, synthetic 3-second pattern and an encoded tone; it never plays audio. Use fresh output locations when repeating a command. Open `review/contact-sheet.jpg` and read `review/report.json`. Warnings can remain even when the command exits 0.

For your own material:

```bash
python3 scripts/media_audit.py ./video.mp4 --out ./qa/video-v1
python3 scripts/captions.py ./captions.vtt --duration 60 --fps 30000/1001 \
  --profile latin --out ./qa/captions-v1.json
```

Caption checks are single-track. Explicit JSON format:

```json
[{"startMs": 0, "endMs": 1200, "text": "Hello"}]
```

## Install as a skill

Keep the extracted folder named `coolray-video-qc`, with `SKILL.md` at its root. Run the following from its parent directory. These commands fail rather than replace an existing installation.

Codex, project-local:

```bash
mkdir -p .agents/skills
python3 -c 'import shutil; shutil.copytree("coolray-video-qc", ".agents/skills/coolray-video-qc")'
```

Claude Code, personal:

```bash
python3 -c 'from pathlib import Path; import shutil; shutil.copytree("coolray-video-qc", Path.home()/".claude/skills/coolray-video-qc")'
```

Start a new agent session if the skill is not discovered. Try: “Use coolray-video-qc to check this video and subtitles. Report errors, warnings, and unchecked items.” In Codex you can invoke `$coolray-video-qc`; in Claude Code use `/coolray-video-qc`.

Discovery follows the host configuration; Python CLI execution alone does not prove host integration. See the [OpenAI skill guide](https://learn.chatgpt.com/docs/build-skills) and [Claude skill guide](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview).

## Results

| Exit | Meaning |
|---|---|
| 0 | No structural errors in the completed checks; warnings may remain |
| 1 | Structural errors detected |
| 2 | Invalid input, unavailable dependency, or incomplete execution |

Do not automatically reject an intentional hold, fade, or pause. `--metadata-only` does not decode or extract frames. HDR sources do not receive SDR JPEG previews. The loudness target is a local heuristic, not a platform requirement. Details: [report reference](references/reports.md).

Reports include local paths, metadata, subtitle text, and source images; review them before sharing. The tools inspect the first non-cover video stream and first audio stream; multi-program/multi-track delivery needs additional checks.

## Develop and package

```bash
python3 -m unittest discover -s tests -v
python3 tools/package.py
```

Tests create disposable synthetic media. FFmpeg tests are skipped if it is unavailable. Packaging writes an allowlisted, reproducible ZIP and SHA-256 checksum into `dist/`, excluding generated reports, media, caches, and Git history. No remote publication occurs.

## License and dependencies

Original code and documentation are MIT licensed; see [LICENSE](LICENSE). FFmpeg is separately installed and is not bundled; see [FFmpeg legal information](https://ffmpeg.org/legal.html) for its build-dependent license. Detection behavior follows the [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) and [ffprobe](https://ffmpeg.org/ffprobe.html) documentation. No third-party footage, voices, fonts, or production assets are included.
