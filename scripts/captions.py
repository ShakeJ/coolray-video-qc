#!/usr/bin/env python3
"""Audit single-track SRT/WebVTT or startMs/endMs/text JSON without retiming."""
import argparse
from fractions import Fraction
from html import unescape
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import sys
import unicodedata


PROFILES = {'ko': {'cps': 12, 'width': 16, 'lines': 2},
            'ko-kids': {'cps': 9, 'width': 16, 'lines': 2},
            'latin': {'cps': 17, 'width': 42, 'lines': 2}}


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.parts.append('\n')


def plain(text):
    parser = PlainText()
    parser.feed(text)
    return unicodedata.normalize('NFC', unescape(''.join(parser.parts)))


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Timestamp must be a finite JSON number in milliseconds')
    return value


def time_ms(text):
    match = re.fullmatch(r'(?:(\d{2,}):)?([0-5]\d):([0-5]\d)[,.](\d{3})', text)
    if not match:
        raise ValueError('Unsupported timestamp: ' + text)
    hours, minutes, seconds, ms = match.groups()
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(ms)


def load_captions(path):
    data = path.read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    if path.suffix.lower() == '.json':
        obj = json.loads(data)
        rows = obj if isinstance(obj, list) else obj.get('captions') if isinstance(obj, dict) else None
        if not isinstance(rows, list):
            raise ValueError('JSON must be an array or {"captions": [...]} using explicit startMs/endMs')
        result = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or not all(k in row for k in ('startMs', 'endMs', 'text')):
                raise ValueError(f'Caption {i+1}: require startMs/endMs/text; seconds are never inferred')
            if not isinstance(row['text'], str):
                raise ValueError(f'Caption {i+1}: text must be a string')
            result.append({'id': str(row.get('id', i+1)), 'startMs': finite(row['startMs']),
                           'endMs': finite(row['endMs']), 'text': row['text']})
        return result
    if path.suffix.lower() not in ('.srt', '.vtt'):
        raise ValueError('Supported formats: .srt, .vtt, .json (ASS requires an explicit conversion)')
    vtt = path.suffix.lower() == '.vtt'
    blocks = re.split(r'\n[ \t]*\n', data.strip())
    result = []
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        if vtt and (lines[0].startswith('WEBVTT') or lines[0] in ('STYLE', 'REGION')
                    or re.match(r'^NOTE(?:\s|$)', lines[0])):
            continue
        index = 0 if '-->' in lines[0] else 1
        if index >= len(lines) or '-->' not in lines[index]:
            raise ValueError('Malformed cue: ' + lines[0][:100])
        match = re.fullmatch(r'\s*(\S+)\s+-->\s+(\S+)(?:\s+.*)?', lines[index])
        if not match:
            raise ValueError('Malformed timing line: ' + lines[index])
        result.append({'id': lines[0] if index else str(len(result)+1),
                       'startMs': time_ms(match[1]), 'endMs': time_ms(match[2]),
                       'text': '\n'.join(lines[index+1:])})
    return result


def width(text, profile):
    """A reading heuristic, never glyph/pixel layout validation."""
    text = unicodedata.normalize('NFC', text)
    total = 0
    for char in text:
        if unicodedata.category(char).startswith('M') or char in ('\u200d', '\ufe0f'):
            continue
        if profile == 'latin':
            total += 1
        else:
            # Local approximation of Korean timed-text weighted character count.
            # Emoji sequences and shaped text still require a rendered-frame review.
            latin_or_narrow = ord(char) < 128 or 'LATIN' in unicodedata.name(char, '')
            total += .5 if latin_or_narrow or unicodedata.category(char).startswith(('P', 'Z')) else 1
    return total


def audit(rows, args):
    findings, details = [], []
    def add(level, code, index, value):
        findings.append({'level': level, 'code': code, 'cue': index, 'detail': value})
    last_start, active_end = -1, -1
    ids = set()
    if not rows:
        add('error', 'empty_track', None, 'No captions')
    for index, row in enumerate(rows, 1):
        start, end = row['startMs'], row['endMs']
        if row['id'] in ids:
            add('warning', 'duplicate_id', index, row['id'])
        ids.add(row['id'])
        valid = start >= 0 and end > start
        if not valid:
            add('error', 'invalid_range', index, {'startMs': start, 'endMs': end})
        if start < last_start:
            add('error', 'out_of_order', index, start)
        if valid and start < active_end:
            add('error', 'overlap', index, {'activeEndMs': active_end, 'startMs': start})
        if args.duration is not None and end > args.duration * 1000 + .001:
            add('error', 'past_video_end', index, end)
        if valid:
            active_end = max(active_end, end)
        last_start = start
        text = plain(row['text'])
        lines = text.splitlines()
        if not text.strip():
            add('error', 'empty_text', index, '')
        if len(lines) > args.max_lines:
            add('warning', 'too_many_lines', index, len(lines))
        widths = [width(line, args.profile) for line in lines]
        if any(w > args.max_width for w in widths):
            add('warning', 'line_too_wide', index, widths)
        seconds = (end - start) / 1000
        cps = sum(widths) / seconds if seconds > 0 else None
        if cps is not None and cps > args.max_cps:
            add('warning', 'reading_speed', index, round(cps, 3))
        if valid and seconds < args.min_duration:
            add('warning', 'short_duration', index, seconds)
        if '\ufffd' in text:
            add('error', 'replacement_character', index, text)
        if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
            add('error', 'control_character', index, 'Unexpected control character')
        detail = {'id': row['id'], 'startMs': start, 'endMs': end, 'text': text,
                  'weighted_widths': widths, 'weighted_cps': cps}
        if args.fps:
            detail['frame_range_exclusive'] = [math.floor(Fraction(str(start))/1000 * args.fps),
                                                math.ceil(Fraction(str(end))/1000 * args.fps)]
        details.append(detail)
    return {'schema_version': 1, 'scope': 'single_track_timing_and_readability_heuristics',
            'profile': args.profile, 'limits': {'max_cps': args.max_cps, 'max_width': args.max_width,
                                              'max_lines': args.max_lines, 'min_duration': args.min_duration},
            'captions': details, 'findings': findings,
            'structural_errors': sum(f['level'] == 'error' for f in findings),
            'warnings': sum(f['level'] == 'warning' for f in findings),
            'not_checked': ['spoken wording/ASR correctness', 'speech/visual sync', 'glyph pixel bounds',
                            'font fallback', 'platform UI occlusion', 'translation meaning']}


def positive(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captions', type=Path)
    parser.add_argument('--out', type=Path, help='new JSON report file; otherwise stdout')
    parser.add_argument('--duration', type=positive, help='final video duration in seconds')
    parser.add_argument('--fps', help='timeline fps, e.g. 30000/1001; reports frame ranges without retiming')
    parser.add_argument('--profile', choices=PROFILES, default='ko')
    parser.add_argument('--max-cps', type=positive)
    parser.add_argument('--max-width', type=positive)
    parser.add_argument('--max-lines', type=int, default=2)
    parser.add_argument('--min-duration', type=positive, default=.6, help='local warning threshold, seconds')
    args = parser.parse_args(argv)
    try:
        args.fps = Fraction(args.fps) if args.fps else None
        if args.fps is not None and args.fps <= 0:
            raise ValueError('fps must be positive')
        if args.max_lines < 1:
            raise ValueError('max-lines must be positive')
        args.max_cps = args.max_cps or PROFILES[args.profile]['cps']
        args.max_width = args.max_width or PROFILES[args.profile]['width']
        rows = load_captions(args.captions.expanduser())
        report = audit(rows, args)
        serialized = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        if args.out:
            target = args.out.expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as handle:
                handle.write(serialized + '\n')
            print(json.dumps({'report': str(target.absolute()), 'structural_errors': report['structural_errors'],
                              'warnings': report['warnings']}, ensure_ascii=False))
        else:
            print(serialized)
        return 1 if report['structural_errors'] else 0
    except (OSError, ValueError, ZeroDivisionError) as exc:
        print(json.dumps({'error': str(exc), 'scope': 'audit_incomplete'}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
