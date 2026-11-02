#!/usr/bin/env python3
"""Create synthetic demo footage without playback, network, or source assets."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='new output directory')
    args = parser.parse_args()
    try:
        if not shutil.which('ffmpeg'):
            raise ValueError('FFmpeg is required on PATH')
        out = args.out.expanduser().absolute()
        out.mkdir(parents=True, exist_ok=False)
        subprocess.run([
            'ffmpeg', '-v', 'error', '-nostdin', '-n',
            '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=3',
            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-color_primaries', 'bt709', '-color_trc', 'bt709',
            '-colorspace', 'bt709', str(out / 'demo.mp4')
        ], check=True, timeout=60)
        shutil.copyfile(Path(__file__).with_name('clean.srt'), out / 'demo.srt')
        print(out / 'demo.mp4')
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
