"""A01·A02·A05·A07·A08·A11: 실제 영상 + SRT + 수동 구간 → MP4."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

from av_analysis import audio_onsets, flash_onsets, frame_rgb
from conftest import wait_job

EVIDENCE = Path(__file__).resolve().parent.parent / "docs" / "evidence"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _project(client, media_dir, name="sync test"):
    r = client.post("/api/projects/from-path", json={"path": str(media_dir / f"{name}.mp4"), "title": f"검수 {name}"})
    assert r.status_code == 200, r.text
    return r.json()


def test_a01_probe_and_errors(client, media_dir):
    p = _project(client, media_dir, "강의 샘플")
    src = p["source"]
    assert src["duration_ms"] == 90000 and src["width"] == 1920 and src["height"] == 1080 and src["has_audio"] == 1
    assert abs(src["fps"] - 30) < 0.01
    # 이름만 MP4 / 손상 파일 → 한국어 오류
    for bad in ("가짜.mp4", "손상.mp4"):
        r = client.post("/api/projects/from-path", json={"path": str(media_dir / bad)})
        assert r.status_code == 400
        err = r.json()["error"]
        assert err["code"] == "MEDIA_INVALID" and "영상 파일을 읽을 수 없습니다" in err["message"]
    # 업로드 경로(복사 보관)도 동작
    with open(media_dir / "sync test.mp4", "rb") as f:
        r = client.post("/api/projects/upload", files={"file": ("업로드 테스트.mp4", f, "video/mp4")}, data={"title": ""})
    assert r.status_code == 200, r.text
    assert r.json()["source"]["owned"] == 1 and r.json()["title"] == "업로드 테스트"


def test_a02_no_api_key_manual_path(client, media_dir):
    st = client.get("/api/status").json()
    assert st["ai"]["connected"] is False and "미연결" in st["ai"]["label"]
    p = _project(client, media_dir, "강의 샘플")
    pid = p["id"]
    srt = (media_dir / "강의 샘플.srt").read_bytes()
    r = client.post(f"/api/projects/{pid}/subtitles", files={"file": ("x.srt", srt)})
    assert r.status_code == 200 and len(r.json()["transcript"]["cues"]) == 29
    # AI 추천은 비활성: 가짜 결과 없이 명확한 오류
    r = client.post(f"/api/projects/{pid}/recommend", json={})
    assert r.status_code == 400 and r.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    assert client.get(f"/api/projects/{pid}/recommendations").json() == []
    est = client.get(f"/api/projects/{pid}/recommend/estimate").json()
    assert est["status"]["connected"] is False and est["input_tokens"] is None
    clip = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 21000, "title": "수동 구간 테스트"}).json()
    j = client.post(f"/api/clips/{clip['id']}/render", json={}).json()
    j = wait_job(client, j["id"])
    assert j["status"] == "succeeded", j
    art = client.get(f"/api/artifacts?project_id={pid}").json()[0]
    assert art["probe"]["width"] == 1080 and art["probe"]["height"] == 1920 and art["probe"]["vcodec"] == "h264"
    assert art["probe"]["acodec"] == "aac" and art["probe"]["pix_fmt"] == "yuv420p" and abs(art["probe"]["fps"] - 30) < 0.01
    assert abs(art["duration_ms"] - 18000) <= 40
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "a02_ffprobe.json").write_text(json.dumps(art["probe"], ensure_ascii=False, indent=1), encoding="utf-8")


def _setup_sync_clip(client, media_dir):
    p = _project(client, media_dir)
    pid = p["id"]
    srt = "1\n00:00:00,500 --> 00:00:02,000\n시작 자막\n\n2\n00:00:06,500 --> 00:00:08,000\n삭제 뒤 자막\n\n3\n00:00:08,500 --> 00:00:09,800\n끝 자막\n"
    client.post(f"/api/projects/{pid}/subtitles", files={"file": ("s.srt", srt.encode())})
    clip = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 0, "end_ms": 10000, "title": "동기화 검사"}).json()
    return pid, clip


def test_a08_silence_speed_sync(client, media_dir):
    src = media_dir / "sync test.mp4"
    before = sha(src)
    pid, clip = _setup_sync_clip(client, media_dir)
    # 무음 감지(제안 모드): 4~6초 무음을 찾아야 함
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/silence", json={"noise_db": -40, "min_ms": 700, "keep_ms": 0}).json()["id"])
    assert j["status"] == "succeeded", j
    sug = j["result"]["suggestions"]
    assert len(sug) == 1 and abs(sug[0]["start_ms"] - 4000) <= 60 and abs(sug[0]["end_ms"] - 6000) <= 60, sug
    data = copy.deepcopy(clip["data"])
    # 결정적 기대값을 위해 정확히 4.000~6.000초를 삭제(감지 결과와의 차이는 위에서 검증)
    data["cuts"] = [{"start_ms": 4000, "end_ms": 6000, "reason": "silence", "enabled": True}]
    data["speed"] = 1.25
    clip = client.put(f"/api/clips/{clip['id']}", json={"data": data, "label": "무음 제거+1.25배"}).json()
    assert abs(clip["summary"]["output_ms"] - 6400) < 1
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/render", json={}).json()["id"])
    assert j["status"] == "succeeded", j
    art = next(a for a in client.get(f"/api/artifacts?project_id={pid}").json() if a["id"] == j["result"]["artifact_id"])
    out = Path(art["path"])
    measured_dur = art["probe"]["duration_ms"]
    assert abs(measured_dur - 6400) <= 50, measured_dur
    expected = [0.8, 2.4, 4.0, 5.6]  # 원본 1,3,7,9초 → (t - 삭제분)/1.25
    a_on = audio_onsets(out)
    # 영상 섬광 영역: 원본 (760..1160, 380..700) → 캔버스 x=0.5625배, y=616+0.5625배
    v_on = flash_onsets(out, 450, 860, 160, 120)
    assert len(a_on) == 4 and len(v_on) == 4, (a_on, v_on)
    a_err = [round((a - e) * 1000, 1) for a, e in zip(a_on, expected)]
    v_err = [round((v - e) * 1000, 1) for v, e in zip(v_on, expected)]
    assert all(abs(x) <= 100 for x in a_err + v_err), (a_err, v_err)
    # 자막 매핑: 원본 6.5~8.0 → (4.5..6.0)/1.25 = 3.6..4.8
    cue_map = {c["lines"][0]: (c["start"], c["end"]) for c in art["meta"]["cue_overlays"]}
    assert abs(cue_map["삭제 뒤 자막"][0] - 3.6) < 0.001 and abs(cue_map["삭제 뒤 자막"][1] - 4.8) < 0.002
    assert sha(src) == before  # 원본 보존
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "a08_sync.json").write_text(json.dumps({
        "expected_duration_ms": 6400, "measured_duration_ms": measured_dur, "expected_events_s": expected,
        "audio_onsets_s": a_on, "video_flash_onsets_s": v_on, "audio_error_ms": a_err, "video_error_ms": v_err,
        "cue_map_s": cue_map, "frame_grid_ms": 1000 / 30,
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def test_a07_delete_speech_and_undo(client, media_dir):
    src = media_dir / "sync test.mp4"
    before = sha(src)
    pid, clip = _setup_sync_clip(client, media_dir)
    cue = next(c for c in clip["data"]["cues"] if c["text"] == "삭제 뒤 자막")
    # 텍스트만 교정 → 영상 길이 변화 없음
    data = copy.deepcopy(clip["data"])
    next(c for c in data["cues"] if c["id"] == cue["id"])["text"] = ""
    edited = client.put(f"/api/clips/{clip['id']}", json={"data": data, "label": "자막 글자 지우기"}).json()
    assert edited["summary"]["output_ms"] == clip["summary"]["output_ms"] and edited["data"]["cuts"] == []
    client.post(f"/api/clips/{clip['id']}/undo")
    # 발화 구간 삭제 → EDL에 반영, 길이 1.5초 감소
    deleted = client.post(f"/api/clips/{clip['id']}/cues/{cue['id']}/delete-speech", json={}).json()
    assert len(deleted["data"]["cuts"]) == 1 and deleted["data"]["cuts"][0]["reason"] == "cue"
    assert abs(deleted["summary"]["output_ms"] - (10000 - 1500)) < 20
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/render", json={}).json()["id"])
    assert j["status"] == "succeeded", j
    art = next(a for a in client.get(f"/api/artifacts?project_id={pid}").json() if a["id"] == j["result"]["artifact_id"])
    assert abs(art["duration_ms"] - 8500) <= 50
    lines = [c["lines"][0] for c in art["meta"]["cue_overlays"]]
    assert "삭제 뒤 자막" not in lines and "끝 자막" in lines
    # 원본 7초 비프 → 6.5~8.0 삭제 후 사라져야 하고 9초 비프는 7.5초로 이동
    on = audio_onsets(Path(art["path"]))
    assert len(on) == 3 and abs(on[-1] - 7.5) <= 0.1, on
    restored = client.post(f"/api/clips/{clip['id']}/undo").json()
    assert restored["data"]["cuts"] == [] and abs(restored["summary"]["output_ms"] - 10000) < 1
    redo = client.post(f"/api/clips/{clip['id']}/redo").json()
    assert len(redo["data"]["cuts"]) == 1
    assert sha(src) == before


def test_a05_edge_markers_visible(client, media_dir):
    pid, clip = _setup_sync_clip(client, media_dir)
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/render", json={}).json()["id"])
    art = next(a for a in client.get(f"/api/artifacts?project_id={pid}").json() if a["id"] == j["result"]["artifact_id"])
    img = frame_rgb(Path(art["path"]), 2.0)
    vr = art["meta"]["video_rect"]
    assert (vr["x"], vr["w"]) == (0, 1080) and vr["h"] == 608  # 16:9 전체 보존(찌그러짐 없음: 1080/608 ≈ 1920/1080)
    s = 1080 / 1920
    probes = {"red": (30, 30, (255, 0, 0)), "lime": (1890, 30, (0, 255, 0)), "blue": (30, 1050, (0, 0, 255)), "yellow": (1890, 1050, (255, 255, 0))}
    for name, (sx, sy, rgb) in probes.items():
        px = img[int(vr["y"] + sy * s), int(vr["x"] + sx * s)].astype(int)
        assert np.abs(px - np.array(rgb)).max() < 60, (name, px)
    from PIL import Image

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).resize((540, 960)).save(EVIDENCE / "a05_edge_markers_frame.png")


def test_a11_silent_input_marked(client, media_dir):
    r = client.post("/api/projects/from-path", json={"path": str(media_dir / "무음 입력.mp4")})
    p = r.json()
    assert p["source"]["has_audio"] == 0
    clip = client.post(f"/api/projects/{p['id']}/clips", json={"start_ms": 0, "end_ms": 5000, "title": "무음"}).json()
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/render", json={}).json()["id"])
    assert j["status"] == "succeeded", j
    art = client.get(f"/api/artifacts?project_id={p['id']}").json()[0]
    assert art["probe"]["audio_kind"] == "silent" and art["probe"]["has_audio"]
