import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_DATA = Path(tempfile.mkdtemp(prefix="jss_test_"))
os.environ["JSS_DATA_DIR"] = str(_DATA / "data")
os.environ.pop("ANTHROPIC_API_KEY", None)  # 기본 테스트는 'API 키 없음' 상태에서 실행


@pytest.fixture(scope="session")
def media_dir() -> Path:
    d = _DATA / "media" / "공백 있는 한글 폴더"
    d.mkdir(parents=True, exist_ok=True)
    tool = ROOT / "tools" / "make_test_media.py"
    subprocess.run([sys.executable, str(tool), str(d), "--duration", "10", "--silence", "4-6", "--name", "sync test"], check=True)
    subprocess.run([sys.executable, str(tool), str(d), "--duration", "90", "--silence", "", "--name", "강의 샘플"], check=True)
    subprocess.run([sys.executable, str(tool), str(d), "--duration", "6", "--silence", "", "--name", "무음 입력", "--no-audio"], check=True)
    (d / "가짜.mp4").write_bytes(b"this is not a video" * 100)
    good = (d / "강의 샘플.mp4").read_bytes()
    (d / "손상.mp4").write_bytes(good[: len(good) // 3])
    return d


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def wait_job(client, job_id: str, timeout: float = 300) -> dict:
    import time

    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("succeeded", "failed", "canceled", "interrupted"):
            return j
        time.sleep(0.2)
    raise TimeoutError(job_id)
