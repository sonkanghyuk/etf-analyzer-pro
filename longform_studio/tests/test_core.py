"""자막 규칙(바이블 §6)·계획서 파서·무음 시간 매핑 단위 테스트."""
from pathlib import Path

import pytest

from longform_studio import media, plan, subtitles
from longform_studio.subtitles import clean_text, make_cues, split_sentence


def chunks(s: str) -> list[str]:
    t = s.split()
    return [clean_text(" ".join(t[i:j])) for i, j in split_sentence(t)]


@pytest.mark.parametrize("sentence", [
    "다우존스는 이번주 2.1% 상승했고 S&P 500은 2.6% 올랐습니다.",
    "두 기업이 하나가 되면 현재 기준으로 시총은 3조 4천억 달러가 됩니다.",
    "엔비디아의 경쟁사를 보면 AI GPU를 직접 만들고 있는 AMD, 맞춤형 AI 칩을 만들고 있는 브로드컴, 자체 칩을 보유하고 있는 구글과 아마존이 있습니다.",
])
def test_chunks_fit_and_keep_units(sentence):
    out = chunks(sentence)
    assert all(len(c) <= 25 for c in out)
    joined = " / ".join(out)
    for bad in ("S&P / 500", "3조 / 4천억", "4천억 / 달러", "보유하고 / 있는", "2.1% / 상승"):
        assert bad not in joined


def test_reference_example_matches_supetv_split():
    # 레퍼런스 실측 자막: "공개되는 대로 바로 영상으로 만들어드릴 테니까" (25자)
    assert chunks("공개되는 대로 바로 영상으로 만들어드릴 테니까 구독과 좋아요 부탁드립니다.")[0] == \
        "공개되는 대로 바로 영상으로 만들어드릴 테니까"


def test_prefers_connective_endings():
    assert chunks("이번주는 매매 버튼을 잘못 누르면 큰일나는 한주였죠.") == ["이번주는 매매 버튼을 잘못 누르면", "큰일나는 한주였죠"]


def test_short_sentence_single_chunk_no_period():
    assert chunks("감사합니다.") == ["감사합니다"]
    assert chunks("어떤 투자가 나와 결이 맞다고 생각하시나요?") == ["어떤 투자가 나와 결이 맞다고 생각하시나요?"]


def test_cue_timing_contiguous_and_min_duration():
    words = [{"s": 0.0, "e": 0.4, "w": "오늘은"}, {"s": 0.45, "e": 0.9, "w": "시장이"}, {"s": 0.95, "e": 1.4, "w": "올랐습니다."},
             {"s": 3.0, "e": 3.4, "w": "그런데"}, {"s": 3.45, "e": 3.9, "w": "환율은"}, {"s": 3.95, "e": 4.5, "w": "내렸죠."}]
    cues = make_cues([words[:3], words[3:]])
    assert [c["text"] for c in cues] == ["오늘은 시장이 올랐습니다", "그런데 환율은 내렸죠"]
    assert cues[0]["e"] == pytest.approx(1.7)          # 쉼이 길면 끝 + 0.3초
    assert all(c["e"] - c["s"] >= 0.8 for c in cues)


def test_ass_has_fixed_bar_and_text(tmp_path):
    subtitles.write_ass([{"s": 1.0, "e": 2.5, "text": "테스트 자막"}], tmp_path / "a.ass")
    s = (tmp_path / "a.ass").read_text(encoding="utf-8")
    assert "Style: Sub,NanumSquare,62," in s and "&H4A000000" in s
    assert "\\pos(280,950)\\p1}m 10 0 l 1348 0" in s and "\\pos(958,992)}테스트 자막" in s


def test_plan_parse(tmp_path: Path):
    (tmp_path / "plan.md").write_text('---\nsource: a.mp4\n---\n## 시황\n::: rings at=00:05 data="다우:+1|S&P500:-2" cues=00:06,7.5\n'
                                      '<!-- ::: vbar at=1 -->\n## 이슈\n::: video at=00:12\n', encoding="utf-8")
    p = plan.load(tmp_path)
    assert [s["kind"] for s in p["scenes"]] == ["video", "rings", "video"]
    assert p["scenes"][1]["cues"] == [6.0, 7.5] and p["scenes"][1]["params"]["data"] == "다우:+1|S&P500:-2"
    assert plan.chapters(p["scenes"]) == [(0.0, "시황"), (12.0, "이슈")]


def test_plan_rejects_unknown_template(tmp_path: Path):
    (tmp_path / "plan.md").write_text("::: nope at=1\n", encoding="utf-8")
    with pytest.raises(KeyError):
        plan.load(tmp_path)


def test_trim_time_mapping():
    keep = media.keep_ranges(20.0, [(5.0, 8.0), (12.0, 12.4)])  # 0.4초 쉼은 너무 짧아 유지
    assert keep == [(0.0, 5.125), (7.875, 20.0)]
    assert media.map_time(3.0, keep) == pytest.approx(3.0)
    assert media.map_time(9.0, keep) == pytest.approx(5.125 + 1.125)
