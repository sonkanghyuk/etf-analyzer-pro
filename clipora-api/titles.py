"""숏폼 제목 생성 (Claude API)."""

import json
import os

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM = (
    "당신은 강의·강연·인터뷰 영상을 유튜브 쇼츠/인스타 릴스용 숏폼으로 만드는 한국어 카피라이터입니다. "
    "각 클립의 자막을 읽고 그 내용을 정확히 반영하는 제목을 하나씩 지으세요. "
    "제목은 22자 이내, 첫 화면에서 끝까지 보고 싶게 만드는 문장으로 쓰되 "
    "자막에 없는 사실이나 과장된 약속은 넣지 마세요. 이모지와 해시태그는 쓰지 않습니다."
)

SCHEMA = {
    "type": "object",
    "properties": {"titles": {"type": "array", "items": {"type": "string"}}},
    "required": ["titles"],
    "additionalProperties": False,
}

_client = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


class TitleError(Exception):
    pass


def generate_titles(transcripts: list[str], persona: str = "") -> list[str]:
    clips = "\n\n".join(f"[클립 {i + 1}]\n{t.strip() or '(자막 없음)'}" for i, t in enumerate(transcripts))
    prompt = f"클립 {len(transcripts)}개의 제목을 순서대로 지어 주세요.\n\n{clips}"
    if persona:
        prompt = f"채널 페르소나: {persona.strip()}\n\n" + prompt

    try:
        response = client().beta.messages.create(
            model=MODEL,
            max_tokens=2048,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError as e:
        raise TitleError("잠시 후 다시 시도해 주세요 (요청이 많아요)") from e
    except anthropic.APIStatusError as e:
        raise TitleError(f"제목 생성 실패 ({e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise TitleError("AI 서버에 연결하지 못했어요") from e

    if response.stop_reason == "refusal":
        raise TitleError("이 내용으로는 제목을 만들 수 없어요")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        titles = json.loads(text)["titles"]
    except (ValueError, KeyError) as e:
        raise TitleError("제목 응답을 해석하지 못했어요") from e

    titles = [str(t).strip()[:40] for t in titles]
    # 개수가 모자라면 빈 칸은 프론트가 자체 제목으로 채웁니다.
    return (titles + [""] * len(transcripts))[: len(transcripts)]
