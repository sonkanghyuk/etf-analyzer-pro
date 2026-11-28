# 레퍼런스 영상 분석 도구

[`docs/supetv_editing_bible.md`](../../docs/supetv_editing_bible.md)의 수치를 만든 스크립트들이다. 표준 라이브러리, Pillow, numpy, ffmpeg만 쓴다.

| 스크립트 | 하는 일 |
|---|---|
| `fetch_and_extract.py` | yt-dlp로 영상(720p 이하 mp4)·한국어 자막·메타데이터 받기 → ffmpeg 장면 전환 검출(`scenes.csv` + 전환 프레임) → N초 간격 대표 프레임. **내 PC에서 실행**(클라우드 IP는 YouTube가 막음) |
| `vtt_clean.py` | YouTube 자동자막 VTT → 롤링 중복 제거 SRT, 문장 단위 대본, 단어 타임라인 JSON |
| `script_stats.py` | 말 속도, 문장 길이, 어미 분포, 자막 청크 추정 |
| `storyboard_stats.py` | 일정 간격 프레임으로 화면 유형 비율, 화면 변화 빈도, 슬라이드 배경색 |
| `contact_sheet.py` | 타임스탬프 라벨을 붙인 5×4 컨택트시트 |
| `spec_preview.py` | 바이블 수치만으로 1920×1080 규격 프레임을 그림. `--overlay ref.jpg`로 레퍼런스와 겹쳐 정렬 검증 |

```bash
python tools/reference_analysis/fetch_and_extract.py               # 기본 레퍼런스 4편
python -I tools/reference_analysis/vtt_clean.py reference_videos/*.ko.vtt
python -I tools/reference_analysis/script_stats.py reference_videos
python -I tools/reference_analysis/spec_preview.py out.png --grid
```

결과물은 `reference_videos/`(git 제외)에 쌓이고, 요약 수치는 `docs/reference_analysis/`에 있다.
