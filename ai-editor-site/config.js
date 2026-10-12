// 배포 설정. GitHub Pages 배포 시에는 워크플로가 저장소 변수로 이 파일을 다시 만듭니다.
// apiBase가 비어 있으면 로그인·결제·AI 제목 없이 브라우저만으로 동작하는 데모 모드입니다.
window.CLIPORA = {
  apiBase: '',          // 예: 'https://clipora-api.onrender.com'
  tossClientKey: '',    // 토스페이먼츠 클라이언트 키 (test_ck_...)
  whisperModel: 'onnx-community/whisper-base',
};
