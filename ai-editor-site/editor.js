// 숏폼 에디터
// - 발화 구간 감지와 하이라이트 선별은 Web Audio로 브라우저에서 실제 계산합니다
//   (말이 끊김 없이 이어지는 비율 60% + 목소리 에너지 40%로 점수화).
// - 자막 "텍스트"와 제목은 음성인식(STT)/LLM 서버가 필요하므로 데모 문장으로 채웁니다.
//   실서비스에서는 transcribe()와 suggestTitle()을 API 호출로 바꾸면 됩니다.
// - 내보내기는 템플릿을 입힌 9:16 캔버스를 MediaRecorder로 녹화해 실제 WebM 파일을 만듭니다.

const $ = (id) => document.getElementById(id);
const video = $('video');
const preview = $('preview');
const pctx = preview.getContext('2d');
const STEP = 0.1; // 오디오 분석 단위(초)

const DEMO_LINES = [
  '여러분 이거 하나만 기억하시면 됩니다', '대부분 여기서 실수를 하세요', '생각보다 정말 간단한 방법이에요',
  '제가 10년 동안 해 보고 깨달은 건', '결국 중요한 건 꾸준함입니다', '이 질문을 정말 많이 받는데요',
  '핵심은 딱 세 가지예요', '처음엔 저도 몰랐어요', '이렇게 하면 시간이 절반으로 줄어요', '오늘 이것만 가져가셔도 충분합니다',
];
const DEMO_TITLES = [
  '이거 모르면 계속 손해 봅니다', '10년 차가 알려주는 진짜 핵심', '다들 여기서 실수합니다',
  '딱 3가지만 기억하세요', '질문 1위, 드디어 답합니다', '이 한 마디에 다 담겨 있어요',
];

let fileName = '';
let audioBuffer = null;
let rms = null;
let clips = [];
let sel = -1;
let tpl = getTemplate(new URLSearchParams(location.search).get('template') || Store.template());
let clipPlaying = false;
let exporting = null;

// 미리보기·녹화가 원본 소리를 받도록 오디오 경로를 한 번만 연결합니다.
let actx, audioDest;
function ensureAudioGraph() {
  if (actx) { actx.resume(); return; }
  try {
    actx = new (window.AudioContext || window.webkitAudioContext)();
    const src = actx.createMediaElementSource(video);
    audioDest = actx.createMediaStreamDestination();
    src.connect(actx.destination);
    src.connect(audioDest);
  } catch (_) { actx = null; }
}

const fmt = (t) => {
  t = Math.max(0, t || 0);
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
};
const parseTime = (s) => {
  const parts = String(s).trim().split(':').map(Number);
  if (parts.some(isNaN)) return NaN;
  return parts.reduce((a, b) => a * 60 + b, 0);
};
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ---------- 시작 ----------
$('tpl').innerHTML = TEMPLATES.map((t) => `<option value="${t.id}">${t.name}</option>`).join('');
$('tpl').value = tpl.id;
$('tpl').addEventListener('change', () => { tpl = getTemplate($('tpl').value); Store.template(tpl.id); });

const link = new URLSearchParams(location.search).get('link');
if (link) {
  $('linkNotice').hidden = false;
  $('linkNotice').textContent = `🔗 ${link} — 링크로 가져오기는 서버 연동이 필요해요. 데모에서는 영상 파일을 직접 올려 주세요.`;
}

function renderUsage() {
  const used = Math.ceil(Store.usedSec() / 60);
  $('usage').textContent = `무료 시간 ${Math.max(0, FREE_MINUTES - used)}분 남음`;
}
renderUsage();

// ---------- 파일 ----------
function loadFile(file) {
  if (!file || !file.type.startsWith('video/')) { toast('영상 파일만 올릴 수 있어요'); return; }
  ensureAudioGraph();
  fileName = file.name;
  video.src = URL.createObjectURL(file);
  video.hidden = false;
  $('empty').hidden = true;
  $('linkNotice').hidden = true;
  audioBuffer = null; rms = null; clips = []; sel = -1;
  renderClips(); selectClip(-1);
  decodeAudio(file);
}

async function decodeAudio(file) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    audioBuffer = await ctx.decodeAudioData(await file.arrayBuffer());
    ctx.close();
  } catch (_) { audioBuffer = null; }
}

$('file').addEventListener('change', (e) => loadFile(e.target.files[0]));
['dragenter', 'dragover'].forEach((t) => $('stage').addEventListener(t, (e) => e.preventDefault()));
$('stage').addEventListener('drop', (e) => { e.preventDefault(); loadFile(e.dataTransfer.files[0]); });

video.addEventListener('loadedmetadata', () => {
  $('rStart').value = fmt(0);
  $('rEnd').value = fmt(video.duration);
  renderTimeline();
});

$('setStart').addEventListener('click', () => { $('rStart').value = fmt(video.currentTime); renderTimeline(); });
$('setEnd').addEventListener('click', () => { $('rEnd').value = fmt(video.currentTime); renderTimeline(); });
['rStart', 'rEnd'].forEach((id) => $(id).addEventListener('change', renderTimeline));

function getRange() {
  const dur = video.duration || 0;
  let s = parseTime($('rStart').value), e = parseTime($('rEnd').value);
  if (isNaN(s)) s = 0;
  if (isNaN(e) || e <= 0) e = dur;
  s = clamp(s, 0, dur); e = clamp(e, 0, dur);
  return { start: Math.min(s, e), end: Math.max(s, e) };
}

// ---------- 오디오 분석 ----------
function computeRms() {
  if (rms) return rms;
  if (!audioBuffer) {
    // 소리가 없거나 디코딩 불가: 3초 말하고 0.6초 쉬는 패턴으로 가정
    const n = Math.ceil(video.duration / STEP);
    rms = Float32Array.from({ length: n }, (_, i) => ((i * STEP) % 3.6 < 3 ? 0.2 : 0));
    return rms;
  }
  const data = audioBuffer.getChannelData(0);
  const win = Math.floor(audioBuffer.sampleRate * STEP);
  rms = new Float32Array(Math.ceil(data.length / win));
  for (let k = 0; k < rms.length; k++) {
    let sum = 0;
    const s = k * win, e = Math.min(s + win, data.length);
    for (let j = s; j < e; j++) sum += data[j] * data[j];
    rms[k] = Math.sqrt(sum / Math.max(1, e - s));
  }
  return rms;
}

// 발화 구간: 0.5초 이상 조용하면 문장이 끝난 것으로 봅니다.
function detectSpeech(start, end) {
  const r = computeRms();
  const i0 = Math.floor(start / STEP), i1 = Math.min(r.length, Math.ceil(end / STEP));
  const slice = Array.from(r.slice(i0, i1)).sort((a, b) => a - b);
  const threshold = Math.max(0.01, (slice[Math.floor(slice.length * 0.2)] || 0) * 2.5);
  const segs = [];
  let s = null, quiet = 0;
  for (let i = i0; i < i1; i++) {
    if (r[i] > threshold) { if (s === null) s = i; quiet = 0; }
    else if (s !== null && ++quiet >= 5) { segs.push({ start: s * STEP, end: (i - 4) * STEP }); s = null; quiet = 0; }
  }
  if (s !== null) segs.push({ start: s * STEP, end: i1 * STEP });
  return { segs: segs.filter((x) => x.end - x.start > 0.3), threshold };
}

function pickHighlights(start, end) {
  const r = computeRms();
  const { segs, threshold } = detectSpeech(start, end);
  const dur = end - start;
  const L = clamp(dur / 3, 3, 45);
  const N = Math.min(10, Math.max(1, Math.round(dur / 300), Math.min(3, Math.floor(dur / (L * 1.2)))));

  // 누적합으로 구간별 발화 비율·평균 에너지를 빠르게 계산
  const i0 = Math.floor(start / STEP), i1 = Math.min(r.length, Math.ceil(end / STEP));
  const speechPre = [0], energyPre = [0];
  let maxE = 1e-6;
  for (let i = i0; i < i1; i++) {
    speechPre.push(speechPre[speechPre.length - 1] + (r[i] > threshold ? 1 : 0));
    energyPre.push(energyPre[energyPre.length - 1] + r[i]);
    maxE = Math.max(maxE, r[i]);
  }
  const w = Math.round(L / STEP);
  const cands = [];
  for (let k = 0; k + w <= i1 - i0; k += 5) {
    const speechRatio = (speechPre[k + w] - speechPre[k]) / w;
    const energy = (energyPre[k + w] - energyPre[k]) / w / maxE;
    cands.push({ start: start + k * STEP, score: 0.6 * speechRatio + 0.4 * energy });
  }
  cands.sort((a, b) => b.score - a.score);

  const picked = [];
  for (const c of cands) {
    if (picked.length >= N) break;
    // 문장 중간에서 시작/끝나지 않도록 가까운 발화 경계에 맞춥니다.
    const near = segs.find((s) => Math.abs(s.start - c.start) <= 2);
    const s = clamp(near ? Math.max(start, near.start - 0.2) : c.start, start, end - 1);
    let e = s + L;
    const endSeg = segs.find((x) => Math.abs(x.end - e) <= 2);
    e = clamp(endSeg ? endSeg.end + 0.3 : e, s + 1, end);
    if (picked.every((p) => e + 0.5 <= p.start || s >= p.end + 0.5)) picked.push({ start: s, end: e, raw: c.score });
  }
  return { clips: picked.sort((a, b) => a.start - b.start), segs };
}

function transcribe(clip, segs, offset) {
  const caps = [];
  segs.forEach((s) => {
    const a = Math.max(s.start, clip.start), b = Math.min(s.end, clip.end);
    for (let t = a; t < b - 0.2; t += 3) caps.push({ start: t, end: Math.min(t + 3, b), text: '' });
  });
  if (!caps.length) caps.push({ start: clip.start, end: clip.end, text: '' });
  caps.forEach((c, i) => { c.text = DEMO_LINES[(offset + i) % DEMO_LINES.length]; });
  return caps;
}
const suggestTitle = (i) => DEMO_TITLES[i % DEMO_TITLES.length];

// ---------- AI 숏폼 만들기 ----------
async function progress(steps) {
  $('progress').classList.add('show');
  for (let i = 0; i < steps.length; i++) {
    $('progressText').textContent = `🤖 ${steps[i]}…`;
    $('progressBar').style.width = ((i + 1) / steps.length) * 100 + '%';
    await new Promise((r) => setTimeout(r, 450));
  }
  $('progress').classList.remove('show');
}

$('make').addEventListener('click', async () => {
  if (!video.duration) { toast('먼저 촬영본을 올려 주세요'); return; }
  const { start, end } = getRange();
  if (end - start < 3) { toast('구간을 3초 이상으로 지정해 주세요'); return; }
  if (Store.usedSec() + (end - start) > FREE_MINUTES * 60) {
    toast('무료 시간이 부족해요. 구간을 줄이거나 플랜을 업그레이드해 주세요'); return;
  }
  if (!audioBuffer && !rms) await new Promise((r) => setTimeout(r, 300)); // 디코딩 대기 여유
  $('make').disabled = true;
  await progress(['음성 분석', '하이라이트 탐색', '자막 생성', '템플릿 적용']);
  const { clips: found, segs } = pickHighlights(start, end);
  let offset = 0;
  clips = found.map((c, i) => {
    const captions = transcribe(c, segs, offset);
    offset += captions.length;
    return { ...c, score: Math.min(99, Math.round(55 + 44 * c.raw)), title: suggestTitle(i), captions };
  });
  Store.addUsed(end - start);
  renderUsage();
  $('make').disabled = false;
  renderClips();
  selectClip(0);
  toast(`하이라이트 ${clips.length}개를 찾았어요 (자막·제목은 데모 문장)`);
});

// ---------- 클립 목록 / 선택 ----------
function renderClips() {
  if (!clips.length) {
    $('clips').innerHTML = '<p style="color: var(--muted); font-size: 14px;">촬영본을 올리고 구간을 지정한 뒤 "AI 숏폼 만들기"를 눌러 보세요.</p>';
  } else {
    $('clips').innerHTML = clips.map((c, i) => `
      <button class="clip-card ${i === sel ? 'sel' : ''}" data-clip="${i}">
        <span class="score">AI ${c.score}점</span>
        <b>${c.title.replace(/</g, '&lt;')}</b>
        <span>${fmt(c.start)} – ${fmt(c.end)} · ${Math.round(c.end - c.start)}초</span>
      </button>`).join('');
  }
  renderTimeline();
}

function selectClip(i) {
  sel = i;
  const c = clips[i];
  $('clipTitle').disabled = !c;
  $('clipTitle').value = c ? c.title : '';
  $('caps').innerHTML = c ? c.captions.map((cap, k) => `
    <div class="cap" data-k="${k}"><time data-seek="${cap.start}">${fmt(cap.start)}</time><input value="${cap.text.replace(/"/g, '&quot;')}" data-cap="${k}" /></div>`).join('')
    : '<span style="font-size: 13px;">하이라이트를 선택하면 자막을 수정할 수 있어요.</span>';
  if (c) video.currentTime = c.start;
  document.querySelectorAll('.clip-card').forEach((el) => el.classList.toggle('sel', +el.dataset.clip === i));
  renderTimeline();
}

$('clips').addEventListener('click', (e) => {
  const b = e.target.closest('[data-clip]');
  if (b && !exporting) { stopClip(); selectClip(+b.dataset.clip); }
});
$('clipTitle').addEventListener('input', () => {
  if (!clips[sel]) return;
  clips[sel].title = $('clipTitle').value;
  const card = document.querySelector(`[data-clip="${sel}"] b`);
  if (card) card.textContent = clips[sel].title;
});
$('caps').addEventListener('input', (e) => { if (e.target.dataset.cap) clips[sel].captions[+e.target.dataset.cap].text = e.target.value; });
$('caps').addEventListener('click', (e) => { if (e.target.dataset.seek) video.currentTime = +e.target.dataset.seek; });

// ---------- 재생 ----------
function playClip() {
  const c = clips[sel];
  if (!c) { toast('하이라이트를 먼저 선택하세요'); return; }
  ensureAudioGraph();
  if (video.currentTime < c.start || video.currentTime >= c.end - 0.1) video.currentTime = c.start;
  clipPlaying = true;
  $('playClip').textContent = '❚❚ 일시정지';
  video.play();
}
function stopClip() {
  clipPlaying = false;
  $('playClip').textContent = '▶ 클립 재생';
  if (!exporting) video.pause();
}
$('playClip').addEventListener('click', () => (clipPlaying ? stopClip() : playClip()));
video.addEventListener('pause', () => { if (clipPlaying && !exporting) stopClip(); });

// ---------- 타임라인 ----------
function renderTimeline() {
  const dur = video.duration || 1;
  const pct = (t) => (t / dur) * 100 + '%';
  const r = video.duration ? getRange() : { start: 0, end: 0 };
  $('timeline').innerHTML =
    (video.duration ? `<div class="range" style="left:${pct(r.start)};width:${pct(r.end - r.start)}"></div>` : '') +
    clips.map((c, i) => `<div class="clip ${i === sel ? 'sel' : ''}" style="left:${pct(c.start)};width:${pct(c.end - c.start)}"></div>`).join('') +
    `<div class="head" id="head" style="left:${pct(video.currentTime || 0)}"></div>`;
}
$('timeline').addEventListener('click', (e) => {
  if (!video.duration || exporting) return;
  const r = e.currentTarget.getBoundingClientRect();
  video.currentTime = ((e.clientX - r.left) / r.width) * video.duration;
});

// ---------- 렌더 루프 ----------
const exportCanvas = document.createElement('canvas');
exportCanvas.width = 720; exportCanvas.height = 1280;
const ectx = exportCanvas.getContext('2d');

function currentCaption(t) {
  const c = clips[sel];
  if (!c || t < c.start || t > c.end) return '';
  const cap = c.captions.find((x) => t >= x.start && t <= x.end);
  return cap ? cap.text : '';
}

function frame() {
  const t = video.currentTime;
  const c = clips[sel];
  if (c && (clipPlaying || exporting) && t >= c.end) {
    if (exporting) exporting.finish();
    else { stopClip(); video.currentTime = c.start; }
  }
  const opts = {
    source: video.readyState >= 2 ? video : null,
    tpl, title: c ? c.title : '하이라이트를 선택하세요', caption: currentCaption(t), watermark: true,
  };
  renderFrame(pctx, 540, 960, opts);
  if (exporting) {
    renderFrame(ectx, 720, 1280, opts);
    const p = c ? (t - c.start) / (c.end - c.start) : 0;
    $('progressBar').style.width = clamp(p, 0, 1) * 100 + '%';
    $('progressText').textContent = `🎞️ 숏폼 렌더링 중… ${Math.round(clamp(p, 0, 1) * 100)}%`;
  }
  const head = $('head');
  if (head && video.duration) head.style.left = (t / video.duration) * 100 + '%';
  document.querySelectorAll('.cap').forEach((el) => {
    const cap = c && c.captions[+el.dataset.k];
    el.classList.toggle('active', !!cap && t >= cap.start && t <= cap.end);
  });
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

// ---------- 내보내기 ----------
function pickMime() {
  const list = ['video/webm;codecs=vp9,opus', 'video/webm;codecs=vp8,opus', 'video/webm', 'video/mp4'];
  return list.find((m) => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
}

$('export').addEventListener('click', async () => {
  const c = clips[sel];
  if (!c) { toast('내보낼 하이라이트를 선택하세요'); return; }
  if (exporting) return;
  if (!window.MediaRecorder || !exportCanvas.captureStream) { toast('이 브라우저는 영상 내보내기를 지원하지 않아요 (Chrome 권장)'); return; }
  ensureAudioGraph();

  const stream = exportCanvas.captureStream(30);
  if (audioDest) audioDest.stream.getAudioTracks().forEach((tr) => stream.addTrack(tr));
  const mime = pickMime();
  const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 4_000_000 } : undefined);
  const chunks = [];
  rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);

  clipPlaying = false;
  video.pause();
  video.currentTime = c.start;
  await new Promise((r) => video.addEventListener('seeked', r, { once: true }));
  renderFrame(ectx, 720, 1280, { source: video, tpl, title: c.title, caption: currentCaption(c.start), watermark: true });
  const thumbCanvas = document.createElement('canvas');
  thumbCanvas.width = 270; thumbCanvas.height = 480;
  thumbCanvas.getContext('2d').drawImage(exportCanvas, 0, 0, 270, 480);
  const thumb = thumbCanvas.toDataURL('image/jpeg', 0.75);

  document.querySelectorAll('#make, #export, #playClip').forEach((b) => { b.disabled = true; });
  $('progress').classList.add('show');

  const done = new Promise((resolve) => { rec.onstop = resolve; });
  exporting = {
    finish() {
      if (rec.state !== 'inactive') rec.stop();
      video.pause();
    },
  };
  rec.start(250);
  try { await video.play(); } catch (_) { exporting.finish(); }
  await done;
  exporting = null;
  $('progress').classList.remove('show');
  document.querySelectorAll('#make, #export, #playClip').forEach((b) => { b.disabled = false; });

  const blob = new Blob(chunks, { type: (mime || 'video/webm').split(';')[0] });
  if (!blob.size) { toast('렌더링에 실패했어요. 다시 시도해 주세요'); return; }
  await Store.add({
    id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
    title: c.title, templateId: tpl.id, sourceName: fileName,
    start: c.start, end: c.end, duration: c.end - c.start, score: c.score,
    createdAt: Date.now(), blob, thumb,
  });
  toast('숏폼을 저장했어요 → 내 콘텐츠');
  setTimeout(() => { if (confirm('숏폼이 저장됐어요. 내 콘텐츠로 이동할까요?')) location.href = 'contents.html'; }, 400);
});
