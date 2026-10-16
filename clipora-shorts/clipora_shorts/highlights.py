"""하이라이트 선정.

- Claude: 자막 전체를 읽고 "앞뒤 맥락 없이도 이해되는, 끝까지 보게 되는" 구간과 제목을 고릅니다.
- 휴리스틱(--no-ai 또는 API 키 없음): 말이 빽빽하고, 쉼 뒤에 시작해서 문장 끝에서 끝나는 구간을 고릅니다.
어느 쪽이든 결과는 같은 검증(길이·겹침·문장 경계)을 거칩니다.
"""

import json
import re
from dataclasses import dataclass, field

DEFAULT_MODEL = "claude-opus-5-5"
# 숏폼 첫 문장으로 약한 시작: 인사, 진행 멘트, 앞 내용 참조
WEAK_START = re.compile(r"^(안녕하세요|안녕하십니까|감사합니다|자[,\s]|네[,\s]|그래서|그리고|앞에서|아까|방금|지난 시간|다음 시간|오늘 강의)")
SENTENCE_END = re.compile(r"[.?!…]$|(?:다|요|죠|까|니다|세요)[.?!]?$")


@dataclass
class Clip:
    start: float
    end: float
    title: str
    score: int = 0
    hook: str = ""
    reason: str = ""
    hashtags: list[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


class HighlightError(Exception):
    pass


def mmss(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:04.1f}"


def format_transcript(segments: list[dict]) -> str:
    return "\n".join(f"[{s['id']}] {mmss(s['start'])}-{mmss(s['end'])} {s['text']}" for s in segments)


# ---------- Claude ----------

SYSTEM = """당신은 강의·강연·인터뷰·웨비나 촬영본에서 유튜브 쇼츠/인스타그램 릴스용 클립을 뽑는 숏폼 에디터입니다.

좋은 클립의 기준:
- 앞뒤 맥락 없이 이 클립만 봐도 이해된다 (생각의 시작에서 시작하고, 결론이나 펀치라인에서 끝난다).
- 첫 3초 안에 궁금증이나 공감을 일으키는 문장이 있다.
- 구체적인 팁, 의외의 사실, 강한 의견, 감정이 실린 이야기, 웃음 포인트처럼 공유하고 싶어지는 내용이다.
- 인사, 진행 멘트, 슬라이드 넘김, "앞에서 말씀드린" 같은 앞부분 참조로 시작하는 구간은 피한다.

제목은 22자 이내 한국어로, 클립 내용을 정확히 반영하면서 끝까지 보고 싶게 쓴다. 자막에 없는 사실이나 과장된 약속은 넣지 않고, 이모지는 쓰지 않는다.
해시태그는 '#' 없이 단어만 3~5개 쓴다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start_id": {"type": "integer"},
                    "end_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "hook": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "integer"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["start_id", "end_id", "title", "hook", "reason", "score", "hashtags"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["clips"],
    "additionalProperties": False,
}


def pick_with_claude(
    segments: list[dict],
    count: int,
    min_len: float,
    max_len: float,
    persona: str = "",
    model: str = DEFAULT_MODEL,
) -> list[Clip]:
    import anthropic

    prompt = (
        f"아래는 촬영본의 자막입니다. 각 줄은 [세그먼트 번호] 시작-끝 내용입니다.\n"
        f"숏폼으로 만들 구간을 최대 {count}개 골라 주세요. 각 구간은 {min_len:.0f}~{max_len:.0f}초 길이로, "
        f"start_id 세그먼트의 시작부터 end_id 세그먼트의 끝까지입니다. 구간끼리 겹치면 안 되고, "
        f"좋은 구간이 부족하면 억지로 채우지 말고 적게 고르세요. score는 0~100으로 숏폼 성과 예상치입니다.\n"
    )
    if persona:
        prompt += f"\n채널 페르소나(선정과 제목에 반영): {persona}\n"
    prompt += f"\n<transcript>\n{format_transcript(segments)}\n</transcript>"

    client = anthropic.Anthropic()
    try:
        # 긴 강의는 입력이 커서 스트리밍으로 받습니다(타임아웃 방지).
        with client.beta.messages.stream(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise HighlightError("ANTHROPIC_API_KEY가 올바르지 않아요") from e
    except anthropic.RateLimitError as e:
        raise HighlightError("Claude API 요청 한도에 걸렸어요. 잠시 후 다시 시도해 주세요") from e
    except anthropic.APIStatusError as e:
        raise HighlightError(f"Claude API 오류 ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise HighlightError("Claude API에 연결하지 못했어요") from e
    except TypeError as e:  # SDK가 인증 정보를 찾지 못한 경우
        raise HighlightError("Claude 인증 정보가 없어요 (ANTHROPIC_API_KEY 설정 필요)") from e

    if response.stop_reason == "refusal":
        raise HighlightError("Claude가 이 영상의 하이라이트 선정을 거절했어요")
    if response.stop_reason == "max_tokens":
        raise HighlightError("Claude 응답이 잘렸어요. --count를 줄여 다시 시도해 주세요")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        raw = json.loads(text)["clips"]
    except (ValueError, KeyError) as e:
        raise HighlightError("Claude 응답을 해석하지 못했어요") from e

    by_id = {s["id"]: s for s in segments}
    clips = []
    for c in raw:
        a, b = sorted((c["start_id"], c["end_id"]))
        if a not in by_id or b not in by_id:
            continue
        clips.append({
            "ids": (a, b), "title": c["title"].strip(), "score": int(c["score"]),
            "hook": c["hook"].strip(), "reason": c["reason"].strip(),
            "hashtags": [h.strip().lstrip("#") for h in c["hashtags"] if h.strip()][:5],
        })
    return finalize(clips, segments, count, min_len, max_len)


# ---------- 휴리스틱 ----------

def pick_heuristic(segments: list[dict], count: int, min_len: float, max_len: float) -> list[Clip]:
    if not segments:
        return []
    rates = [len(s["text"].replace(" ", "")) / max(0.3, s["end"] - s["start"]) for s in segments]
    max_rate = max(rates) or 1
    cands = []
    for i in range(len(segments)):
        talk = 0.0
        chars = 0
        for j in range(i, len(segments)):
            talk += segments[j]["end"] - segments[j]["start"]
            chars += len(segments[j]["text"].replace(" ", ""))
            span = segments[j]["end"] - segments[i]["start"]
            if span > max_len:
                break
            if span < min_len:
                continue
            density = talk / span
            rate = min(1.0, (chars / span) / max_rate)
            after_pause = i == 0 or segments[i]["start"] - segments[i - 1]["end"] > 0.6
            weak_start = bool(WEAK_START.search(segments[i]["text"].strip()))
            ends_sentence = bool(SENTENCE_END.search(segments[j]["text"].strip()))
            fullness = min(1.0, span / ((min_len + max_len) / 2))  # 너무 짧은 구간보다 적당한 길이를 선호
            score = 0.45 * density + 0.15 * rate + 0.15 * after_pause + 0.15 * ends_sentence + 0.1 * fullness - 0.3 * weak_start
            cands.append({"ids": (segments[i]["id"], segments[j]["id"]), "score": round(score * 100)})
    cands.sort(key=lambda c: -c["score"])
    for c in cands:
        c["title"] = ""
    return finalize(cands, segments, count, min_len, max_len)


# ---------- 공통 검증 ----------

def finalize(cands: list[dict], segments: list[dict], count: int, min_len: float, max_len: float) -> list[Clip]:
    """길이를 맞추고, 겹치는 구간은 점수 높은 쪽만 남기고, 앞뒤에 숨 쉴 여유를 붙입니다."""
    idx = {s["id"]: k for k, s in enumerate(segments)}
    picked: list[Clip] = []
    for c in sorted(cands, key=lambda c: -c["score"]):
        a, b = idx[c["ids"][0]], idx[c["ids"][1]]
        while b > a and segments[b]["end"] - segments[a]["start"] > max_len:
            b -= 1
        start, end = segments[a]["start"], segments[b]["end"]
        if end - start > max_len * 1.15:  # 세그먼트 하나가 너무 긴 경우
            end = start + max_len
        if end - start < min_len * 0.5:
            continue
        # 앞뒤 여유: 이전/다음 세그먼트를 침범하지 않는 범위에서
        prev_end = segments[a - 1]["end"] if a > 0 else 0.0
        next_start = segments[b + 1]["start"] if b + 1 < len(segments) else end + 1.0
        start = max(prev_end, start - 0.15, 0.0)
        end = min(next_start, end + 0.35)
        if any(start < p.end and end > p.start for p in picked):
            continue
        title = c.get("title") or first_sentence(" ".join(s["text"] for s in segments[a : b + 1]))
        picked.append(Clip(
            start=round(start, 3), end=round(end, 3), title=title[:40], score=max(0, min(100, c["score"])),
            hook=c.get("hook", ""), reason=c.get("reason", ""), hashtags=c.get("hashtags", []),
        ))
        if len(picked) >= count:
            break
    return sorted(picked, key=lambda p: -p.score)


def first_sentence(text: str, limit: int = 22) -> str:
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+|(?<=[다요죠까])\s+", text) if len(p.strip()) >= 6]
    best = min(parts, key=lambda p: abs(16 - len(p))) if parts else text.strip()
    best = best.rstrip(".")
    return best if len(best) <= limit else best[: limit - 1] + "…"


def pick(segments, count, min_len, max_len, use_ai=True, persona="", model=DEFAULT_MODEL, log=print) -> tuple[list[Clip], str]:
    if use_ai:
        try:
            return pick_with_claude(segments, count, min_len, max_len, persona, model), "claude"
        except HighlightError as e:
            log(f"  ⚠ {e} → 규칙 기반 선정으로 대신합니다")
    return pick_heuristic(segments, count, min_len, max_len), "heuristic"
