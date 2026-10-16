"""Offline AI contract checks. These mocks do NOT certify real ASR/provider quality.

Run: python -m unittest discover -s tests -p 'test_ai_adapters.py' -v
No external request, model download, credential, or user media is needed.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

from studio import ai


class CandidateValidationTests(unittest.TestCase):
    def setUp(self):
        self.cues = [dict(id=f"c{i}", start=i * 10.0, end=(i + 1) * 10.0,
                          text=f"문장 {i}입니다. 원본 조건을 확인하세요.") for i in range(12)]
        self.settings = dict(provider="remote", min_duration=30, max_duration=50,
                             count=5, consent_external=True)
        self.good = dict(start=0.0, end=40.0, title="원본 조건을 확인하세요", summary="문장 0입니다.",
                         topic="검수", reason="연속된 문장을 선택했습니다.",
                         evidence_ids=["c0", "c1", "c2", "c3"], score=70, warnings=[])
        self.progress = []
        self.callback = lambda value, message: self.progress.append((value, message))

    def test_valid_candidate_uses_real_evidence(self):
        result = ai.validate_candidates([self.good], self.cues, 120.0, self.settings)
        self.assertEqual(result[0]["end"], 40.0)
        self.assertEqual(result[0]["provider"], "remote")

    def test_invalid_results_rejected(self):
        bad_values = [dict(start=-1), dict(start=45.0, end=40.0), dict(end=121.0),
                      dict(start=0.1), dict(evidence_ids=["missing"]),
                      dict(evidence_ids=["c0", "c0", "c3"]), dict(evidence_ids=["c0", "c8"]),
                      dict(title="보장수익 99%"), dict(score=float("nan")),
                      dict(score=101), dict(start=True), dict(warnings="wrong")]
        for change in bad_values:
            with self.subTest(change=change), self.assertRaises(ai.UserFacingError) as caught:
                ai.validate_candidates([{**self.good, **change}], self.cues, 120.0, self.settings)
            self.assertEqual(caught.exception.code, "INVALID_AI_RESULT")
        for raw in ([self.good, self.good], "invalid", {"candidates": None}):
            with self.subTest(raw=raw), self.assertRaises(ai.UserFacingError):
                ai.validate_candidates(raw, self.cues, 120.0, self.settings)

    def test_empty_candidates_allowed_without_padding(self):
        self.assertEqual(ai.validate_candidates([], self.cues, 120.0, self.settings), [])

    def test_mock_remote_and_style_change_reuse_cache(self):
        response = {"choices": [{"message": {"content": json.dumps({"candidates": [self.good]})}}]}
        with tempfile.TemporaryDirectory() as folder:
            args = (self.cues, 120.0, Path(folder), self.settings, self.callback, threading.Event())
            with patch.object(ai, "_remote_json", return_value=response) as remote:
                first = ai.recommend(*args)
                self.assertEqual(remote.call_count, 1)
            with patch.object(ai, "_remote_json", side_effect=AssertionError("cache repeated provider request")):
                self.assertEqual(ai.recommend(*args), first)
                styled = [{**cue, "highlight": "강조색"} for cue in self.cues]
                self.assertEqual(ai.recommend(styled, *args[1:]), first)
            modified = [dict(cue) for cue in self.cues]
            modified[0]["text"] = "수정한 문장입니다."
            with patch.object(ai, "_remote_json", return_value={"choices": [{"message": {"content": "invalid"}}]}) as remote:
                with self.assertRaises(ai.UserFacingError) as caught:
                    ai.recommend(modified, *args[1:])
                self.assertEqual(caught.exception.code, "INVALID_AI_RESULT")
                self.assertEqual(remote.call_count, 1)

    def test_rules_are_deterministic_explicit_and_offline(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(ai, "_remote_json", side_effect=AssertionError("rules used network")):
            result = ai.recommend(self.cues, 120.0, Path(folder), {**self.settings, "provider": "rules"}, self.callback, threading.Event())
            self.assertTrue(result)
            self.assertTrue(all(candidate["provider"] == "rules" for candidate in result))
            self.assertEqual(result, ai.recommend(self.cues, 120.0, Path(folder), {**self.settings, "provider": "rules"}, self.callback, threading.Event()))

    def test_cancellation_honored_before_request(self):
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ai.CancelledError):
            ai.recommend(self.cues, 120.0, Path(folder), self.settings, self.callback, cancel)

    def test_status_hides_secrets_and_external_consent_required(self):
        with patch.dict(os.environ, {"JOHNBER_API_KEY": "TOP_SECRET_TEST_KEY"}):
            state = ai.status()
            self.assertTrue(state["remote_key"])
            self.assertNotIn("TOP_SECRET_TEST_KEY", json.dumps(state))
            with patch.object(ai.http.client, "HTTPSConnection", side_effect=AssertionError("network attempted")):
                with self.assertRaises(ai.UserFacingError) as caught:
                    ai._remote_json("/chat/completions", b"{}", "application/json", {}, threading.Event())
                self.assertEqual(caught.exception.code, "EXTERNAL_CONSENT_REQUIRED")

    def test_http_auth_error_is_safe_and_not_replaced_by_results(self):
        class Connection:
            def __init__(self, *args, **kwargs):
                self.sock = None
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return types.SimpleNamespace(status=401, read=lambda maximum: b'{"error":"secret server details"}')
            def close(self):
                pass
        with patch.dict(os.environ, {"JOHNBER_API_KEY": "TOP_SECRET_TEST_KEY"}), patch.object(ai.http.client, "HTTPSConnection", Connection), patch.object(ai, "getproxies", return_value={}):
            with self.assertRaises(ai.UserFacingError) as caught:
                ai._remote_json("/chat/completions", b"{}", "application/json", self.settings, threading.Event())
            self.assertEqual(caught.exception.code, "API_AUTH")
            self.assertNotIn("TOP_SECRET_TEST_KEY", str(caught.exception))
            self.assertNotIn("secret server details", str(caught.exception))

    def test_standard_https_proxy_uses_tls_connect_and_hides_proxy_auth(self):
        calls = {}
        class Connection:
            def __init__(self, host, port=None, timeout=None, context=None):
                calls["host"] = host
                calls["port"] = port
                calls["context"] = context
            def set_tunnel(self, host, port=None, headers=None):
                calls["tunnel"] = (host, port, headers)
        with patch.object(ai, "getproxies", return_value={"https": "http://user:proxy-secret@proxy.example:8080"}), patch.object(ai, "proxy_bypass", return_value=False), patch.object(ai.http.client, "HTTPSConnection", Connection):
            connection, target, headers = ai._connection("https", "api.openai.com", None, "/v1/chat/completions")
        self.assertEqual(calls["host"], "proxy.example")
        self.assertEqual(calls["port"], 8080)
        self.assertEqual(calls["tunnel"][:2], ("api.openai.com", 443))
        self.assertIn("Proxy-Authorization", calls["tunnel"][2])
        self.assertTrue(calls["context"].check_hostname)
        self.assertEqual(calls["context"].verify_mode, ai.ssl.CERT_REQUIRED)
        self.assertEqual(headers, {})  # proxy secret stays out of origin headers
        self.assertEqual(target, "/v1/chat/completions")

    def test_no_proxy_bypasses_proxy_for_local_provider(self):
        calls = {}
        class Connection:
            def __init__(self, host, port=None, timeout=None):
                calls["host"] = host
        with patch.object(ai, "getproxies", return_value={"http": "http://proxy.example:8080"}), patch.object(ai, "proxy_bypass", return_value=True), patch.object(ai.http.client, "HTTPConnection", Connection):
            ai._connection("http", "127.0.0.1", 1234, "/v1/chat/completions")
        self.assertEqual(calls["host"], "127.0.0.1")

    def test_api_base_only_server_env_and_tls_preserved(self):
        with patch.dict(os.environ, {"JOHNBER_API_BASE": "http://untrusted.example/v1"}):
            with self.assertRaises(ai.UserFacingError) as caught:
                ai._remote_url("/chat/completions")
            self.assertEqual(caught.exception.code, "API_BASE_INVALID")
        with patch.dict(os.environ, {"JOHNBER_API_BASE": "https://user:secret@example.com/v1"}):
            with self.assertRaises(ai.UserFacingError):
                ai._remote_url("/chat/completions")


@unittest.skipUnless(shutil.which("ffmpeg"), "real extraction test needs FFmpeg")
class AudioAdapterTests(unittest.TestCase):
    """Actual audio extraction + mocked STT only; this is NOT Korean ASR evidence."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / "한글 원본.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-y", str(self.source)], check=True, timeout=30)
        self.callback = lambda value, message: None

    def test_remote_adapter_transmits_only_wav_and_caches(self):
        def fake_stt(endpoint, body, content_type, settings, cancel):
            self.assertEqual(endpoint, "/audio/transcriptions")
            self.assertIn(b'filename="audio.wav"', body)
            self.assertIn(b"RIFF", body)
            self.assertNotIn(b"ftyp", body)
            return {"segments": [{"start": 0.0, "end": 1.9, "text": "정상 전사 테스트입니다."}]}
        with patch.dict(os.environ, {"JOHNBER_API_KEY": "mock-key"}):
            with patch.object(ai, "_remote_json", side_effect=fake_stt) as remote:
                first = ai.transcribe(self.source, self.folder / "cache", {"provider": "remote", "consent_external": True}, self.callback, threading.Event())
                self.assertEqual(remote.call_count, 1)
                self.assertEqual(first[0]["end"], 1.9)
            with patch.object(ai, "_remote_json", side_effect=AssertionError("STT cache repeated request")):
                self.assertEqual(first, ai.transcribe(self.source, self.folder / "cache", {"provider": "remote"}, self.callback, threading.Event()))

    def test_local_adapter_disables_download_and_only_prompts_dictionary(self):
        seen = {}
        class Engine:
            def __init__(self, *args, **kwargs):
                seen["load"] = kwargs
            def transcribe(self, *args, **kwargs):
                seen["transcribe"] = kwargs
                return iter([types.SimpleNamespace(start=0.0, end=1.9, text="로컬 모델 모의 전사입니다.")]), None
        fake = types.ModuleType("faster_whisper")
        fake.WhisperModel = Engine
        with patch.dict("sys.modules", {"faster_whisper": fake}), patch.object(ai.importlib.util, "find_spec", return_value=True):
            result = ai.transcribe(self.source, self.folder / "cache", {"provider": "local", "dictionary": ["SOXL", "SCHD"]}, self.callback, threading.Event())
        self.assertIs(seen["load"]["local_files_only"], True)
        self.assertEqual(seen["transcribe"]["initial_prompt"], "SOXL, SCHD")
        self.assertEqual(result[0]["text"], "로컬 모델 모의 전사입니다.")


if __name__ == "__main__":
    unittest.main()
