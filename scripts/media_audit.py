#!/usr/bin/env python3
"""Read-only, renderer-independent FFmpeg audit. No playback or network calls."""
import argparse
import datetime
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def rate(value):
    try:
        result = float(Fraction(str(value)))
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def positive(value):
    result = number(value)
    if result is None or result <= 0:
        raise argparse.ArgumentTypeError('must be a finite positive number')
    return result


def run(argv, timeout):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                            stdin=subprocess.DEVNULL)
    return result.returncode, result.stdout, result.stderr


def primary_video(streams):
    return next((s for s in streams if s.get('codec_type') == 'video'
                 and not s.get('disposition', {}).get('attached_pic')), None)


def rotation(stream):
    values = [s.get('rotation') for s in stream.get('side_data_list', [])]
    values.append(stream.get('tags', {}).get('rotate'))
    return next((int(round(number(v))) % 360 for v in values if number(v) is not None), 0)


def geometry(stream):
    w, h = stream.get('width', 0), stream.get('height', 0)
    return (h, w) if rotation(stream) in (90, 270) else (w, h)


def stream_span(stream):
    start, duration = number(stream.get('start_time')), number(stream.get('duration'))
    if duration is None:
        ticks, base = number(stream.get('duration_ts')), rate(stream.get('time_base'))
        if ticks is not None and base is not None:
            duration = ticks * base
    return {'start': start, 'duration': duration,
            'end': start + duration if start is not None and duration is not None else None}


def finding(report, level, code, detail):
    report['findings'].append({'level': level, 'code': code, 'detail': detail})


def metadata_checks(data, args):
    streams = data.get('streams', [])
    video = primary_video(streams)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    report = {'schema_version': 1, 'scope': 'mechanical_checks_only', 'findings': [],
              'needs_visual_review': True, 'needs_audio_content_review': bool(audio),
              'streams': streams, 'format': data.get('format', {}), 'checks_run': ['ffprobe']}
    if video is None:
        finding(report, 'error', 'missing_video', 'No non-cover-art video stream')
        return report, None, audio
    w, h = geometry(video)
    fps = rate(video.get('avg_frame_rate')) or rate(video.get('r_frame_rate'))
    report['video'] = {'stream_index': video['index'], 'display_width': w, 'display_height': h,
                       'rotation': rotation(video), 'fps': fps, 'span': stream_span(video)}
    duration = stream_span(video)['duration']
    if duration is None:
        duration = number(data.get('format', {}).get('duration'))
        finding(report, 'warning', 'video_duration_fallback', 'Using container duration for sampling')
    report['duration_for_sampling'] = duration
    if duration is None or duration <= 0:
        finding(report, 'error', 'unknown_duration', 'No finite positive duration')
    if args.expect_size and (w, h) != args.expect_size:
        finding(report, 'error', 'size_mismatch', {'expected': args.expect_size, 'actual': [w, h]})
    if args.expect_fps and (fps is None or abs(fps - args.expect_fps) > .001):
        finding(report, 'error', 'fps_mismatch', {'expected': args.expect_fps, 'actual': fps})
    tolerance = max(.05, 1 / fps) if fps else .05
    if args.expect_duration and (duration is None or abs(duration - args.expect_duration) > tolerance):
        finding(report, 'error', 'duration_mismatch', {'expected': args.expect_duration, 'actual': duration})
    if args.require_audio and audio is None:
        finding(report, 'error', 'missing_audio', 'Audio stream required by caller')
    if audio:
        vspan, aspan = stream_span(video), stream_span(audio)
        report['audio_span'] = aspan
        if all(vspan[k] is not None and aspan[k] is not None for k in ('start', 'end')):
            delta = {k: (aspan[k] - vspan[k]) * 1000 for k in ('start', 'end')}
            report['av_boundary_delta_ms'] = delta
            if max(abs(v) for v in delta.values()) > tolerance * 1000:
                finding(report, 'warning', 'av_boundary_difference', delta)
        else:
            finding(report, 'warning', 'av_boundaries_unknown', 'Cannot compare stream start/end')
    transfer = video.get('color_transfer')
    report['hdr_signalled'] = transfer in ('smpte2084', 'arib-std-b67')
    if report['hdr_signalled']:
        finding(report, 'warning', 'hdr_signalled', 'Preserve HDR or perform an explicit color-managed SDR conversion; retagging is insufficient')
    for key in ('color_space', 'color_transfer', 'color_primaries'):
        if video.get(key) in (None, 'unknown', 'unspecified'):
            finding(report, 'warning', 'color_metadata_unknown', key)
    if video.get('sample_aspect_ratio') not in (None, 'N/A', '0:1', '1:1'):
        finding(report, 'warning', 'non_square_pixels', video.get('sample_aspect_ratio'))
    if video.get('field_order') not in (None, 'unknown', 'progressive'):
        finding(report, 'warning', 'interlaced_source', video.get('field_order'))
    return report, video, audio


def parse_scan(log):
    events = []
    patterns = [('black', r'black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)'),
                ('freeze', r'freeze_start:\s*([\d.]+)'),
                ('freeze_end', r'freeze_end:\s*([\d.]+)'),
                ('silence', r'silence_start:\s*(-?[\d.]+)'),
                ('silence_end', r'silence_end:\s*(-?[\d.]+)')]
    for kind, pattern in patterns:
        for match in re.finditer(pattern, log):
            events.append({'kind': kind, 'time': float(match[1]),
                           **({'end': float(match[2]), 'duration': float(match[3])}
                              if kind == 'black' else {})})
    loudness = None
    for block in re.findall(r'\{[^{}]*"input_i"[^{}]*\}', log, re.S):
        try:
            loudness = {key: number(value) for key, value in json.loads(block).items()
                        if key.startswith('input_')}
        except json.JSONDecodeError:
            continue
    vfr = re.findall(r'VFR:([\d.]+)', log)
    return {'events': sorted(events, key=lambda e: e['time']), 'loudness': loudness,
            'vfrdet_ratio': float(vfr[-1]) if vfr else None}


def scan(media, video, audio, args, out, report):
    argv = ['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-xerror',
            '-err_detect', 'explode', '-protocol_whitelist', 'file,pipe',
            '-i', str(media), '-map', f'0:{video["index"]}',
            '-vf', f'blackdetect=d={args.black_seconds}:pix_th=0.10:pic_th=0.98,'
                   f'freezedetect=n=-60dB:d={args.freeze_seconds},vfrdet']
    if audio:
        argv += ['-map', f'0:{audio["index"]}', '-af',
                 f'silencedetect=n=-50dB:d={args.silence_seconds},'
                 f'loudnorm=I={args.target_lufs}:TP=-1:LRA=11:print_format=json']
    argv += ['-f', 'null', '-']
    try:
        code, _, log = run(argv, args.timeout)
    except subprocess.TimeoutExpired:
        finding(report, 'error', 'scan_timeout', 'Full scan incomplete; increase --timeout or use a faster machine')
        return
    (out / 'scan.log').write_text(log)
    report['checks_run'].append('full_decode_and_signal_scan')
    if code:
        finding(report, 'error', 'decode_or_filter_failure', {'returncode': code, 'log': 'scan.log'})
        return
    result = parse_scan(log)
    report['signal_scan'] = result
    for event in result['events']:
        if event['kind'] in ('black', 'freeze', 'silence'):
            finding(report, 'warning', event['kind'] + '_candidate', event)
    loud = result['loudness']
    if audio and loud is None:
        finding(report, 'error', 'loudness_missing', 'Requested audio scan produced no measurements')
    elif loud:
        if loud.get('input_i') is None:
            finding(report, 'warning', 'silent_or_unmeasurable_audio', loud)
        elif abs(loud['input_i'] - args.target_lufs) > 2:
            finding(report, 'warning', 'loudness_off_local_target', {'measured_lufs': loud['input_i'], 'local_target': args.target_lufs})
        if loud.get('input_tp') is not None and loud['input_tp'] > -1:
            finding(report, 'warning', 'true_peak_above_local_target', loud['input_tp'])
    if result['vfrdet_ratio'] is not None and result['vfrdet_ratio'] > .01:
        finding(report, 'warning', 'variable_frame_intervals_candidate', result['vfrdet_ratio'])


def sample(media, args, out, report):
    duration = report['duration_for_sampling']
    if not duration:
        return
    if report['hdr_signalled']:
        finding(report, 'warning', 'hdr_frame_sampling_skipped', 'SDR JPEG previews would misrepresent HDR; use a color-managed preview outside this tool')
        return
    fps = report['video']['fps'] or 30
    last = max(0, duration - 1 / fps)
    times = args.sample_times or [last * i / (args.samples - 1) for i in range(args.samples)]
    if any(t < 0 or t > last + .0001 for t in times):
        finding(report, 'error', 'sample_time_outside_video', times)
        return
    frames = out / 'frames'
    frames.mkdir()
    report['frames'] = []
    for i, t in enumerate(times):
        target = frames / f'{i:03d}-{t:.3f}s.jpg'
        code, _, log = run(['ffmpeg', '-v', 'error', '-nostdin', '-ss', str(t),
                            '-protocol_whitelist', 'file,pipe', '-i', str(media),
                            '-map', f'0:{report["video"]["stream_index"]}', '-frames:v', '1',
                            '-vf', 'scale=640:-2', '-q:v', '2', str(target)], args.timeout)
        if code or not target.exists() or target.stat().st_size == 0:
            finding(report, 'error', 'frame_extract_failed', {'time': t, 'log': log[-1000:]})
        else:
            report['frames'].append({'requested_time': t, 'path': str(target), 'reviewed': False})
    report['checks_run'].append('decoded_frame_sampling')
    # A sheet is navigation, not a substitute for native-resolution crops.
    if len(report['frames']) == len(times):
        # glob uses FFmpeg's input handler, not a shell; filenames are generated here.
        code, _, log = run(['ffmpeg', '-v', 'error', '-nostdin', '-pattern_type', 'glob',
                            '-i', str(frames / '*.jpg'), '-vf', f'scale=320:-2,tile=3x{math.ceil(len(times)/3)}:padding=4:margin=4',
                            '-frames:v', '1', str(out / 'contact-sheet.jpg')], args.timeout)
        if code:
            finding(report, 'warning', 'contact_sheet_failed', log[-1000:])
        else:
            report['contact_sheet'] = str(out / 'contact-sheet.jpg')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('media', type=Path)
    parser.add_argument('--out', required=True, type=Path, help='new directory; never overwritten')
    parser.add_argument('--metadata-only', action='store_true')
    parser.add_argument('--require-audio', action='store_true')
    parser.add_argument('--expect-size', help='display dimensions, e.g. 1080x1920')
    parser.add_argument('--expect-fps', help='number or rational, e.g. 30000/1001')
    parser.add_argument('--expect-duration', type=positive)
    parser.add_argument('--target-lufs', type=float, default=-16, help='local production target, not a platform mandate')
    parser.add_argument('--black-seconds', type=positive, default=.15)
    parser.add_argument('--freeze-seconds', type=positive, default=1)
    parser.add_argument('--silence-seconds', type=positive, default=1)
    parser.add_argument('--samples', type=int, choices=range(2, 13), default=6)
    parser.add_argument('--sample-times', help='comma-separated seconds for cut boundaries or clip start/middle/end')
    parser.add_argument('--timeout', type=positive, default=300, help='per-process timeout in seconds')
    args = parser.parse_args(argv)
    if args.expect_size:
        if not re.fullmatch(r'[1-9]\d*x[1-9]\d*', args.expect_size):
            parser.error('--expect-size must be WIDTHxHEIGHT')
        args.expect_size = tuple(map(int, args.expect_size.split('x')))
    if args.expect_fps:
        args.expect_fps = rate(args.expect_fps)
        if args.expect_fps is None:
            parser.error('--expect-fps must be positive and finite')
    if not math.isfinite(args.target_lufs) or not -70 <= args.target_lufs <= -5:
        parser.error('--target-lufs must be between -70 and -5')
    if args.sample_times:
        args.sample_times = [number(t) for t in args.sample_times.split(',')]
        if len(args.sample_times) > 24 or any(t is None or t < 0 for t in args.sample_times):
            parser.error('--sample-times requires 1–24 finite non-negative seconds')
    return args


def main(argv=None):
    args = parse_args(argv)
    out = None
    try:
        media = args.media.expanduser().resolve(strict=True)
        if not media.is_file():
            raise ValueError('Input must be a local file')
        for command in ['ffprobe'] + ([] if args.metadata_only else ['ffmpeg']):
            if shutil.which(command) is None:
                raise ValueError(f'Missing existing tool: {command}')
        args.out = args.out.expanduser().absolute()
        args.out.mkdir(parents=True, exist_ok=False)
        out = args.out
        code, stdout, stderr = run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                                   '-show_streams', '-show_format',
                                   '-of', 'json', str(media)], args.timeout)
        if code:
            raise ValueError('ffprobe failed: ' + stderr[-1500:])
        report, video, audio = metadata_checks(json.loads(stdout), args)
        report.update({'input': str(media), 'size_bytes': media.stat().st_size,
                       'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        if video and not args.metadata_only:
            scan(media, video, audio, args, out, report)
            sample(media, args, out, report)
        report['structural_errors'] = sum(f['level'] == 'error' for f in report['findings'])
        report['warnings'] = sum(f['level'] == 'warning' for f in report['findings'])
        report['not_checked'] = ['story comprehension', 'identity/physical continuity', 'lip sync',
                                  'native detail/true resolution', 'subtitle pixel layout', 'asset rights']
        if args.metadata_only:
            report['not_checked'] += ['full decode', 'signal defects', 'loudness', 'decoded frames']
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
        print(json.dumps({'report': str(out / 'report.json'), 'structural_errors': report['structural_errors'],
                          'warnings': report['warnings'], 'needs_visual_review': True}, ensure_ascii=False))
        return 1 if report['structural_errors'] else 0
    except (OSError, ValueError, subprocess.TimeoutExpired, KeyError) as exc:
        error = {'error': str(exc), 'scope': 'audit_incomplete'}
        if out:
            (out / 'error.json').write_text(json.dumps(error, ensure_ascii=False, indent=2))
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
