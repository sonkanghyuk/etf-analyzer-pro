"""스토리보드(또는 일정 간격 프레임) 폴더로 편집 호흡·화면 유형·팔레트를 계산한다.

사용: python -I storyboard_stats.py reference_videos/frames/storyboard  > stats.json
- 프레임 파일명: sb_####_tMMmSSs.jpg, 같은 폴더의 meta.json(interval_s) 필요
- 유형 분류(휴리스틱): slide(밝은 종이 배경 + 상단 중앙 제목), treemap(녹/적 히트맵),
  dark_text(어두운 배경 + 큰 흰 글자), footage(그 외 실사/뉴스 영상)
- 변화 판정: 이전 프레임과 평균 절대차 > 18 → 화면 변화, 제목 띠(상단 15%)까지 바뀌면 '전환', 본문만 바뀌면 '빌드'
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def classify(a):
    h, w, _ = a.shape
    L = a.mean(2)
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) / np.maximum(mx, 1)
    top = L[: int(h * 0.15)]
    body = a[int(h * 0.18): int(h * 0.82)]
    g = ((body[..., 1] > body[..., 0] + 40) & (body[..., 1] > 90)).mean()
    r = ((body[..., 0] > body[..., 1] + 60) & (body[..., 0] > 110)).mean()
    corners = np.concatenate([L[15:40, 2:14].ravel(), L[15:40, w - 30:w - 18].ravel()])
    if g + r > 0.55:
        return "treemap"
    if corners.mean() > 185 and sat[15:40, 2:14].mean() < 0.12 and top.mean() > 170:
        return "slide"
    if L.mean() < 70 and (L[int(h * .3):int(h * .75)] > 200).mean() > 0.04:
        return "dark_text"
    return "footage"


def main():
    root = Path(sys.argv[1])
    meta = json.loads((root / "meta.json").read_text())
    out = {}
    for vid, m in meta.items():
        files = sorted((root / vid).glob("sb_*.jpg"))
        arr = [np.asarray(Image.open(p).convert("RGB")).astype(float) for p in files]
        types = [classify(a) for a in arr]
        changes, builds = [], []
        for i in range(1, len(arr)):
            d = np.abs(arr[i] - arr[i - 1]).mean()
            dt = np.abs(arr[i][:14] - arr[i - 1][:14]).mean()  # 제목 띠
            t = float(re.search(r"sb_(\d+)", files[i].name).group(1)) * m["interval_s"]
            if d > 18 or dt > 25:
                (changes if (dt > 25 or types[i] != types[i - 1]) else builds).append(round(t, 1))
        # 같은 화면 지속 시간(구간 길이) — 샘플 간격 해상도
        events = sorted(changes + builds)
        segs = np.diff([0] + events + [m["duration"]])
        tc = {k: types.count(k) for k in set(types)}
        # 슬라이드 배경색 (밝은 모서리 픽셀)
        slide_bg = [a[15:40, 2:14].reshape(-1, 3).mean(0) for a, t in zip(arr, types) if t == "slide"]
        out[vid] = {
            "interval_s": round(m["interval_s"], 2),
            "frames": len(arr),
            "type_ratio": {k: round(v / len(arr), 3) for k, v in sorted(tc.items())},
            "screen_changes(full)": len(changes),
            "screen_builds(partial)": len(builds),
            "events_per_min": round(len(events) / (m["duration"] / 60), 2),
            "median_hold_s": round(float(np.median(segs)), 1),
            "mean_hold_s": round(float(np.mean(segs)), 1),
            "slide_bg_rgb": [int(v) for v in np.mean(slide_bg, 0)] if slide_bg else None,
            "timeline": [[round(i * m["interval_s"]), t] for i, t in enumerate(types)],
        }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
