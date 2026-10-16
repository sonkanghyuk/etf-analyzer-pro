"""샘플 입력·프로젝트·완성 MP4를 samples/ 폴더에 다시 만든다(외부 API 사용 안 함).

python tools/make_samples.py
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "samples"
os.environ["JSS_DATA_DIR"] = tempfile.mkdtemp(prefix="jss_samples_")
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(ROOT))


def main() -> None:
    inp, outp = SAMPLES / "input", SAMPLES / "output"
    inp.mkdir(parents=True, exist_ok=True)
    if outp.exists():
        shutil.rmtree(outp)
    outp.mkdir(parents=True)
    tool = ROOT / "tools" / "make_test_media.py"
    subprocess.run([sys.executable, str(tool), str(inp), "--duration", "90", "--silence", "", "--name", "lecture_sample"], check=True)
    subprocess.run([sys.executable, str(tool), str(inp), "--duration", "10", "--silence", "4-6", "--name", "sync_test"], check=True)

    from fastapi.testclient import TestClient

    from app import jobs
    from app.main import app

    with TestClient(app) as c:
        p = c.post("/api/projects/from-path", json={"path": str(inp / "lecture_sample.mp4"), "title": "샘플 강의"}).json()
        pid = p["id"]
        c.post(f"/api/projects/{pid}/subtitles", files={"file": ("s.srt", (inp / "lecture_sample.srt").read_bytes())})
        made = []
        # 1) 검은 배경 강의 보존형 + 강조
        c1 = c.post(f"/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 21000, "title": "SOXL · TQQQ 자막 렌더링 샘플", "template_id": "tpl_builtin_dark"}).json()
        d = c1["data"]
        cue = next(x for x in d["cues"] if x["text"].startswith("SOXL"))
        cue["emphasis"] = [[0, 4], [21, 26]]
        c.put(f"/api/clips/{c1['id']}", json={"data": d})
        made.append(c1["id"])
        # 2) 밝은 배경 + 발화 1개 삭제 + 1.25배
        c2 = c.post(f"/api/projects/{pid}/clips", json={"start_ms": 24000, "end_ms": 54000, "title": "밝은 템플릿 · 발화 삭제 · 1.25배", "template_id": "tpl_builtin_light"}).json()
        c2 = c.post(f"/api/clips/{c2['id']}/cues/{c2['data']['cues'][1]['id']}/delete-speech", json={}).json()
        d = c2["data"]
        d["speed"] = 1.25
        c.put(f"/api/clips/{c2['id']}", json={"data": d})
        made.append(c2["id"])
        # 3) 미니멀 + 사용자 지정 크롭(자료 확대)
        c3 = c.post(f"/api/projects/{pid}/clips", json={"start_ms": 57000, "end_ms": 87000, "title": "미니멀 템플릿 · 영역 확대(사용자 크롭)", "template_id": "tpl_builtin_minimal"}).json()
        d = copy.deepcopy(c3["data"])
        d["style"]["video"]["crop"] = {"enabled": True, "x": 0.25, "y": 0.2, "w": 0.5, "h": 0.6}
        c.put(f"/api/clips/{c3['id']}", json={"data": d})
        made.append(c3["id"])
        r = c.post(f"/api/projects/{pid}/batch-export", json={"clip_ids": made, "zip": True}).json()
        zj = jobs.wait(r["zip_job"]["id"], 900)
        assert zj["status"] == "succeeded", zj
        for a in c.get(f"/api/artifacts?project_id={pid}").json():
            src = Path(a["path"])
            for ext in (".mp4", ".srt"):
                shutil.copy(src.with_suffix(ext), outp / src.with_suffix(ext).name)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2.5", "-i", str(src), "-frames:v", "1", "-vf", "scale=360:640",
                            str(outp / (src.stem + "_frame.jpg"))], check=True)
        za = next(a for a in c.get(f"/api/artifacts?project_id={pid}&kind=zip").json())
        shutil.copy(za["path"], outp / za["filename"])
        (outp / "sample_project.jss.json").write_text(json.dumps(c.get(f"/api/projects/{pid}/export.json").json(), ensure_ascii=False, indent=1), encoding="utf-8")
        probes = {}
        for f in sorted(outp.glob("*.mp4")):
            probes[f.name] = json.loads(subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_entries",
                                                        "format=duration:stream=codec_name,width,height,pix_fmt,avg_frame_rate,sample_rate",
                                                        str(f)], capture_output=True, text=True, check=True).stdout)
        (outp / "ffprobe.json").write_text(json.dumps(probes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(outp)


if __name__ == "__main__":
    main()
