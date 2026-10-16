import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from clipora_shorts import captions, cli, highlights, render, templates  # noqa: E402
from clipora_shorts.media import VideoInfo  # noqa: E402


def make_segments():
    texts = [
        "안녕하세요 오늘 강의 시작합니다", "결국 매일 꾸준히 하는 사람이 이깁니다", "하루 열 시간 몰아서 하는 건 오래 못 가요",
        "첫 번째는 시작 시간을 고정하는 겁니다", "두 번째는 기록이에요", "숫자가 쌓이면 그만두기 아까워집니다",
        "슬럼프가 오면 양을 절반으로 줄이세요", "멈추는 것보다 줄이는 게 낫거든요", "감사합니다",
    ]
    segs, t = [], 0.5
    for i, text in enumerate(texts):
        words = text.split()
        dur = 4.0
        step = dur / len(words)
        segs.append({
            "id": i, "start": t, "end": t + dur, "text": text,
            "words": [{"start": t + k * step, "end": t + (k + 0.9) * step, "word": w} for k, w in enumerate(words)],
        })
        t += dur + (1.5 if i in (0, 5) else 0.4)
    return segs


def test_parse_time_and_safe_name():
    assert cli.parse_time("90") == 90
    assert cli.parse_time("1:30") == 90
    assert cli.parse_time("1:02:03") == 3723
    with pytest.raises(Exception):
        cli.parse_time("1:xx")
    assert cli.safe_name('a/b:c*d?"e<f>g|') == "abcdefg"
    assert cli.safe_name("   ") == "short"


def test_caption_chunks_are_short_relative_and_cover_clip():
    segs = make_segments()
    chunks = captions.caption_chunks(segs, start=5.0, end=20.0, max_chars=12)
    assert chunks and chunks[0]["start"] >= 0 and chunks[-1]["end"] <= 15.0
    assert all(len(c["text"]) <= 12 or " " not in c["text"] for c in chunks)
    assert all(a["end"] <= b["start"] + 1e-6 for a, b in zip(chunks, chunks[1:]))


def test_caption_chunks_without_word_timestamps():
    segs = [{"id": 0, "start": 0.0, "end": 6.0, "text": "단어 타임스탬프가 없는 문장도 자막으로 나눠야 합니다", "words": []}]
    chunks = captions.caption_chunks(segs, 0.0, 6.0, max_chars=10)
    assert len(chunks) >= 3
    assert abs(chunks[-1]["end"] - 6.0) < 0.01


def test_srt_and_ass_output():
    chunks = [{"start": 0.0, "end": 1.5, "text": "중요한 {핵심} 문장"}, {"start": 61.25, "end": 62.0, "text": "끝"}]
    srt = captions.to_srt(chunks)
    assert "00:01:01,250 --> 00:01:02,000" in srt
    ass = captions.to_ass(chunks, "제목 {테스트}", 62.0, templates.get("blur"), "Noto Sans CJK KR")
    assert "Style: Title,Noto Sans CJK KR" in ass and "Dialogue: 1,0:00:00.00,0:01:02.00,Title" in ass
    assert "{테스트}" not in ass  # 중괄호는 ASS 태그로 해석되지 않게 치환
    assert "{\\c" in ass  # blur 템플릿은 핵심어 강조
    no_title = captions.to_ass(chunks, "제목", 62.0, templates.get("minimal"), "X")
    assert "Title" not in no_title.split("[Events]")[1]


def test_finalize_trims_drops_and_deduplicates():
    segs = make_segments()
    cands = [
        {"ids": (1, 3), "score": 90, "title": "꾸준함"},
        {"ids": (2, 4), "score": 80, "title": "겹침"},      # 1번과 겹침 → 제외
        {"ids": (5, 7), "score": 70, "title": ""},          # 제목 없으면 자막에서 생성
        {"ids": (0, 8), "score": 60, "title": "너무 김"},   # max 안으로 잘림 (겹치면 제외)
    ]
    clips = highlights.finalize(cands, segs, count=5, min_len=8, max_len=14)
    assert [c.title for c in clips][:1] == ["꾸준함"]
    assert all(c.duration <= 14 * 1.15 + 0.5 for c in clips)
    assert all(not (a.start < b.end and a.end > b.start) for i, a in enumerate(clips) for b in clips[i + 1:])
    assert clips[1].title  # 자동 제목


def test_heuristic_respects_bounds():
    segs = make_segments()
    clips = highlights.pick_heuristic(segs, count=3, min_len=8, max_len=15)
    assert 1 <= len(clips) <= 3
    for c in clips:
        assert 8 * 0.5 <= c.duration <= 15 * 1.15 + 0.5
        assert c.title


class FakeStream:
    def __init__(self, response, captured, kwargs):
        self.response, captured["kwargs"] = response, kwargs

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.response


def fake_anthropic(monkeypatch, response, captured):
    import anthropic

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        stream=lambda **kw: FakeStream(response, captured, kw))))
    monkeypatch.setattr(anthropic, "Anthropic", lambda: client)


def test_claude_pick_uses_structured_output_and_validates(monkeypatch):
    segs = make_segments()
    answer = {"clips": [
        {"start_id": 1, "end_id": 3, "title": "꾸준함이 이깁니다", "hook": "h", "reason": "r", "score": 91, "hashtags": ["#공부", "습관"]},
        {"start_id": 7, "end_id": 6, "title": "순서 뒤바뀜", "hook": "", "reason": "", "score": 70, "hashtags": []},
        {"start_id": 42, "end_id": 43, "title": "없는 번호", "hook": "", "reason": "", "score": 99, "hashtags": []},
    ]}
    captured = {}
    fake_anthropic(monkeypatch, SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(answer))]), captured)
    clips = highlights.pick_with_claude(segs, 3, 8, 15, persona="수험생 채널")
    assert [c.title for c in clips] == ["꾸준함이 이깁니다", "순서 뒤바뀜"]
    assert clips[0].hashtags == ["공부", "습관"]
    kw = captured["kwargs"]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert "수험생 채널" in kw["messages"][0]["content"] and "[1] 00:" in kw["messages"][0]["content"]


def test_refusal_falls_back_to_heuristic(monkeypatch):
    captured = {}
    fake_anthropic(monkeypatch, SimpleNamespace(stop_reason="refusal", content=[]), captured)
    logs = []
    clips, method = highlights.pick(make_segments(), 2, 8, 15, use_ai=True, log=logs.append)
    assert method == "heuristic" and clips and "거절" in logs[0]


def test_filter_crops_around_face_and_handles_vertical_sources():
    wide = VideoInfo(duration=60, width=1920, height=1080, has_audio=True)
    g = render.build_filter(wide, templates.get("talk"), face_x=0.8, ass_name="01.ass", fontsdir=None)
    # 1920x1080 → 높이 1920에 맞추면 폭 3414, 얼굴 중심 0.8 → x = 0.8*3414 - 540
    assert "scale=3414:1920,crop=1080:1920:2191:0" in g and g.endswith("ass=01.ass,format=yuv420p[v]")
    g = render.build_filter(wide, templates.get("talk"), face_x=0.99, ass_name="a.ass", fontsdir=None)
    assert "crop=1080:1920:2334:0" in g  # 오른쪽 끝을 넘지 않음
    fit = render.build_filter(wide, templates.get("blur"), None, "a.ass", "C:\\Fonts")
    assert "boxblur" in fit and "overlay=0:" in fit and "fontsdir='C\\:/Fonts'" in fit
    tall = VideoInfo(duration=60, width=1080, height=1920, has_audio=True)
    assert "crop=1080:1920:0:0" in render.build_filter(tall, templates.get("clean"), None, "a.ass", None)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 필요")
def test_end_to_end_vertical_video(tmp_path):
    video = tmp_path / "phone.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=720x1280:r=30:d=40",
                    "-f", "lavfi", "-i", "sine=f=300:d=40", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                    "-c:a", "aac", str(video)], check=True)
    tr = tmp_path / "t.json"
    tr.write_text(json.dumps({"language": "ko", "segments": make_segments()}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    code = cli.main([str(video), "--transcript", str(tr), "--no-ai", "--min", "8", "--max", "15",
                     "-t", "clean", "-o", str(out), "--quality", "fast", "--reframe", "center"])
    assert code == 0
    mp4s = sorted(out.glob("*.mp4"))
    assert mp4s and (out / "clips.json").exists() and (out / "업로드정보.md").exists()
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                            "-of", "csv=p=0", str(mp4s[0])], capture_output=True, text=True)
    assert probe.stdout.strip() == "1080,1920"
    plan = json.loads((out / "clips.json").read_text(encoding="utf-8"))
    assert plan["method"] == "heuristic" and plan["clips"][0]["captions"]
