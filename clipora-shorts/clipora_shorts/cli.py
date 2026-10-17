"""clipora-shorts: 촬영본 → 숏폼 MP4 여러 개.

예)
  clipora-shorts 강의.mp4
  clipora-shorts 강연.mov --count 5 --template blur --start 10:00 --end 40:00
  clipora-shorts 인터뷰.mp4 --template talk --reframe face --persona "20대 직장인 대상 커리어 채널"
"""

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import __version__, captions, config, highlights, media, render, sample, templates, transcribe


def parse_time(value: str) -> float:
    """'90', '1:30', '01:02:03', '75.5' → 초"""
    try:
        parts = [float(p) for p in value.strip().split(":")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"시간 형식이 아니에요: {value} (예: 90, 1:30, 1:02:03)")
    if not 1 <= len(parts) <= 3 or any(p < 0 for p in parts):
        raise argparse.ArgumentTypeError(f"시간 형식이 아니에요: {value}")
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def safe_name(text: str, limit: int = 30) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", text).strip().rstrip(".")
    return (name[:limit].strip() or "short")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clipora-shorts",
        description="강의·강연·인터뷰 촬영본에서 AI가 하이라이트를 골라 자막 입힌 9:16 숏폼 MP4로 만듭니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="템플릿: " + ", ".join(f"{t.id}({t.name})" for t in templates.TEMPLATES.values()),
    )
    p.add_argument("video", nargs="?", type=Path, help="촬영본 파일 (mp4, mov, mkv ...)")
    p.add_argument("-o", "--out", type=Path, help="결과 폴더 (기본: <파일이름>_shorts)")
    p.add_argument("-n", "--count", type=int, help="만들 숏폼 개수 (기본: 원본 5분당 1개, 최대 10개)")
    p.add_argument("--min", dest="min_len", type=float, default=20, help="숏폼 최소 길이(초), 기본 20")
    p.add_argument("--max", dest="max_len", type=float, default=60, help="숏폼 최대 길이(초), 기본 60")
    p.add_argument("--start", type=parse_time, help="분석할 구간 시작 (예: 10:00)")
    p.add_argument("--end", type=parse_time, help="분석할 구간 끝 (예: 40:00)")
    p.add_argument("-t", "--template", default="blur", choices=list(templates.TEMPLATES), help="숏폼 템플릿, 기본 blur")
    p.add_argument("--reframe", default="face", choices=["face", "center"],
                   help="꽉 채우는 템플릿에서 자를 위치: face(얼굴 따라가기, opencv 필요) / center")
    p.add_argument("--persona", default="", help="채널 성격·타깃 (하이라이트 선정과 제목에 반영)")
    p.add_argument("--no-ai", action="store_true", help="Claude 없이 규칙 기반으로 하이라이트 선정")
    p.add_argument("--model", default=highlights.DEFAULT_MODEL, help=f"Claude 모델, 기본 {highlights.DEFAULT_MODEL}")
    p.add_argument("--whisper", default="small", help="Whisper 모델: tiny/base/small/medium/large-v3, 기본 small")
    p.add_argument("--language", default="ko", help="음성 언어, 기본 ko")
    p.add_argument("--device", default="auto", help="음성인식 장치: auto/cpu/cuda")
    p.add_argument("--transcript", type=Path, help="이미 만든 transcript.json 사용 (음성인식 건너뜀)")
    p.add_argument("--font", default=render.default_font(), help="자막 글꼴 이름")
    p.add_argument("--fontsdir", help="글꼴 파일(.ttf/.otf)이 있는 폴더")
    p.add_argument("--quality", default="normal", choices=["fast", "normal", "high"], help="인코딩 품질/속도")
    p.add_argument("--no-loudnorm", action="store_true", help="음량 평준화(-14 LUFS) 끄기")
    p.add_argument("--plan-only", action="store_true", help="영상은 만들지 않고 하이라이트 목록만 출력")
    p.add_argument("--list-templates", action="store_true", help="템플릿 목록 보기")
    p.add_argument("--demo", action="store_true", help="샘플 영상으로 설치 확인 (인터넷·API 키 불필요)")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def log(msg: str) -> None:
    print(msg, flush=True)


def progress_bar(label: str):
    last = [-1]

    def update(ratio: float) -> None:
        pct = int(ratio * 100)
        if pct != last[0]:
            last[0] = pct
            filled = pct // 4
            sys.stdout.write(f"\r  {label} [{'█' * filled}{'·' * (25 - filled)}] {pct:3d}%")
            sys.stdout.flush()
            if pct >= 100:
                sys.stdout.write("\n")

    return update


def get_transcript(args, info, out: Path, start: float, end: float) -> dict:
    if args.transcript:
        log(f"📝 자막 불러오기: {args.transcript}")
        return transcribe.load(args.transcript)

    cache = out / "transcript.json"
    key = {"source": args.video.name, "size": args.video.stat().st_size, "start": start, "end": end,
           "whisper": args.whisper, "language": args.language}
    if cache.exists():
        try:
            data = transcribe.load(cache)
            if data.get("key") == key:
                log("📝 이전에 만든 자막을 다시 씁니다 (transcript.json)")
                return data
        except (ValueError, json.JSONDecodeError):
            pass

    if not info.has_audio:
        raise SystemExit("❌ 소리가 없는 영상이에요. 음성이 있는 촬영본을 넣어 주세요.")
    log(f"🎧 음성 추출 중… ({captions_mmss(start)}–{captions_mmss(end)})")
    wav = out / ".work" / "audio.wav"
    media.extract_audio(args.video, wav, start, end)
    log(f"📝 음성인식 중 (Whisper {args.whisper}, 처음 실행 시 모델을 내려받아요)")
    t0 = time.time()
    data = transcribe.transcribe(wav, offset=start, model_size=args.whisper, language=args.language,
                                 device=args.device, on_progress=progress_bar("음성인식"))
    progress_bar("음성인식")(1.0)
    log(f"  문장 {len(data['segments'])}개 인식 ({time.time() - t0:.0f}초)")
    data["key"] = key
    transcribe.save(data, cache)
    wav.unlink(missing_ok=True)
    return data


def captions_mmss(t: float) -> str:
    t = int(t)
    return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def write_summary(out: Path, results: list[dict], source: str, method: str) -> Path:
    lines = [f"# 숏폼 {len(results)}개 — {source}", "",
             f"하이라이트 선정: {'Claude (내용 분석)' if method == 'claude' else '규칙 기반 (말 밀도·문장 경계)'}", ""]
    for r in results:
        lines += [f"## {r['rank']:02d}. {r['title']}", "",
                  f"- 파일: `{r['file']}`",
                  f"- 원본 구간: {captions_mmss(r['start'])} – {captions_mmss(r['end'])} ({r['duration']:.0f}초) · 점수 {r['score']}"]
        if r["hook"]:
            lines.append(f"- 첫 문장 훅: {r['hook']}")
        if r["reason"]:
            lines.append(f"- 고른 이유: {r['reason']}")
        if r["hashtags"]:
            lines.append("- 해시태그: " + " ".join("#" + h for h in r["hashtags"]))
        lines += ["", "업로드 설명 예시:", "", f"> {r['title']}" + ("  \n> " + " ".join("#" + h for h in r["hashtags"]) if r["hashtags"] else ""), ""]
    path = out / "업로드정보.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_templates:
        for t in templates.TEMPLATES.values():
            print(f"  {t.id:8s} {t.name} — {t.desc}")
        return 0
    config.apply_api_key()
    if args.demo:
        try:
            media.require_tools()
        except media.MediaError as e:
            log(f"❌ {e}")
            return 1
        base = (args.out.parent if args.out else Path.cwd() / "Clipora_샘플")
        log("🧪 샘플 영상으로 시험합니다 (음성인식·AI 없이 규칙 기반)")
        args.video, args.transcript = sample.create(base)
        args.no_ai, args.min_len, args.max_len = True, 15, 40
        args.count = args.count or 2
        args.out = args.out or base / "결과"
    if not args.video:
        build_parser().print_help()
        return 2
    if not args.video.exists():
        log(f"❌ 파일이 없어요: {args.video}")
        return 1
    if args.min_len <= 0 or args.max_len < args.min_len:
        log("❌ --min/--max 길이를 확인해 주세요")
        return 1

    try:
        media.require_tools()
        info = media.probe(args.video)
    except media.MediaError as e:
        log(f"❌ {e}")
        return 1

    start = args.start or 0.0
    end = min(args.end, info.duration) if args.end else info.duration
    if end - start < args.min_len:
        log(f"❌ 분석 구간({end - start:.0f}초)이 최소 숏폼 길이({args.min_len:.0f}초)보다 짧아요")
        return 1
    if not args.fontsdir and sys.platform.startswith("win"):
        # Windows용 ffmpeg는 시스템 글꼴을 못 찾는 경우가 있어 글꼴 폴더를 직접 알려 줍니다.
        args.fontsdir = str(Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts")
    out = args.out or args.video.with_name(f"{args.video.stem}_shorts")
    (out / ".work").mkdir(parents=True, exist_ok=True)
    tpl = templates.get(args.template)
    log(f"🎬 {args.video.name} · {info.width}x{info.height} · {captions_mmss(info.duration)} → {out}")

    data = get_transcript(args, info, out, start, end)
    segments = [s for s in data["segments"] if s["end"] > start and s["start"] < end]
    if not segments:
        log("❌ 인식된 말이 없어요. 음성이 들어 있는지, --language가 맞는지 확인해 주세요.")
        return 1

    span = end - start
    # 원본 5분당 1개, 짧은 영상도 길이가 되면 최대 3개까지
    count = args.count or max(1, min(10, max(round(span / 300), min(3, int(span // (args.max_len * 1.5))))))
    log(f"✨ 하이라이트 고르는 중… (최대 {count}개, {args.min_len:.0f}~{args.max_len:.0f}초)")
    clips, method = highlights.pick(segments, count, args.min_len, args.max_len,
                                    use_ai=not args.no_ai, persona=args.persona, model=args.model, log=log)
    if not clips:
        log("❌ 조건에 맞는 구간을 찾지 못했어요. --min 값을 줄여 보세요.")
        return 1
    for i, c in enumerate(clips, 1):
        log(f"  {i:2d}. [{c.score:3d}점] {captions_mmss(c.start)}–{captions_mmss(c.end)} ({c.duration:.0f}초) {c.title}")

    results = []
    for i, c in enumerate(clips, 1):
        base = f"{i:02d}_{safe_name(c.title)}"
        chunks = captions.caption_chunks(segments, c.start, c.end)
        (out / f"{base}.srt").write_text(captions.to_srt(chunks), encoding="utf-8")
        results.append({"rank": i, "file": f"{base}.mp4", **asdict(c), "duration": round(c.duration, 2), "captions": chunks})
        if args.plan_only:
            continue

        ass_path = out / ".work" / f"{i:02d}.ass"
        ass_path.write_text(captions.to_ass(chunks, c.title, c.duration, tpl, args.font), encoding="utf-8")
        needs_crop = tpl.layout == "fill" or info.width / info.height <= 0.8
        face_x = None
        if needs_crop and args.reframe == "face":
            from .reframe import face_center_x
            face_x = face_center_x(args.video, c.start, c.end)
        log(f"🎞️  {i}/{len(clips)} 렌더링: {base}.mp4" + (" (얼굴 위치에 맞춰 자름)" if face_x is not None else ""))
        try:
            render.render_clip(args.video, info, c.start, c.end, tpl, ass_path, out / f"{base}.mp4",
                               face_x=face_x, fontsdir=args.fontsdir, quality=args.quality,
                               loudnorm=not args.no_loudnorm)
            render.thumbnail(out / f"{base}.mp4", out / f"{base}.jpg", at=min(1.0, c.duration / 2))
        except media.MediaError as e:
            log(f"  ❌ {e}")
            results[-1]["error"] = str(e)

    (out / "clips.json").write_text(json.dumps({"source": args.video.name, "method": method, "template": tpl.id,
                                                "clips": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = write_summary(out, results, args.video.name, method)
    failed = sum(1 for r in results if "error" in r)
    log(f"\n✅ 완료: 숏폼 {len(results) - failed}개" + (f" (실패 {failed}개)" if failed else "")
        + f"\n   폴더: {out}\n   업로드 정보: {summary.name}")
    return 1 if failed == len(results) and not args.plan_only else 0
