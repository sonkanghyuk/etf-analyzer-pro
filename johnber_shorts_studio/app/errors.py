"""사용자에게 보여줄 오류 코드와 한국어 안내."""
from __future__ import annotations

ERROR_MESSAGES: dict[str, tuple[str, bool]] = {
    # code: (안내 문구, 재시도 가능 여부)
    "FFMPEG_MISSING": ("FFmpeg를 찾을 수 없습니다. README의 'FFmpeg 설치'를 따라 설치하거나 .env의 JSS_FFMPEG에 ffmpeg.exe 경로를 지정하세요.", True),
    "MEDIA_INVALID": ("영상 파일을 읽을 수 없습니다. 손상되었거나 확장자만 MP4인 파일일 수 있습니다.", False),
    "MEDIA_NO_VIDEO": ("영상 트랙이 없는 파일입니다. 영상(MP4 등)을 선택하세요.", False),
    "MEDIA_TOO_LONG": ("허용 길이를 초과한 영상입니다. .env의 JSS_MAX_SOURCE_MINUTES로 한도를 바꿀 수 있습니다.", False),
    "UPLOAD_TOO_LARGE": ("허용 용량을 초과한 파일입니다. .env의 JSS_MAX_UPLOAD_GB로 한도를 바꿀 수 있습니다.", False),
    "DISK_FULL": ("디스크 공간이 부족합니다. 불필요한 파일을 정리한 뒤 다시 시도하세요.", True),
    "SUBTITLE_PARSE": ("자막 파일 형식을 해석하지 못했습니다.", False),
    "STT_NOT_INSTALLED": ("로컬 전사 엔진(faster-whisper)이 설치되지 않았습니다. 설치.cmd를 다시 실행하세요.", False),
    "STT_MODEL_MISSING": ("전사 모델을 불러오지 못했습니다. 인터넷 연결(Hugging Face) 또는 .env의 JSS_WHISPER_MODEL에 지정한 로컬 모델 폴더를 확인하세요.", True),
    "AI_NOT_CONFIGURED": ("AI 제공자가 연결되지 않았습니다. .env에 ANTHROPIC_API_KEY를 설정하세요. 수동 구간 지정은 계속 사용할 수 있습니다.", False),
    "AI_AUTH": ("API 키가 올바르지 않거나 권한이 없습니다. .env의 ANTHROPIC_API_KEY를 확인하세요.", False),
    "AI_RATE_LIMIT": ("API 사용 한도를 초과했습니다. 잠시 후 다시 시도하세요.", True),
    "AI_NETWORK": ("네트워크 연결에 실패했습니다. 인터넷 연결을 확인하고 다시 시도하세요.", True),
    "AI_BAD_RESPONSE": ("AI 응답이 형식에 맞지 않아 사용하지 않았습니다. 다시 시도하세요.", True),
    "AI_REFUSED": ("AI 제공자가 요청을 거절했습니다.", False),
    "AI_SERVER": ("AI 제공자 서버 오류입니다. 잠시 후 다시 시도하세요.", True),
    "RENDER_FAILED": ("영상 렌더링에 실패했습니다. 로그를 확인하세요.", True),
    "RENDER_INVALID_OUTPUT": ("렌더링 결과 파일 검사에 실패했습니다(빈 파일·미완성·음성 누락). 성공본으로 표시하지 않았습니다.", True),
    "TIMEOUT": ("작업 시간이 초과되었습니다.", True),
    "CANCELED": ("사용자가 작업을 취소했습니다.", True),
    "INTERRUPTED": ("서버가 재시작되어 작업이 중단되었습니다. 재시도할 수 있습니다.", True),
    "CLIP_EMPTY": ("남은 구간이 없습니다. 삭제한 구간을 확인하세요.", False),
    "BUILTIN_TEMPLATE": ("기본 템플릿은 수정·삭제할 수 없습니다. 복제한 뒤 수정하세요.", False),
    "NOT_FOUND": ("대상을 찾을 수 없습니다.", False),
    "INTERNAL": ("예상하지 못한 오류가 발생했습니다. 로그를 확인하세요.", True),
}


class StudioError(Exception):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        message, retryable = ERROR_MESSAGES.get(code, ERROR_MESSAGES["INTERNAL"])
        self.message = message
        self.retryable = retryable
        self.detail = detail
        super().__init__(f"{code}: {message}" + (f" ({detail})" if detail else ""))

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail, "retryable": self.retryable}
