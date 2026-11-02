#!/usr/bin/env python3
"""Behavioral regressions for audit evidence, error handling and non-mutation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def cli(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, timeout=90)


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def audit(self, data, suffix='.json', *extra):
        source = self.root / ('captions' + suffix)
        source.write_text(json.dumps(data, ensure_ascii=False) if suffix == '.json' else data)
        result = cli('captions.py', source, *extra)
        return result.returncode, json.loads(result.stdout or result.stderr)

    def test_srt_and_json_have_same_millisecond_timeline(self):
        code, a = self.audit('1\n00:00:00,250 --> 00:00:01,750\n가격은 2만 원입니다\n', '.srt')
        code2, b = self.audit([{'startMs': 250, 'endMs': 1750, 'text': '가격은 2만 원입니다'}])
        self.assertEqual((code, code2), (0, 0))
        self.assertEqual(a['captions'], b['captions'])

    def test_vtt_notes_settings_and_tags(self):
        code, r = self.audit('WEBVTT\n\nNOTE metadata\nignored\n\nintro\n00:00.000 --> 00:02.000 align:start\n<i>안녕하세요</i>\n', '.vtt')
        self.assertEqual(code, 0)
        self.assertEqual(r['captions'][0]['text'], '안녕하세요')
        self.assertEqual(r['captions'][0]['endMs'], 2000)

    def test_nested_overlap_and_past_end_are_errors(self):
        code, r = self.audit([{'startMs': 0, 'endMs': 5000, 'text': '긴 자막'},
                              {'startMs': 1000, 'endMs': 1500, 'text': '둘'},
                              {'startMs': 2000, 'endMs': 2500, 'text': '셋'}], '.json', '--duration', '3')
        self.assertEqual(code, 1)
        codes = [f['code'] for f in r['findings']]
        self.assertEqual(codes.count('overlap'), 2)
        self.assertIn('past_video_end', codes)

    def test_no_inference_of_seconds_and_reject_nonfinite(self):
        code, _ = self.audit([{'start': 0, 'end': 2, 'text': '단위 없음'}])
        self.assertEqual(code, 2)
        code, _ = self.audit([{'startMs': 0, 'endMs': float('nan'), 'text': '잘못된 시간'}])
        self.assertEqual(code, 2)

    def test_negative_reversed_and_out_of_order(self):
        code, r = self.audit([{'startMs': 2000, 'endMs': 1000, 'text': '역순'},
                              {'startMs': -1, 'endMs': 400, 'text': '음수'}])
        self.assertEqual(code, 1)
        self.assertIn('out_of_order', [f['code'] for f in r['findings']])

    def test_nfc_does_not_inflate_korean_reading_count(self):
        _, a = self.audit([{'startMs': 0, 'endMs': 1000, 'text': '가'}])
        _, b = self.audit([{'startMs': 0, 'endMs': 1000, 'text': '\u1100\u1161'}])
        self.assertEqual(a['captions'][0]['weighted_cps'], b['captions'][0]['weighted_cps'])

    def test_rational_fps_exclusive_range(self):
        code, r = self.audit([{'startMs': 1001, 'endMs': 2002, 'text': '시간'}], '.json', '--fps', '30000/1001')
        self.assertEqual(code, 0)
        self.assertEqual(r['captions'][0]['frame_range_exclusive'], [30, 60])

    def test_reading_speed_is_warning_not_silent_rewrite(self):
        text = '읽는 속도가 아주 빠른 문장을 그대로 보존합니다'
        code, r = self.audit([{'startMs': 0, 'endMs': 300, 'text': text}])
        self.assertEqual(code, 0)
        self.assertIn('reading_speed', [f['code'] for f in r['findings']])
        self.assertEqual(r['captions'][0]['text'], text)

    def test_existing_output_is_not_overwritten(self):
        source = self.root / 'x.json'
        source.write_text('[{"startMs":0,"endMs":1000,"text":"확인"}]')
        target = self.root / 'report.json'
        target.write_text('keep')
        self.assertEqual(cli('captions.py', source, '--out', target).returncode, 2)
        self.assertEqual(target.read_text(), 'keep')


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires existing FFmpeg')
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.good = cls.root / 'good.mp4'
        cls.silent = cls.root / 'black-no-audio.mp4'
        cls.hdr = cls.root / 'hdr-tagged.mp4'
        def make(target, inputs, options):
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', *inputs, *options, str(target)],
                           check=True, capture_output=True, timeout=45)
        make(cls.good, ['-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=2.4',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2.4'],
             ['-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-pix_fmt', 'yuv420p',
              '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709'])
        make(cls.silent, ['-f', 'lavfi', '-i', 'color=black:size=320x180:rate=30:duration=1.6'],
             ['-c:v', 'libx264', '-preset', 'ultrafast'])
        make(cls.hdr, ['-i', str(cls.good)], ['-c', 'copy', '-color_trc', 'smpte2084',
                                           '-color_primaries', 'bt2020', '-colorspace', 'bt2020nc'])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def audit(self, source, *args):
        out = self.root / self.id().split('.')[-1]
        result = cli('media_audit.py', source, '--out', out, *args)
        report = json.loads((out / 'report.json').read_text()) if (out / 'report.json').exists() else None
        return result, report, out

    def test_decode_samples_and_input_preserved(self):
        before = hashlib.sha256(self.good.read_bytes()).hexdigest()
        result, r, out = self.audit(self.good, '--expect-size', '320x180', '--require-audio')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('full_decode_and_signal_scan', r['checks_run'])
        self.assertEqual(len(r['frames']), 6)
        self.assertTrue((out / 'contact-sheet.jpg').exists())
        self.assertTrue(r['needs_visual_review'])
        self.assertIsNotNone(r['signal_scan']['loudness']['input_i'])
        self.assertEqual(before, hashlib.sha256(self.good.read_bytes()).hexdigest())

    def test_missing_audio_and_size_mismatch_fail(self):
        result, r, _ = self.audit(self.silent, '--require-audio', '--expect-size', '1080x1920', '--metadata-only')
        self.assertEqual(result.returncode, 1)
        self.assertEqual({f['code'] for f in r['findings'] if f['level']=='error'}, {'missing_audio', 'size_mismatch'})

    def test_intended_black_freeze_warns_without_auto_reject(self):
        result, r, _ = self.audit(self.silent)
        self.assertEqual(result.returncode, 0, result.stderr)
        codes = {f['code'] for f in r['findings']}
        self.assertIn('black_candidate', codes)
        self.assertIn('freeze_candidate', codes)

    def test_hdr_metadata_does_not_make_misleading_jpeg(self):
        result, r, _ = self.audit(self.hdr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(r['hdr_signalled'])
        self.assertNotIn('frames', r)
        self.assertIn('hdr_frame_sampling_skipped', [f['code'] for f in r['findings']])

    def test_bad_input_and_existing_output_fail_honestly(self):
        bad = self.root / 'not-video.mp4'
        bad.write_text('not a video')
        result, r, out = self.audit(bad)
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(r)
        self.assertTrue((out / 'error.json').exists())
        (out / 'keep.txt').write_text('keep')
        self.assertEqual(cli('media_audit.py', self.good, '--out', out).returncode, 2)
        self.assertEqual((out / 'keep.txt').read_text(), 'keep')

    def test_metadata_only_reports_omitted_checks(self):
        result, r, _ = self.audit(self.good, '--metadata-only')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(r['checks_run'], ['ffprobe'])
        self.assertIn('full decode', r['not_checked'])
        self.assertNotIn('frames', r)

    def test_corrupt_packet_is_detected_after_valid_container_probe(self):
        packets = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                             '-show_packets', '-of', 'json', str(self.good)],
                                            capture_output=True, text=True, check=True).stdout)['packets']
        packet = next(p for p in packets if int(p['size']) > 300)
        data = bytearray(self.good.read_bytes())
        begin, size = int(packet['pos']), int(packet['size'])
        data[begin+20:begin+size] = bytes(size-20)
        source = self.root / 'corrupt-packet.mp4'
        source.write_bytes(data)
        result, r, _ = self.audit(source, '--samples', '2')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('decode_or_filter_failure', [f['code'] for f in r['findings']])



if __name__ == '__main__':
    unittest.main(verbosity=2)
