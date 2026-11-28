"""존버나드TV 롱폼 편집기.

  python -m longform_studio prepare <원본.mp4|m4a|wav> [--name 이름] [--srt 자막.srt] [--no-trim]
      → episodes/<이름>/ 에 무음 줄인 원본, 받아쓰기(words.json·transcript.txt), 장면 계획서 뼈대(plan.md)
  (plan.md 에 장면 추가 — Claude에게 "plan.md 채워줘" 라고 시키면 된다)
  python -m longform_studio check  episodes/<이름>      자막·장면 규격 검사만
  python -m longform_studio render episodes/<이름> [--preview]
      → out/final.mp4, subtitles.srt, chapters.txt, qa_report.json, contact_*.jpg
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import compose, media, plan, qa, subtitles, transcript
from .brand import set_convention


def cmd_prepare(a) -> None:
    media.need()
    src = Path(a.input).resolve()
    if not src.exists():
        sys.exit(f"파일이 없습니다: {src}")
    name = a.name or re.sub(r"[^\w가-힣-]+", "_", src.stem).strip("_")
    ep = Path(a.episodes) / name
    ep.mkdir(parents=True, exist_ok=True)
    info = media.probe(src)
    print(f"원본: {src.name}  {info['duration'] / 60:.1f}분  영상={'있음' if info['has_video'] else '없음(음성만)'}")
    keep = [(0.0, info["duration"])]
    work_src = src
    if not a.no_trim:
        sil = media.silences(src)
        keep = media.keep_ranges(info["duration"], sil)
        work_src = ep / ("trimmed.mp4" if info["has_video"] else "trimmed.m4a")
        print(f"긴 무음 {len(sil)}곳 줄이는 중… ({sum(b - a for a, b in keep) / 60:.1f}분으로)")
        media.trim(src, work_src, keep, info["has_video"])
        (ep / "trim_map.json").write_text(json.dumps(keep), encoding="utf-8")
    if a.srt:
        words = transcript.from_subtitle_file(Path(a.srt))
        if not a.no_trim:
            for w in words:
                w["s"], w["e"] = media.map_time(w["s"], keep), media.map_time(w["e"], keep)
    else:
        print(f"받아쓰는 중(faster-whisper {a.model})…")
        words = transcript.from_whisper(work_src, a.model, a.prompt)
    transcript.save(words, ep)
    source = work_src.name if work_src.parent == ep.resolve() or work_src.parent == ep else str(work_src)
    plan.write_skeleton(ep, source, words, info["has_video"], a.title or src.stem)
    print(f"완료: {ep}\n  transcript.txt 확인 → plan.md 에 장면 추가 → render")


def _cues(ep: Path) -> list[dict]:
    return subtitles.make_cues(transcript.sentences(transcript.load(ep)))


def cmd_check(a) -> list[dict]:
    ep = Path(a.episode)
    pl = plan.load(ep)
    set_convention(pl["meta"].get("color_convention"))
    src = compose._src(ep, pl["meta"])
    dur = media.probe(src)["duration"]
    cues = _cues(ep)
    issues = qa.check_cues(cues) + qa.check_pace(pl["scenes"], dur)
    for i in issues:
        print(f"[{i['level']:5s}] {i['at']}  {i['msg']}")
    print(f"장면 {len(pl['scenes'])}개 · 자막 {len(cues)}개 · 오류 {sum(i['level'] == 'error' for i in issues)} · "
          f"경고 {sum(i['level'] == 'warn' for i in issues)}")
    return issues


def cmd_render(a) -> None:
    ep = Path(a.episode)
    pl = plan.load(ep)
    set_convention(pl["meta"].get("color_convention"))
    out = ep / "out"
    out.mkdir(exist_ok=True)
    cues = _cues(ep)
    subtitles.write_ass(cues, out / "subs_src.ass")
    subtitles.write_srt(cues, out / "subtitles.srt")
    chs = plan.chapters(pl["scenes"])
    (out / "chapters.txt").write_text("".join(f"{int(t // 60):02d}:{int(t % 60):02d} {n}\n" for t, n in chs), encoding="utf-8")
    print(f"렌더 시작: 장면 {len(pl['scenes'])}개, 자막 {len(cues)}개")
    final = compose.render(ep, pl, out / "subs_src.ass", preview=a.preview)
    dur = media.probe(final)["duration"]
    issues = qa.check_cues(cues) + qa.check_pace(pl["scenes"], dur) + qa.check_output(final, loudness=not a.preview)
    (out / "qa_report.json").write_text(json.dumps(issues, ensure_ascii=False, indent=1), encoding="utf-8")
    sheets = qa.contact_sheets(final, out)
    errs = sum(i["level"] == "error" for i in issues)
    warns = sum(i["level"] == "warn" for i in issues)
    print(f"완료: {final}  (오류 {errs}, 경고 {warns}, 컨택트시트 {len(sheets)}장)")
    for i in issues:
        if i["level"] != "info":
            print(f"  [{i['level']}] {i['at']} {i['msg']}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="longform_studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("input")
    p.add_argument("--name")
    p.add_argument("--title")
    p.add_argument("--episodes", default="episodes")
    p.add_argument("--srt", help="받아쓰기 대신 쓸 자막 파일(SRT/VTT, 원본 기준 시각)")
    p.add_argument("--no-trim", action="store_true", help="무음 줄이기 생략")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--prompt", help="받아쓰기 힌트(티커·인명 목록)")
    p.set_defaults(fn=cmd_prepare)
    c = sub.add_parser("check")
    c.add_argument("episode")
    c.set_defaults(fn=cmd_check)
    r = sub.add_parser("render")
    r.add_argument("episode")
    r.add_argument("--preview", action="store_true", help="빠른 저화질 렌더")
    r.set_defaults(fn=cmd_render)
    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
