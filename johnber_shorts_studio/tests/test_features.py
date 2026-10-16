"""A03(오류 경로)·A04(검증)·A06·A10·A12·A13·A14·A15."""
from __future__ import annotations

import copy
import json
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from conftest import wait_job

EVIDENCE = Path(__file__).resolve().parent.parent / "docs" / "evidence"


def _project_with_srt(client, media_dir, title="기능 검수"):
    p = client.post("/api/projects/from-path", json={"path": str(media_dir / "강의 샘플.mp4"), "title": title}).json()
    client.post(f"/api/projects/{p['id']}/subtitles", files={"file": ("a.srt", (media_dir / "강의 샘플.srt").read_bytes())})
    return p["id"]


# ------------------------------------------------------------------ A04: AI 응답 검증

def _cues(n=30, step=3000):
    return [{"id": f"c{i}", "start_ms": 500 + i * step, "end_ms": 500 + i * step + 2700, "text": f"문장 {i} 입니다. 수익률 3.07%"} for i in range(n)]


def test_a04_validation_rejects_bad_candidates():
    from app import recommend
    from app.errors import StudioError

    cues = _cues()
    cues[12]["text"] = "하지만 위험도 큽니다."
    settings = {"min_s": 30, "max_s": 60, "count": 8}
    base = {"titles": ["좋은 제목"], "summary": "", "topic": "", "reason": "", "score": 80, "cautions": []}
    raw = {"candidates": [
        {**base, "start_index": 0, "end_index": 11, "titles": ["3.07% 이야기", "연 30% 보장"]},   # 채택(조작 수치 제목 제외)
        {**base, "start_index": -1, "end_index": 5},     # 음수
        {**base, "start_index": 20, "end_index": 15},    # 역전
        {**base, "start_index": 25, "end_index": 99},    # 범위 초과
        {**base, "start_index": 1, "end_index": 12},     # 1번과 과도한 중복
        {**base, "start_index": 14, "end_index": 15},    # 너무 짧음
        {**base, "start_index": 14, "end_index": 26},    # 채택
    ]}
    acc, rej = recommend.validate_candidates(json.dumps(raw), cues, 95_000, settings)
    assert [ (a["start_cue_id"], a["end_cue_id"]) for a in acc] == [("c0", "c11"), ("c14", "c26")]
    reasons = [r["reason"] for r in rej]
    assert any("음수" in r for r in reasons) and any("역전" in r for r in reasons)
    assert any("범위 초과" in r for r in reasons) and any("중복" in r for r in reasons) and any("요청 범위 밖" in r for r in reasons)
    assert acc[0]["titles"] == ["3.07% 이야기"]  # '연 30% 보장'은 원문에 없는 수치 → 제외
    assert any("원문에 없는 수치" in c for c in acc[0]["cautions"])
    assert any("단서·반론" in c for c in acc[0]["cautions"])  # 바로 뒤 '하지만'
    assert acc[0]["score_note"].startswith("모델의 편집적 평가")
    with pytest.raises(StudioError) as e:
        recommend.validate_candidates("{not json", cues, 95_000, settings)
    assert e.value.code == "AI_BAD_RESPONSE"
    with pytest.raises(StudioError):
        recommend.validate_candidates({"items": []}, cues, 95_000, settings)
    # 원본 길이 초과(자막 시각이 영상보다 긴 경우)
    acc2, rej2 = recommend.validate_candidates(raw, cues, 40_000, settings)
    assert all(a["end_ms"] <= 40_500 for a in acc2) and any("원본 길이 초과" in r["reason"] for r in rej2)


def test_rule_candidates_are_labeled_not_ai(client, media_dir):
    pid = _project_with_srt(client, media_dir, "규칙 후보")
    r = client.post(f"/api/projects/{pid}/rule-candidates", json={"settings": {"min_s": 15, "max_s": 30, "count": 5}}).json()
    recs = client.get(f"/api/projects/{pid}/recommendations").json()
    assert recs[0]["provider"] == "rule" and recs[0]["model"] is None and r["count"] >= 1
    for c in recs[0]["candidates"]:
        assert c["score"] is None and "AI 판단 아님" in c["reason"] and 15000 <= c["duration_ms"] <= 30000


# ------------------------------------------------------------------ A06·A10: 스타일·템플릿 버전

def test_a06_style_roundtrip_and_overflow_warning(client, media_dir):
    pid = _project_with_srt(client, media_dir, "스타일")
    clip = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 9000, "title": "스타일"}).json()
    d = copy.deepcopy(clip["data"])
    st = d["style"]
    st["subtitle"].update({"size": 70, "color": "#00FFAA", "bg": {**st["subtitle"]["bg"], "enabled": True, "color": "#112233", "opacity": 0.8}})
    st["subtitle"]["box"]["y"] = 1400
    st["emphasis"].update({"color": "#FF3355", "scale": 1.2})
    d["cues"][0]["text"] = "SOXL · TQQQ · SCHD / 3.07% / 0.1%p / 1,000,000원 / 길이가 긴 한글 테스트 문장 " * 3
    d["cues"][0]["emphasis"] = [[0, 4]]
    d["cues"][1]["text"] = "첫 줄\n둘째 줄"
    client.put(f"/api/clips/{clip['id']}", json={"data": d})
    again = client.get(f"/api/clips/{clip['id']}").json()  # 새로 읽기(새로고침/재실행과 같은 경로)
    s2 = again["data"]["style"]
    assert s2["subtitle"]["size"] == 70 and s2["subtitle"]["color"] == "#00FFAA" and s2["subtitle"]["bg"]["enabled"]
    assert s2["subtitle"]["box"]["y"] == 1400 and s2["emphasis"]["color"] == "#FF3355"
    sc = client.post(f"/api/clips/{clip['id']}/scene", json={}).json()
    long_cue = next(c for c in sc["cues"] if c["id"] == d["cues"][0]["id"])
    assert any(w["code"] in ("too_many_lines", "auto_shrink") for w in long_cue["warnings"])
    manual = next(c for c in sc["cues"] if c["id"] == d["cues"][1]["id"])
    assert manual["lines"] == ["첫 줄", "둘째 줄"]
    assert again["data"]["cuts"] == []  # 자막 교정이 영상 삭제로 이어지지 않음


def test_a10_template_versions(client, media_dir):
    pid = _project_with_srt(client, media_dir, "템플릿 버전")
    base = client.get("/api/templates/tpl_builtin_dark").json()
    tpl = client.post("/api/templates", json={"name": "템플릿 A", "data": base["data"]}).json()
    c1 = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 9000, "title": "클립1", "template_id": tpl["id"]}).json()
    d = copy.deepcopy(c1["data"])
    d["style"]["subtitle"]["size"] = 77  # 사용자 수정
    c1 = client.put(f"/api/clips/{c1['id']}", json={"data": d}).json()
    assert c1["modified_keys"] == ["subtitle.size"]
    new_data = copy.deepcopy(tpl["data"])
    new_data["title"]["color"] = "#FF0000"
    tpl2 = client.put(f"/api/templates/{tpl['id']}", json={"data": new_data}).json()
    assert tpl2["current_version"] == 2
    c1_now = client.get(f"/api/clips/{c1['id']}").json()
    assert c1_now["data"]["style"]["title"]["color"] == "#FFFFFF" and c1_now["data"]["template"]["version"] == 1
    assert c1_now["template_latest_version"] == 2
    c2 = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 9000, "end_ms": 15000, "title": "클립2", "template_id": tpl["id"]}).json()
    assert c2["data"]["template"]["version"] == 2 and c2["data"]["style"]["title"]["color"] == "#FF0000"
    kept = client.post(f"/api/clips/{c1['id']}/apply-template", json={"template_id": tpl["id"], "mode": "keep"}).json()
    assert kept["data"]["style"]["subtitle"]["size"] == 77 and kept["data"]["style"]["title"]["color"] == "#FF0000"
    assert kept["kept_keys"] == ["subtitle.size"]
    over = client.post(f"/api/clips/{c1['id']}/apply-template", json={"template_id": tpl["id"], "mode": "overwrite"}).json()
    assert over["data"]["style"]["subtitle"]["size"] == base["data"]["subtitle"]["size"]
    undone = client.post(f"/api/clips/{c1['id']}/undo").json()
    assert undone["data"]["style"]["subtitle"]["size"] == 77
    # 기본 템플릿은 직접 수정 불가(복제 후 수정)
    assert client.put("/api/templates/tpl_builtin_dark", json={"data": base["data"]}).status_code == 400
    old = client.get(f"/api/templates/{tpl['id']}?v=1").json()
    assert old["data"]["title"]["color"] == "#FFFFFF"


# ------------------------------------------------------------------ A12: 개별·일괄 내보내기

def test_a12_batch_export_zip(client, media_dir):
    pid = _project_with_srt(client, media_dir, "일괄:내보내기?")
    titles = ["같은 제목", "같은 제목", 'A:B/C*D?"<>| 금지문자', "아주 긴 제목 " * 20]
    ids = [client.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000 + i * 6000, "end_ms": 8000 + i * 6000, "title": t}).json()["id"]
           for i, t in enumerate(titles)]
    r1 = client.post(f"/api/projects/{pid}/batch-export", json={"clip_ids": ids, "zip": True}).json()
    r2 = client.post(f"/api/projects/{pid}/batch-export", json={"clip_ids": ids, "zip": True}).json()  # 중복 클릭
    assert [j["id"] for j in r1["render_jobs"]] == [j["id"] for j in r2["render_jobs"]]
    assert r1["zip_job"]["id"] == r2["zip_job"]["id"]
    zj = wait_job(client, r1["zip_job"]["id"], 600)
    assert zj["status"] == "succeeded", zj
    art = next(a for a in client.get(f"/api/artifacts?project_id={pid}&kind=zip").json() if a["id"] == zj["result"]["artifact_id"])
    with zipfile.ZipFile(art["path"]) as zf:
        names = zf.namelist()
        mp4s = [n for n in names if n.endswith(".mp4")]
        assert len(mp4s) == 4 and len(set(mp4s)) == 4
        for n in mp4s:
            assert not any(ch in n for ch in '<>:"/\\|?*') and len(n) < 200
        out_dir = Path(art["path"]).parent / "unzipped"
        zf.extractall(out_dir)
    for n in mp4s:
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(out_dir / n)],
                                         capture_output=True, text=True, check=True).stdout)
        kinds = sorted(s["codec_type"] for s in info["streams"])
        assert kinds == ["audio", "video"]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "a12_zip_listing.json").write_text(json.dumps(names, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ A13·A14: 복구·취소·오류

def test_a13_interrupted_jobs_recovered():
    from app import db, jobs

    jid = db.new_id("job")
    db.execute("INSERT INTO jobs(id, kind, status, created_at, started_at, params_json) VALUES(?,?,?,?,?,?)",
               (jid, "silence", "running", db.now(), db.now(), "{}"))
    assert jobs.recover_on_startup() >= 1
    j = jobs.get(jid)
    assert j["status"] == "interrupted" and j["retryable"] == 1 and j["error_code"] == "INTERRUPTED"


def test_a14_cancel_kills_ffmpeg(client, media_dir):
    pid = _project_with_srt(client, media_dir, "취소")
    clip = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 0, "end_ms": 90000, "title": "긴 렌더"}).json()
    job = client.post(f"/api/clips/{clip['id']}/render", json={}).json()
    t0 = time.time()
    while time.time() - t0 < 60:
        j = client.get(f"/api/jobs/{job['id']}").json()
        if j["status"] == "running" and (j["progress"] or 0) > 0.02:
            break
        time.sleep(0.2)
    client.post(f"/api/jobs/{job['id']}/cancel")
    j = wait_job(client, job["id"], 60)
    assert j["status"] == "canceled" and j["error_code"] == "CANCELED"
    time.sleep(0.5)
    ps = subprocess.run(["pgrep", "-af", f"{clip['id']}_"], capture_output=True, text=True).stdout
    assert "ffmpeg" not in ps, ps
    assert not [a for a in client.get(f"/api/artifacts?project_id={pid}").json() if a["clip_id"] == clip["id"]]
    retry = client.post(f"/api/jobs/{job['id']}/retry").json()
    assert retry["status"] == "queued"
    client.post(f"/api/jobs/{retry['id']}/cancel")


def test_a14_ffmpeg_missing_and_disk_full(client, media_dir, monkeypatch):
    pid = _project_with_srt(client, media_dir, "오류")
    clip = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 6000, "title": "오류"}).json()
    monkeypatch.setenv("JSS_FFMPEG", "/없는/경로/ffmpeg.exe")
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/render", json={}).json()["id"])
    assert j["status"] == "failed" and j["error_code"] == "FFMPEG_MISSING" and "FFmpeg를 찾을 수 없습니다" in j["error_message"]
    monkeypatch.delenv("JSS_FFMPEG")
    from app import render
    import collections

    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(render.shutil, "disk_usage", lambda p: Usage(10, 10, 5 * 1024 * 1024))
    d = clip["data"]
    d["speed"] = 1.1  # 편집 상태가 달라야 새 작업
    client.put(f"/api/clips/{clip['id']}", json={"data": d})
    j = wait_job(client, client.post(f"/api/clips/{clip['id']}/render", json={}).json()["id"])
    assert j["status"] == "failed" and j["error_code"] == "DISK_FULL" and j["retryable"]


def test_a14_invalid_api_key_not_leaked(client, media_dir, monkeypatch):
    """실제 Anthropic API에 잘못된 키로 요청해 인증 오류 처리와 키 비노출을 확인(요금 없음)."""
    fake = "sk-ant-api03-INVALIDTESTKEY-0000000000000000000000"
    monkeypatch.setenv("ANTHROPIC_API_KEY", fake)
    pid = _project_with_srt(client, media_dir, "키 오류")
    est = client.get(f"/api/projects/{pid}/recommend/estimate").json()
    err = est.get("estimate_error") or {}
    if err.get("code") == "AI_NETWORK":
        pytest.skip("api.anthropic.com에 연결할 수 없는 환경")
    assert err.get("code") == "AI_AUTH", est
    j = wait_job(client, client.post(f"/api/projects/{pid}/recommend", json={}).json()["id"], 120)
    assert j["status"] == "failed" and j["error_code"] == "AI_AUTH"
    full = client.get(f"/api/jobs/{j['id']}").json()
    blob = json.dumps(full, ensure_ascii=False) + json.dumps(est, ensure_ascii=False)
    assert fake not in blob and "INVALIDTESTKEY" not in blob
    assert client.get(f"/api/projects/{pid}/recommendations").json() == []  # 가짜 결과 없음


# ------------------------------------------------------------------ A15: 캐시·비용

def test_a15_recommendation_cache(client, media_dir, monkeypatch):
    """제공자 호출을 테스트 대역으로 바꿔 '몇 번 호출되는지'만 센다(이 결과는 테스트 DB에만 존재)."""
    from app import recommend

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-placeholder-000000000000")
    calls = []

    def fake_call(cues, settings):
        calls.append(len(cues))
        return json.dumps({"candidates": [{"start_index": 0, "end_index": 9, "titles": ["테스트"], "summary": "", "topic": "",
                                           "reason": "", "score": 50, "cautions": []}]}), {"input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr(recommend, "call_model", fake_call)
    pid = _project_with_srt(client, media_dir, "캐시")
    s = {"settings": {"min_s": 20, "max_s": 40, "count": 3}}
    j1 = wait_job(client, client.post(f"/api/projects/{pid}/recommend", json=s).json()["id"])
    assert j1["status"] == "succeeded" and j1["result"]["cached"] is False
    # 스타일만 변경 → 재분석 없음
    clip = client.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 9000, "title": "x"}).json()
    d = clip["data"]
    d["style"]["subtitle"]["color"] = "#123456"
    client.put(f"/api/clips/{clip['id']}", json={"data": d})
    j2 = wait_job(client, client.post(f"/api/projects/{pid}/recommend", json=s).json()["id"])
    assert j2["result"]["cached"] is True and len(calls) == 1
    # 전사 교정 → 캐시 무효화
    tr = client.get(f"/api/projects/{pid}/transcript").json()["working"]["cues"]
    tr[0]["text"] = tr[0]["text"] + " (교정)"
    client.put(f"/api/projects/{pid}/transcript", json={"cues": tr})
    j3 = wait_job(client, client.post(f"/api/projects/{pid}/recommend", json=s).json()["id"])
    assert j3["result"]["cached"] is False and len(calls) == 2
    # 분석 설정 변경 → 새 분석
    j4 = wait_job(client, client.post(f"/api/projects/{pid}/recommend", json={"settings": {"min_s": 25, "max_s": 40, "count": 3}}).json()["id"])
    assert j4["result"]["cached"] is False and len(calls) == 3


def test_a03_transcribe_paths(client, media_dir):
    """전사 캐시 재사용 경로와, 모델을 받을 수 없을 때의 한국어 오류를 확인한다(실제 한국어 인식 정확도 검증 아님)."""
    from app import db, services, transcribe

    p = client.post("/api/projects/from-path", json={"path": str(media_dir / "강의 샘플.mp4"), "title": "전사"}).json()
    j = wait_job(client, client.post(f"/api/projects/{p['id']}/transcribe", json={}).json()["id"], 600)
    if j["status"] == "succeeded":
        pytest.skip("모델 다운로드가 가능한 환경 — 실제 한국어 음성으로 별도 검수 필요")
    assert j["error_code"] == "STT_MODEL_MISSING" and "전사 모델" in j["error_message"]
    src = services.get_source(p["source_id"])
    key = transcribe.cache_key(src["sha256"])
    cues = [{"id": "c_x", "start_ms": 0, "end_ms": 1000, "text": "캐시된 문장", "flags": []}]
    db.execute("INSERT INTO transcribe_cache(key, cues_json, engine, model, info_json, created_at) VALUES(?,?,?,?,?,?)",
               (key, db.dumps(cues), "faster-whisper", "small", "{}", db.now()))
    j2 = wait_job(client, client.post(f"/api/projects/{p['id']}/transcribe", json={}).json()["id"])
    assert j2["status"] == "succeeded" and j2["result"]["cached"] is True
    # 원문·작업본 분리 저장
    t = client.get(f"/api/projects/{p['id']}/transcript").json()
    assert t["original_meta"]["origin"] == "asr" and t["working"]["cues"][0]["text"] == "캐시된 문장"


def test_segments_to_cues_flags():
    from app import transcribe

    cues = transcribe.segments_to_cues([
        {"start": 0, "end": 2, "text": " SOXL 3.07% 올랐습니다", "avg_logprob": -0.2, "words": [{"word": "SOXL", "start": 0, "end": 0.5, "probability": 0.3}]},
        {"start": 2, "end": 3, "text": "  ", "avg_logprob": -0.1},
    ])
    assert len(cues) == 1 and set(cues[0]["flags"]) >= {"number", "ticker", "low_conf"} and cues[0]["words"][0]["s"] == 0


def test_dictionary_suggestions_not_auto_applied():
    from app import dictionary

    sug = dictionary.suggestions([{"id": "a", "text": "soxl 이랑 TQQ 그리고 엔비디야가"}], ["SOXL", "TQQQ", "엔비디아"])
    found = {(s["found"], s["suggestion"]) for s in sug}
    assert ("soxl", "SOXL") in found and ("TQQ", "TQQQ") in found and ("엔비디야가", "엔비디아") in found


def test_srt_parse_issues():
    from app import subtitles

    raw = "1\n00:00:01,000 --> 00:00:02,000\n<i>안녕</i>\n\n2\n00:00:01,500 --> 00:00:01,200\n\n\n3\n잘못된 줄\n".encode("cp949")
    r = subtitles.parse_subtitles(raw)
    types = {i["type"] for i in r["issues"]}
    assert r["encoding"] == "cp949" and r["cues"][0]["text"] == "안녕"
    assert {"reversed", "no_timecode"} <= types
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.500\n브이티티\n".encode()
    assert subtitles.parse_subtitles(vtt)["cues"][0]["end_ms"] == 2500
