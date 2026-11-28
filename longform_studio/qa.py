"""자동 품질 검사(바이블 §11) + 5초 간격 컨택트시트."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from . import media, templates
from .brand import brand, font

SPLIT_NUM = re.compile(r"\d[\d,.]*$")


def check_cues(cues: list[dict]) -> list[dict]:
    r = brand()["subtitle_rules"]
    out = []
    for i, c in enumerate(cues):
        t = f"{int(c['s'] // 60):02d}:{c['s'] % 60:04.1f}"
        if len(c["text"]) > r["max_chars"]:
            out.append({"level": "error", "at": t, "msg": f"자막 {len(c['text'])}자 > {r['max_chars']}자: {c['text']}"})
        if c["e"] - c["s"] < r["min_duration"] - 1e-6:
            out.append({"level": "warn", "at": t, "msg": f"자막 표시 {c['e'] - c['s']:.2f}초 < {r['min_duration']}초: {c['text']}"})
        if i and c["s"] < cues[i - 1]["e"] - 0.01:
            out.append({"level": "error", "at": t, "msg": "자막 시간이 앞 자막과 겹침"})
        if c["text"].endswith("."):
            out.append({"level": "warn", "at": t, "msg": "자막 끝 마침표"})
        if i + 1 < len(cues) and SPLIT_NUM.search(c["text"]) and re.match(r"^(%|달러|원|억|조|만|배|bp)", cues[i + 1]["text"]):
            out.append({"level": "error", "at": t, "msg": f"숫자와 단위가 갈라짐: {c['text']} / {cues[i + 1]['text']}"})
    return out


def check_pace(scenes: list[dict], duration: float) -> list[dict]:
    mx = brand()["pace"]["max_static_s"]
    out = []
    ends = [s["at"] for s in scenes[1:]] + [duration]
    for s, end in zip(scenes, ends):
        if s["kind"] in templates.MEDIA_KINDS:
            continue
        edges = [s["at"]] + [c for c in s["cues"] if s["at"] < c < end] + [end]
        for a, b in zip(edges, edges[1:]):
            if b - a > mx:
                out.append({"level": "warn", "at": f"{int(a // 60):02d}:{a % 60:04.1f}",
                            "msg": f"{s['kind']} 화면이 {b - a:.0f}초 동안 그대로(기준 {mx}초) — cues 추가 권장 (plan.md {s['line']}행)"})
    for s in scenes:
        if s["kind"] in ("hbar", "T12", "vbar", "T13", "chart", "T06", "rings", "T01", "equation", "T07") and \
                not templates.get(s["kind"]).credit(s["params"]):
            out.append({"level": "warn", "at": f"{int(s['at'] // 60):02d}:{s['at'] % 60:04.1f}",
                        "msg": f"데이터 화면에 출처(credit=) 없음 (plan.md {s['line']}행)"})
    return out


def check_output(final: Path, loudness: bool = True) -> list[dict]:
    info = media.probe(final)
    out = []
    r = media.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                   "-of", "json", str(final)])
    v = json.loads(r.stdout)["streams"][0]
    if (v["width"], v["height"], v["r_frame_rate"]) != (1920, 1080, "30/1"):
        out.append({"level": "error", "at": "-", "msg": f"출력 규격 {v['width']}x{v['height']} {v['r_frame_rate']}"})
    if loudness:
        e = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(final), "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", e)
        if m and abs(float(m[-1]) + 14) > 1.5:
            out.append({"level": "warn", "at": "-", "msg": f"라우드니스 {m[-1]} LUFS (기준 -14)"})
    out.append({"level": "info", "at": "-", "msg": f"길이 {info['duration'] / 60:.1f}분"})
    return out


def contact_sheets(final: Path, out_dir: Path, every: int = 5, prefix: str = "contact") -> list[Path]:
    with tempfile.TemporaryDirectory() as td:
        # 시간 기준으로 every초마다 한 장(원본 fps가 달라도 라벨이 맞도록)
        media.run(["ffmpeg", "-y", "-i", str(final), "-vf",
                   f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{every - 0.001})',"
                   "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2",
                   "-fps_mode", "vfr", f"{td}/f_%05d.jpg"])
        files = sorted(Path(td).glob("f_*.jpg"))
        sheets = []
        for s in range(0, len(files), 20):
            sheet = Image.new("RGB", (1600, 720), "black")
            d = ImageDraw.Draw(sheet)
            for k, p in enumerate(files[s:s + 20]):
                x, y = (k % 5) * 320, (k // 5) * 180
                sheet.paste(Image.open(p), (x, y))
                t = (s + k) * every
                d.rectangle((x, y, x + 70, y + 24), fill=(255, 230, 0))
                d.text((x + 4, y + 2), f"{t // 60:02d}:{t % 60:02d}", fill="black", font=font("bold", 18))
            fp = out_dir / f"{prefix}_{s // 20:02d}.jpg"
            sheet.save(fp, quality=88)
            sheets.append(fp)
    return sheets
