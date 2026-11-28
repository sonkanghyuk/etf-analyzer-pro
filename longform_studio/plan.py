"""장면 계획서 plan.md 읽기/뼈대 쓰기.

형식:
    ---
    source: trimmed.mp4          # 에피소드 폴더 기준 경로(또는 절대경로)
    title: 영상 제목
    color_convention: us
    logo: logo.png               # 선택. 없으면 longform_studio/assets/logo.png → 임시 텍스트 로고
    ---
    ## 챕터 이름                  # 설명란 타임스탬프가 된다
    ::: video at=00:00
    ::: vbar at=01:23.4 title="헤지펀드의 기술주 쏠림" data="통상 10년:27.0|2026년:40.0!" cues=01:25.0
    <!-- [01:22.0] 받아쓴 문장 (참고용 주석) -->

장면은 at 부터 다음 장면 at 까지 이어진다. cues = 빌드(항목 추가) 시각 목록.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

from . import templates
from .transcript import mmss, sentences


def parse_time(s: str) -> float:
    s = str(s).strip()
    if re.fullmatch(r"[\d.]+", s):
        return float(s)
    parts = [float(x) for x in s.split(":")]
    t = 0.0
    for x in parts:
        t = t * 60 + x
    return t


def load(ep: Path) -> dict:
    text = (ep / "plan.md").read_text(encoding="utf-8")
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        meta = yaml.safe_load(m.group(1)) or {}
        text = text[m.end():]
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    scenes, chapter = [], None
    for ln_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if line.startswith("## "):
            chapter = line[3:].strip()
        elif line.startswith(":::"):
            toks = shlex.split(line[3:].strip())
            if not toks:
                raise ValueError(f"plan.md {ln_no}행: 템플릿 이름이 없습니다")
            kind, params = toks[0], {}
            for t in toks[1:]:
                k, eq, v = t.partition("=")
                if not eq:
                    raise ValueError(f"plan.md {ln_no}행: '{t}' 는 key=value 형식이어야 합니다")
                params[k] = v
            if "at" not in params:
                raise ValueError(f"plan.md {ln_no}행: at= 시각이 필요합니다")
            if kind not in templates.MEDIA_KINDS:
                templates.get(kind)
            scenes.append({"kind": kind, "at": parse_time(params.pop("at")), "chapter": chapter,
                           "cues": [parse_time(c) for c in params.pop("cues", "").split(",") if c.strip()],
                           "params": params, "line": ln_no})
    scenes.sort(key=lambda s: s["at"])
    if not scenes or scenes[0]["at"] > 0.05:
        scenes.insert(0, {"kind": "video", "at": 0.0, "chapter": scenes[0]["chapter"] if scenes else None,
                          "cues": [], "params": {}, "line": 0})
    for a, b in zip(scenes, scenes[1:]):
        if b["at"] - a["at"] < 0.2:
            raise ValueError(f"plan.md {b['line']}행: 장면 시각이 앞 장면({a['line']}행)과 너무 가깝습니다")
    return {"meta": meta, "scenes": scenes}


def chapters(scenes: list[dict]) -> list[tuple[float, str]]:
    out, seen = [], None
    for s in scenes:
        if s["chapter"] and s["chapter"] != seen:
            out.append((s["at"], s["chapter"]))
            seen = s["chapter"]
    if out and out[0][0] > 0:
        out[0] = (0.0, out[0][1])
    return out


def write_skeleton(ep: Path, source: str, words: list[dict], has_video: bool, title: str) -> Path:
    base = "video" if has_video else f'paper title="{title}"'
    lines = ["---", f"source: {source}", f"title: {title}", "color_convention: us", "---", "",
             "## 본편", f"::: {base} at=00:00", ""]
    for s in sentences(words):
        lines.append(f"<!-- [{mmss(s[0]['s'])}] {' '.join(w['w'] for w in s)} -->")
    p = ep / "plan.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p
