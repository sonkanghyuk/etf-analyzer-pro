"""9:16으로 자를 때 화자 얼굴이 가운데 오도록 가로 위치를 정합니다 (OpenCV, 선택 설치).

클립 구간에서 프레임 몇 장을 뽑아 가장 큰 얼굴의 가로 중심을 찾고, 중앙값을 씁니다.
얼굴을 못 찾거나 OpenCV가 없으면 None → 가운데 자르기.
"""

from pathlib import Path


def face_center_x(video: Path, start: float, end: float, samples: int = 12) -> float | None:
    try:
        import cv2
    except ImportError:
        return None
    detector = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened() or detector.empty():
        return None
    centers = []
    try:
        for k in range(samples):
            t = start + (end - start) * (k + 0.5) / samples
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            scale = 640 / w if w > 640 else 1.0
            small = cv2.resize(frame, None, fx=scale, fy=scale) if scale != 1.0 else frame
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(30, 30))
            if len(faces):
                x, _, fw, _ = max(faces, key=lambda f: f[2] * f[3])
                centers.append((x + fw / 2) / small.shape[1])
    finally:
        cap.release()
    if len(centers) < max(2, samples // 4):  # 우연히 한두 번 잡힌 건 믿지 않습니다
        return None
    centers.sort()
    return centers[len(centers) // 2]
