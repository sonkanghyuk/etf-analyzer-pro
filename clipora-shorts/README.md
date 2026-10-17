# Clipora Shorts — 촬영본을 숏폼으로 (PC용)

강의·강연·인터뷰·웨비나 촬영본을 넣으면, AI가 끝까지 볼 만한 구간을 골라 **자막과 제목을 입힌 9:16 숏폼 MP4**를 여러 개 만들어 줍니다. 모든 처리는 내 PC에서 하고, 하이라이트 선정에만 Claude API를 씁니다.

```
강의.mp4 ─▶ 음성인식(Whisper) ─▶ 하이라이트·제목 선정(Claude) ─▶ 9:16 자르기(얼굴 위치) ─▶ 자막 입힌 MP4
```

결과 폴더:

```
강의_shorts/
├─ 01_10년 가르치며 깨달은 단 하나.mp4   ← 1080×1920, 자막·제목 포함, 음량 -14 LUFS
├─ 01_10년 가르치며 깨달은 단 하나.srt   ← 자막 파일 (플랫폼 자막 업로드용)
├─ 01_10년 가르치며 깨달은 단 하나.jpg   ← 썸네일
├─ 02_...
├─ 업로드정보.md    ← 제목, 원본 구간, 고른 이유, 해시태그
├─ clips.json      ← 전체 결과 (다른 프로그램에서 쓰기 좋게)
└─ transcript.json ← 음성인식 결과 (다시 실행하면 재사용)
```

## 가장 쉬운 방법 (Windows)

1. **내려받기** — https://github.com/sonkanghyuk/etf-analyzer-pro/archive/refs/heads/claude/ai-editing-site-i3emy1.zip
   압축을 풀고 안의 `clipora-shorts` 폴더를 원하는 곳(예: 바탕화면)에 둡니다.
2. **`설치하기.bat` 더블클릭** (처음 한 번만, 5~10분)
   Python·ffmpeg가 없으면 자동으로 설치하고, 마지막에 샘플 영상으로 숏폼을 만들어 잘 되는지 확인합니다.
   중간에 Claude API 키를 물어보면 붙여넣거나 그냥 Enter를 누르세요.
   "Windows의 PC 보호" 창이 뜨면 **추가 정보 → 실행**을 누르면 됩니다.
3. **`숏폼만들기.bat` 더블클릭** → 창이 뜨면 영상 파일을 고르고 **✨ 숏폼 만들기**.
   영상 파일을 `숏폼만들기.bat` 아이콘 위에 끌어다 놓아도 됩니다.
   다 되면 결과 폴더(`영상이름_shorts`)가 열립니다.

macOS는 같은 폴더의 `설치하기.command` → `숏폼만들기.command`를 더블클릭하세요(Homebrew 필요).

**Claude API 키**는 https://console.anthropic.com/settings/keys 에서 발급받아 프로그램 창의 "Claude API 키" 칸에 넣으면 이 PC에 저장됩니다. 키가 없어도 동작하지만, 있으면 Claude가 내용을 이해하고 하이라이트와 제목을 고릅니다.

## 직접 설치 (개발자용)

1. Python 3.10 이상, ffmpeg (`winget install Gyan.FFmpeg` / `brew install ffmpeg` / `sudo apt install ffmpeg`)
2. `pip install ".[face]"` (face = 얼굴 따라 자르기, OpenCV)
3. API 키: 환경 변수 `ANTHROPIC_API_KEY` 또는 창 화면에서 저장

## 명령어로 쓰기

```bash
clipora-shorts 강의.mp4                       # 기본: 5분당 1개, 20~60초, 블러 템플릿
clipora-shorts 강연.mov -n 5 --start 10:00 --end 40:00
clipora-shorts 인터뷰.mp4 -t talk --persona "20대 직장인 대상 커리어 채널"
clipora-shorts 강의.mp4 --plan-only           # 어떤 구간이 뽑히는지만 보기
clipora-shorts --demo                         # 샘플 영상으로 설치 확인
python -m clipora_shorts.gui                  # 창 화면
```

### 주요 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `-n, --count` | 만들 숏폼 개수 | 원본 5분당 1개 (최대 10) |
| `--min`, `--max` | 숏폼 길이(초) | 20, 60 |
| `--start`, `--end` | 분석할 구간 (`90`, `1:30`, `1:02:03`) | 전체 |
| `-t, --template` | `clean` `blur` `talk` `pop` `minimal` (`--list-templates`) | `blur` |
| `--reframe` | 꽉 채우는 템플릿에서 자를 위치: `face` / `center` | `face` |
| `--persona` | 채널 성격·타깃 — 선정 기준과 제목에 반영 | |
| `--no-ai` | Claude 없이 규칙 기반 선정 | |
| `--model` | Claude 모델 | `claude-opus-5-5` |
| `--whisper` | 음성인식 모델 `tiny` `base` `small` `medium` `large-v3` | `small` |
| `--device` | 음성인식 장치 `auto` `cpu` `cuda` | `auto` |
| `--transcript` | 이미 있는 transcript.json 사용 (음성인식 건너뜀) | |
| `--font`, `--fontsdir` | 자막 글꼴 이름 / 글꼴 파일 폴더 | OS 기본 한글 글꼴 |
| `--quality` | `fast` `normal` `high` | `normal` |
| `--no-loudnorm` | 음량 평준화 끄기 | |

### 템플릿

| id | 이름 | 화면 |
|---|---|---|
| `clean` | 강의 · 클린 | 검은 배경 가운데 원본, 위 제목, 아래 자막 |
| `blur` | 강연 · 블러 | 흐린 원본 배경, 핵심어 노란색 강조 |
| `talk` | 인터뷰 · 토크 | 화면 꽉 채움, 빨간 제목 띠, 박스 자막 |
| `pop` | 예능 · 팝 | 화면 꽉 채움, 굵은 테두리 노란 자막, 핑크 강조 |
| `minimal` | 미니멀 | 제목 없이 작은 자막만 |

세로로 찍은 영상은 어떤 템플릿이든 화면을 꽉 채우는 방식으로 처리합니다.

## 하이라이트는 어떻게 고르나요

- **Claude 모드** (API 키 있음): 타임스탬프가 붙은 자막 전체를 Claude에게 주고, "앞뒤 맥락 없이도 이해되는지, 첫 3초에 훅이 있는지, 공유하고 싶은 내용인지"를 기준으로 구간·제목·해시태그·고른 이유를 받습니다. 결과는 JSON 스키마로 강제하고, 프로그램이 다시 길이·겹침·문장 경계를 검사합니다. Claude가 응답을 거절하면 서버에서 다른 모델로 자동 재시도하도록 설정되어 있고, 그래도 실패하면 규칙 기반으로 넘어갑니다.
- **규칙 기반**: 말이 빽빽한 구간, 쉼 뒤에서 시작해 문장 끝에서 끝나는 구간을 고르고, 인사·진행 멘트·"앞에서 말씀드린"으로 시작하는 구간은 피합니다.

비용 참고: 1시간 강의 자막은 대략 2~3만 토큰이라, 한 번 선정에 드는 Claude 비용은 보통 수백 원 수준입니다(모델·자막 길이에 따라 다름). `--model`로 더 저렴한 모델을 지정할 수도 있습니다.

## 속도 참고

- 음성인식은 처음 실행할 때 Whisper 모델을 내려받습니다(`small` 약 500MB). 같은 영상을 다시 돌리면 `transcript.json`을 재사용해서 바로 넘어갑니다.
- CPU만 있어도 되지만, NVIDIA GPU가 있으면 `--device cuda`가 훨씬 빠릅니다. 빠르게 시험해 보려면 `--whisper base`.

## 개발

```bash
pip install ".[face,test]"
pytest tests
```

| 파일 | 역할 |
|---|---|
| `설치하기.bat`, `숏폼만들기.bat` (+ `.command`) | 원클릭 설치 · 실행 |
| `clipora_shorts/gui.py` | 창 화면 (tkinter) |
| `clipora_shorts/cli.py` | 명령행, 전체 흐름 |
| `config.py`, `sample.py` | API 키 저장, 설치 확인용 샘플 |
| `media.py` | ffprobe/ffmpeg 호출, 음성 추출 |
| `transcribe.py` | faster-whisper 음성인식 (단어 단위 타임스탬프) |
| `highlights.py` | Claude / 규칙 기반 하이라이트 선정과 검증 |
| `captions.py` | 화면용 자막 나누기, ASS·SRT 생성 |
| `reframe.py` | 얼굴 위치 찾기 (OpenCV) |
| `render.py` | 9:16 합성, 자막 입히기, 인코딩 |
| `templates.py` | 템플릿 정의 |
