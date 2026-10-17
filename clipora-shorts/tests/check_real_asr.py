"""CI용: 실제 한국어 음성 영상으로 음성인식(Whisper)부터 숏폼 MP4까지 전체 과정을 돌립니다.

사용: python tests/check_real_asr.py   (인터넷 필요 — Whisper 모델을 내려받음)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clipora_shorts import cli  # noqa: E402

here = Path(__file__).parent
out = here.parent / "asr_out"
code = cli.main([str(here / "fixtures" / "speech_ko.mp4"), "-o", str(out), "--whisper", "base",
                 "--no-ai", "--min", "8", "--max", "30", "--quality", "fast"])
data = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
texts = [s["text"] for s in data["segments"]]
sys.stdout.buffer.write(("인식된 문장 %d개: %s\n" % (len(texts), " / ".join(texts[:6]))).encode("utf-8"))
mp4s = list(out.glob("*.mp4"))
assert code == 0, f"exit code {code}"
assert texts, "음성인식 결과가 비어 있어요"
assert mp4s, "숏폼 MP4가 없어요"
assert any(s["words"] for s in data["segments"]), "단어 타임스탬프가 없어요"
print(f"OK: segments={len(texts)} shorts={len(mp4s)}")
