"""정제된 대본(words.json, transcript.txt)으로 말투·속도·문장 길이 통계를 낸다.

사용: python -I script_stats.py reference_videos
"""
import collections
import json
import re
import sys
from pathlib import Path

ENDINGS = [("~죠/~죠?", r"죠[.?]?$"), ("~는데요/~인데요", r"데요[.?]?$"), ("~습니다/~ㅂ니다", r"니다[.?]?$"),
           ("~고요", r"고요[.?]?$"), ("~요(기타)", r"요[.?]?$"), ("~까요?", r"까요?\??$"), ("~다(평서)", r"다[.]?$")]


def main():
    root = Path(sys.argv[1])
    out = {}
    for wf in sorted(root.glob("*.words.json")):
        stem = wf.name.split(".")[0]
        words = json.loads(wf.read_text(encoding="utf-8"))
        sents = [l.split("] ", 1)[1].strip() for l in (root / f"{stem}.transcript.txt").read_text(encoding="utf-8").splitlines() if "] " in l]
        chars = sum(len(w["w"].replace(" ", "")) for w in words)
        dur = words[-1]["t"] - words[0]["t"]
        lens = sorted(len(s.replace(" ", "")) for s in sents)
        eoj = sorted(len(s.split()) for s in sents)
        end = collections.Counter()
        for s in sents:
            for name, rx in ENDINGS:
                if re.search(rx, s):
                    end[name] += 1
                    break
            else:
                end["기타"] += 1
        nums = sum(len(re.findall(r"\d[\d,.]*\s*(%|달러|원|억|조|배|주|bp|포인트)", s)) for s in sents)
        # 번인 자막 청크 추정: 어절 경계에서 24자(공백 포함) 이하로 자르기
        chunks = []
        for s in sents:
            cur = ""
            for w in s.split():
                if cur and len(cur) + 1 + len(w) > 24:
                    chunks.append(cur)
                    cur = w
                else:
                    cur = f"{cur} {w}".strip()
            if cur:
                chunks.append(cur)
        cl = sorted(len(c) for c in chunks)
        out[stem] = {
            "duration_s": round(dur), "sentences": len(sents),
            "syllables_per_min": round(chars / dur * 60), "chars_per_sec": round(chars / dur, 2),
            "sentence_chars(no space) median/mean/p90": [lens[len(lens) // 2], round(sum(lens) / len(lens), 1), lens[int(len(lens) * .9)]],
            "sentence_eojeol median/mean": [eoj[len(eoj) // 2], round(sum(eoj) / len(eoj), 1)],
            "sec_per_sentence": round(dur / len(sents), 2),
            "endings_%": {k: round(v / len(sents) * 100, 1) for k, v in end.most_common()},
            "question_%": round(sum(s.endswith("?") for s in sents) / len(sents) * 100, 1),
            "numbers_per_min": round(nums / dur * 60, 1),
            "est_subtitle_chunks": len(chunks),
            "est_chunk_len(with space) median/mean": [cl[len(cl) // 2], round(sum(cl) / len(cl), 1)],
            "est_sec_per_chunk": round(dur / len(chunks), 2),
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
