// 브라우저 음성인식 (Whisper, transformers.js)
// 서버나 API 키 없이 사용자의 브라우저에서 직접 돌아갑니다.
// 처음 한 번 모델(whisper-base 약 80MB)을 내려받고, 이후에는 브라우저 캐시를 씁니다.

const TRANSFORMERS_URL = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@3.5.1';
const SAMPLE_RATE = 16000;

const STT = (() => {
  let asrPromise = null;

  function load(onProgress) {
    if (asrPromise) return asrPromise;
    asrPromise = (async () => {
      const { pipeline } = await import(TRANSFORMERS_URL);
      const files = {};
      return pipeline('automatic-speech-recognition', (window.CLIPORA || {}).whisperModel || 'onnx-community/whisper-base', {
        dtype: 'q8',
        device: 'wasm',
        progress_callback: (p) => {
          if (p.status !== 'progress' || !p.total) return;
          files[p.file] = { loaded: p.loaded, total: p.total };
          const all = Object.values(files);
          onProgress?.(all.reduce((a, f) => a + f.loaded, 0) / all.reduce((a, f) => a + f.total, 0));
        },
      });
    })();
    asrPromise.catch(() => { asrPromise = null; }); // 실패하면 다음에 다시 시도
    return asrPromise;
  }

  // AudioBuffer의 [start, end] 구간을 Whisper 입력 형식(16kHz 모노)으로 바꿉니다.
  async function resample(buffer, start, end) {
    const len = Math.max(1, Math.ceil((end - start) * SAMPLE_RATE));
    const ctx = new OfflineAudioContext(1, len, SAMPLE_RATE);
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    src.start(0, start, end - start);
    return (await ctx.startRendering()).getChannelData(0);
  }

  // 반환: [{ start, end, text }] (원본 영상 기준 초)
  async function transcribe(buffer, start, end, onProgress) {
    const asr = await load(onProgress);
    const audio = await resample(buffer, start, end);
    const out = await asr(audio, {
      language: 'korean',
      task: 'transcribe',
      return_timestamps: true,
      chunk_length_s: 30,
      stride_length_s: 5,
    });
    const chunks = out.chunks && out.chunks.length ? out.chunks : [{ timestamp: [0, end - start], text: out.text || '' }];
    return chunks
      .map((c) => ({
        start: start + (c.timestamp[0] ?? 0),
        end: start + (c.timestamp[1] ?? end - start),
        text: (c.text || '').trim(),
      }))
      .filter((c) => c.text && c.end > c.start);
  }

  return { load, transcribe };
})();
