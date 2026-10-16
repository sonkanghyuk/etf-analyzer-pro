import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

from studio import ai, media, subtitles, timeline, validation


class TimelineTests(unittest.TestCase):
    def test_cut_speed_maps_every_stream_without_accumulated_rounding(self):
        clip = dict(start=0, end=10, speed=1.25, cuts=[dict(start=4, end=6)])
        self.assertAlmostEqual(timeline.duration(clip), 6.4)
        self.assertEqual(timeline.source_time(clip, 3.2), 6)
        cues = [dict(id='a', start=3, end=7, text='cut-crossing')]
        mapped = timeline.mapped_cues(clip, cues)
        self.assertEqual([(c['start'], c['end']) for c in mapped], [(2.4, 3.2), (3.2, 4.0)])
        self.assertEqual(cues[0]['start'], 3)

    def test_overlapping_cuts_merge_and_preserve_order(self):
        clip = dict(start=0, end=10, speed=1, cuts=[dict(start=3, end=6), dict(start=2, end=4)])
        self.assertEqual(timeline.segments(clip), [dict(start=0, end=2), dict(start=6, end=10)])
        for bad in (float('nan'), float('inf'), -1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                timeline.duration(dict(start=bad, end=10))

    def test_srt_roundtrip_preserves_numeric_text_and_line_break(self):
        text = 'SOXL / 3.07% / 0.1%p / 1,000,000원\n긴 한글'
        cues = subtitles.parse(('1\n00:00:00,100 --> 00:00:02,900\n' + text).encode(), 10)
        self.assertEqual(subtitles.parse(subtitles.export(cues).encode(), 10)[0]['text'], text)
        for malformed in ('1\n00:00:03,000 --> 00:00:02,000\n역전', '1\n00:61:00,000 --> 00:61:01,000\n분 오류'):
            with self.assertRaises(ValueError):
                subtitles.parse(malformed.encode(), 10)

    def test_style_canonical_fields_survive_save_validation(self):
        style = validation.style({'title': {'weight': 'normal', 'outline_width': 5, 'outline_color': '#336699', 'background': '#445566', 'background_opacity': .6, 'letter_spacing': -2, 'size': 10, 'line_height': .6}, 'video': {'fit': 'cover'}, 'highlight': {'size': 71, 'color': '#123456'}})
        self.assertFalse(style['title']['bold'])
        self.assertEqual(style['title']['stroke'], 5)
        self.assertEqual(style['title']['bg_opacity'], .6)
        self.assertEqual(style['video']['fit'], 'cover')
        self.assertEqual(style['title']['letter_spacing'], -2)
        self.assertEqual(style['title']['line_height'], .6)
        self.assertEqual(media._font(style['title'],[]).size, 10)

    def test_untrusted_import_identifiers_and_asset_paths_rejected(self):
        for identifier in ('../../etc/passwd', '\" onfocus=alert(1)', '<img src=x>', 'x'*81):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    validation.clip(dict(id=identifier,start=0,end=2),10)
                with self.assertRaises(ValueError):
                    subtitles.validate([dict(id=identifier,start=0,end=2,text='인용 데이터')],10)
        safe=validation.style({'logo':{'image_path':'/etc/passwd','asset_id':None},'background_image_path':'/etc/passwd'})
        self.assertNotIn('image_path',safe['logo'])
        self.assertNotIn('background_image_path',safe)


class AIValidationTests(unittest.TestCase):
    def setUp(self):
        self.cues = [dict(id='a', start=0, end=2, text='분배율 3.07% 숫자는 그대로입니다.'), dict(id='b', start=2, end=4, text='과거 실적은 미래를 보장하지 않습니다.')]
        self.settings = dict(provider='remote', min_duration=1, max_duration=5, count=5, consent_external=True)
        self.candidate = dict(start=0, end=4, title='분배율 3.07%', summary='과거 실적은 미래를 보장하지 않습니다.', topic='테스트', reason='조건과 근거를 함께 담습니다.', evidence_ids=['a','b'], score=75, warnings=['검수 필요'])

    def test_invalid_provider_results_rejected(self):
        for change in ({'start': -1}, {'start': 3, 'end': 2}, {'end': 11}, {'start': .5}, {'evidence_ids': ['missing']}, {'title': '수익 9999%'}, {'score': float('nan')}):
            with self.subTest(change=change), self.assertRaises(ai.UserFacingError):
                ai.validate_candidates([{**self.candidate, **change}], self.cues, 10, self.settings)
        with self.assertRaises(ai.UserFacingError):
            ai.validate_candidates([self.candidate, self.candidate], self.cues, 10, self.settings)
        with self.assertRaises(ai.UserFacingError):
            ai.validate_candidates('not JSON', self.cues, 10, self.settings)

    def test_recommendation_cache_ignores_style_invalidates_transcript_and_model(self):
        payload = {'choices': [{'message': {'content': json.dumps({'candidates': [self.candidate]})}}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(ai, '_remote_json', return_value=payload) as provider:
            for styled in (self.cues, [{**c, 'style': {'color': '#ff00ff'}} for c in self.cues]):
                ai.recommend(styled, 10, Path(tmp), self.settings, lambda *a: None, threading.Event())
            self.assertEqual(provider.call_count, 1)
            changed = copy.deepcopy(self.cues)
            changed[1]['text'] += ' 원문 교정'
            ai.recommend(changed, 10, Path(tmp), self.settings, lambda *a: None, threading.Event())
            ai.recommend(changed, 10, Path(tmp), {**self.settings, 'chat_model':'test-model-changed'}, lambda *a: None, threading.Event())
            self.assertEqual(provider.call_count, 3)

    def test_no_external_request_without_consent_or_key(self):
        with patch.dict('os.environ', {'JOHNBER_API_KEY': ''}), patch.object(ai.http.client, 'HTTPSConnection') as connection:
            with self.assertRaises(ai.UserFacingError) as error:
                ai._remote_json('/chat/completions', b'{}', 'application/json', {}, threading.Event())
            self.assertEqual(error.exception.code, 'EXTERNAL_CONSENT_REQUIRED')
            with self.assertRaises(ai.UserFacingError) as error:
                ai._remote_json('/chat/completions', b'{}', 'application/json', self.settings, threading.Event())
            self.assertEqual(error.exception.code, 'API_KEY_MISSING')
            connection.assert_not_called()

    def test_provider_failures_redact_body_and_key(self):
        for status, expected in ((401, 'API_AUTH'), (429, 'API_RATE_LIMIT'), (500, 'API_HTTP_ERROR')):
            connection = MagicMock()
            response = connection.getresponse.return_value
            response.status = status
            response.read.return_value = b'private-provider-body api-key-fixture'
            with self.subTest(status=status), patch.dict('os.environ', {'JOHNBER_API_KEY': 'api-key-fixture'}), patch.object(ai.http.client, 'HTTPSConnection', return_value=connection):
                with self.assertRaises(ai.UserFacingError) as error:
                    ai._remote_json('/chat/completions', b'{}', 'application/json', self.settings, threading.Event())
                self.assertEqual(error.exception.code, expected)
                self.assertNotIn('private-provider-body', str(error.exception))
                self.assertNotIn('api-key-fixture', str(error.exception))
        with patch.dict('os.environ', {'JOHNBER_API_KEY': 'api-key-fixture'}), patch.object(ai.http.client, 'HTTPSConnection') as constructor:
            constructor.return_value.request.side_effect = OSError('private api-key-fixture')
            with self.assertRaises(ai.UserFacingError) as error:
                ai._remote_json('/chat/completions', b'{}', 'application/json', self.settings, threading.Event())
            self.assertEqual(error.exception.code, 'API_NETWORK')
            self.assertNotIn('api-key-fixture', str(error.exception))


if __name__ == '__main__':
    unittest.main()
