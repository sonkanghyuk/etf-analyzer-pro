"""A09: 브라우저 미리보기 화면과 최종 MP4 프레임 비교(서버가 떠 있어야 함).

python tests/ui_preview_match.py http://127.0.0.1:8790 <영상.mp4> <자막.srt> <증거폴더>
같은 출력 시각에서 미리보기(.stage 스크린샷)와 MP4 프레임의 제목·자막 영역을 비교한다.
- 글자 픽셀 경계상자(bbox)의 좌표 차이(캔버스 너비 대비 %)
- 강조색(노랑) 픽셀 존재 여부
- 줄 수·줄 내용(미리보기 장면 API vs 렌더링 메타)
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import requests  # type: ignore
from PIL import Image
from playwright.sync_api import sync_playwright

base, video, srt, out = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
s = requests.Session()


def j(r):
    r.raise_for_status()
    return r.json()


proj = j(s.post(f"{base}/api/projects/from-path", json={"path": video, "title": "A09 비교"}))
pid = proj["id"]
with open(srt, "rb") as f:
    j(s.post(f"{base}/api/projects/{pid}/subtitles", files={"file": ("a.srt", f)}))
clip = j(s.post(f"{base}/api/projects/{pid}/clips", json={"start_ms": 3000, "end_ms": 21000, "title": "미리보기 일치 검사 SOXL 3.07%"}))
data = clip["data"]
emph_cue = next(c for c in data["cues"] if c["text"].startswith("SOXL"))
emph_cue["emphasis"] = [[0, 4], [21, 26]]  # 'SOXL', '3.07%'
clip = j(s.put(f"{base}/api/clips/{clip['id']}", json={"data": data, "label": "강조"}))
job = j(s.post(f"{base}/api/clips/{clip['id']}/render", json={}))
while True:
    job = j(s.get(f"{base}/api/jobs/{job['id']}"))
    if job["status"] in ("succeeded", "failed", "canceled", "interrupted"):
        break
    time.sleep(0.5)
assert job["status"] == "succeeded", job
art = next(a for a in j(s.get(f"{base}/api/artifacts?project_id={pid}")) if a["id"] == job["result"]["artifact_id"])
mp4 = Path(art["path"])
scene = j(s.post(f"{base}/api/clips/{clip['id']}/scene", json={}))
cues = scene["cues"]
emph_out = next(c for c in cues if c["id"] == emph_cue["id"])
times = {"start": cues[0], "middle": cues[len(cues) // 2], "end": cues[-1], "emphasis": emph_out}


def frame(t: float) -> Image.Image:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1", "-c:v", "png", "-f", "image2", "-"],
                         capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(raw)).convert("RGB")


def text_bbox(img: np.ndarray, box: dict, emph: bool = False):
    x0, y0 = max(0, int(box["x"]) - 10), max(0, int(box["y"]) - 10)
    x1, y1 = min(1080, int(box["x"] + box["w"]) + 10), min(1920, int(box["y"] + box["h"]) + 10)
    reg = img[y0:y1, x0:x1].astype(int)
    if emph:
        mask = (reg[..., 0] > 200) & (reg[..., 1] > 170) & (reg[..., 2] < 90)  # 강조색 #FFD400
    else:
        mask = reg.min(axis=2) > 200  # 흰 글자
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None, 0
    return [int(xs.min() + x0), int(ys.min() + y0), int(xs.max() + x0), int(ys.max() + y0)], int(mask.sum())


results = {}
with sync_playwright() as p:
    exe = os.environ.get("JSS_CHROMIUM")
    b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    page = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
    page.goto(f"{base}/#/project/{pid}?clip={clip['id']}")
    page.wait_for_selector(".stage .sel", timeout=30000)
    page.add_style_tag(content=".stage .sel, .stage .safe, .stage .safe-label, .stage .notice, .stage .guide { display: none !important; }")
    for name, c in times.items():
        t_ms = (c["out_start_ms"] + c["out_end_ms"]) / 2
        page.evaluate(f"(() => {{ const r = document.querySelector('.transport input[type=range]'); r.value = {round(t_ms)}; r.dispatchEvent(new Event('input')); }})()")
        page.wait_for_timeout(700)
        shot = Image.open(io.BytesIO(page.locator(".stage").screenshot())).convert("RGB").resize((1080, 1920), Image.LANCZOS)
        fr = frame(t_ms / 1000)
        shot.save(out / f"a09_{name}_preview.png")
        fr.save(out / f"a09_{name}_output.png")
        side = Image.new("RGB", (1080 * 2 + 20, 1920), "white")
        side.paste(shot, (0, 0))
        side.paste(fr, (1100, 0))
        side.resize((1100, 960)).save(out / f"a09_{name}_side_by_side.png")
        P, O = np.asarray(shot), np.asarray(fr)
        entry = {"t_ms": t_ms, "lines_scene": c["lines"]}
        meta = next(co for co in art["meta"]["cue_overlays"] if co["cue_id"] == c["id"])
        entry["lines_output_meta"] = meta["lines"]
        for label, box, emph in (("title", scene["title"]["text_box"], False), ("subtitle", c["text_box"], False)) + \
                (("emphasis", c["text_box"], True),) * (name == "emphasis"):
            bp, np_ = text_bbox(P, box, emph)
            bo, no = text_bbox(O, box, emph)
            diff = None if bp is None or bo is None else max(abs(a - b2) for a, b2 in zip(bp, bo)) / 1080 * 100
            entry[label] = {"preview_bbox": bp, "output_bbox": bo, "max_coord_diff_pct": diff, "preview_px": np_, "output_px": no}
        results[name] = entry
    b.close()

ok = True
for name, e in results.items():
    if e["lines_scene"] != e["lines_output_meta"]:
        ok = False
    for k in ("title", "subtitle", "emphasis"):
        if k in e and (e[k]["max_coord_diff_pct"] is None or e[k]["max_coord_diff_pct"] > 0.5):
            ok = False
results["PASS"] = ok
(out / "a09_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=1))
sys.exit(0 if ok else 1)
