"""YouTube 자동자막(VTT, 단어 타임스탬프 포함)을 정제한다.

출력 (입력 파일 옆에):
  <stem>.clean.srt      : 롤링 중복 제거한 1줄 자막 (YouTube 표시 단위)
  <stem>.transcript.txt : [mm:ss] 문장 단위 대본
  <stem>.words.json     : [{"t": 초, "w": "단어"}] 단어 타임라인

사용: python -I vtt_clean.py reference_videos/*.ko.vtt
"""
import html
import json
import re
import sys
from pathlib import Path

TS = r"(\d+):(\d\d):(\d\d)\.(\d{3})"


def sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse(path):
    text = html.unescape(Path(path).read_text(encoding="utf-8"))
    words = []  # (t, word)
    for block in text.split("\n\n"):
        lines = block.strip("\n").split("\n")
        if not lines or "-->" not in lines[0]:
            continue
        m = re.match(TS + r" --> " + TS, lines[0])
        start = sec(*m.groups()[:4])
        for ln in lines[1:]:
            if "<c>" not in ln and "<0" not in ln:
                continue
            # first word has cue start time, others inline
            first, *rest = re.split(r"(<\d+:\d\d:\d\d\.\d{3}>)", ln)
            first = re.sub(r"</?c>", "", first).strip()
            if first:
                words.append((start, first))
            cur = start
            for tok in rest:
                tm = re.match("<" + TS + ">", tok)
                if tm:
                    cur = sec(*tm.groups())
                    continue
                w = re.sub(r"</?c>", "", tok).strip()
                if w:
                    words.append((cur, w))
    return words


def caption_lines(path):
    """YouTube 화면에 실제로 뜨는 단위(= <c> 태그가 있던 한 줄)."""
    text = html.unescape(Path(path).read_text(encoding="utf-8"))
    out = []
    for block in text.split("\n\n"):
        lines = block.strip("\n").split("\n")
        if not lines or "-->" not in lines[0]:
            continue
        m = re.match(TS + r" --> " + TS, lines[0])
        s, e = sec(*m.groups()[:4]), sec(*m.groups()[4:])
        for ln in lines[1:]:
            if "<c>" in ln:
                out.append([s, e, re.sub(r"<[^>]+>", "", ln).strip()])
    # 다음 줄 시작까지 표시 시간 연장
    for i in range(len(out) - 1):
        out[i][1] = max(out[i][1], out[i + 1][0])
    return out


def fmt_srt(t):
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)):03d}"


def main():
    for p in sys.argv[1:]:
        p = Path(p)
        stem = p.name.split(".")[0]
        base = p.with_name(stem)
        words = parse(p)
        caps = caption_lines(p)
        with open(f"{base}.clean.srt", "w", encoding="utf-8") as f:
            for i, (s, e, t) in enumerate(caps, 1):
                f.write(f"{i}\n{fmt_srt(s)} --> {fmt_srt(e)}\n{t}\n\n")
        # sentence split on 다/요/죠/까 + punctuation
        sents, cur, t0 = [], [], None
        for t, w in words:
            if t0 is None:
                t0 = t
            cur.append(w)
            if re.search(r"[.?!]$", w):
                sents.append((t0, " ".join(cur)))
                cur, t0 = [], None
        if cur:
            sents.append((t0, " ".join(cur)))
        with open(f"{base}.transcript.txt", "w", encoding="utf-8") as f:
            for t, s in sents:
                f.write(f"[{int(t // 60):02d}:{int(t % 60):02d}] {s}\n")
        json.dump([{"t": round(t, 2), "w": w} for t, w in words],
                  open(f"{base}.words.json", "w", encoding="utf-8"), ensure_ascii=False)
        print(p.name, "words", len(words), "captions", len(caps), "sentences", len(sents))


if __name__ == "__main__":
    main()
