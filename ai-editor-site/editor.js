// 에디터 데모
// - 무음 구간 감지(AI 컷편집)와 발화 구간 분할은 Web Audio로 브라우저에서 실제 계산합니다.
// - 자막 "텍스트"는 음성인식(STT) 서버가 필요하므로 데모 문장으로 채웁니다.
//   실서비스에서는 transcribe()를 Whisper 등 STT API 호출로 바꾸면 됩니다.

const $ = (id) => document.getElementById(id);
const video = $('video');
const stage = $('stage');
const caption = $('caption');
const FREE_MINUTES = 30;

let subs = [];      // { start, end, text }
let cuts = [];      // { start, end } — 재생 시 건너뛸 무음 구간
let speech = null;  // 발화 구간 캐시
let audioBuffer = null;
let fileName = 'video';
let usedSec = 0;

const DEMO_LINES = [
  '안녕하세요 여러분, 오늘도 영상 찾아와 주셔서 감사합니다',
  '오늘은 정말 유용한 꿀팁을 준비해 봤는데요',
  '바로 본론으로 들어가 보겠습니다',
  '첫 번째는 생각보다 정말 간단해요',
  '이 부분은 꼭 기억해 두시면 좋겠어요',
  '두 번째 방법은 조금 더 응용된 버전입니다',
  '여기서 많은 분들이 실수를 하시는데요',
  '이렇게만 하면 시간을 절반으로 줄일 수 있어요',
  '마지막으로 정리해 보면',
  '영상이 도움이 되셨다면 구독과 좋아요 부탁드려요',
];

const fmt = (t, srt = false) => {
  const h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = Math.floor(t % 60);
  const ms = Math.floor((t % 1) * 1000);
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return srt ? `${p(h)}:${p(m)}:${p(s)},${p(ms, 3)}` : `${p(m)}:${p(s)}.${Math.floor(ms / 100)}`;
};

// ---------- 파일 로드 ----------
function loadFile(file) {
  if (!file || !file.type.startsWith('video/')) { toast('영상 파일만 올릴 수 있어요'); return; }
  fileName = file.name.replace(/\.[^.]+$/, '');
  video.src = URL.createObjectURL(file);
  video.hidden = false;
  $('empty').hidden = true;
  subs = []; cuts = []; speech = null; audioBuffer = null;
  renderSubs(); renderTimeline();
  decodeAudio(file);
}

async function decodeAudio(file) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    audioBuffer = await ctx.decodeAudioData(await file.arrayBuffer());
    ctx.close();
  } catch (_) {
    audioBuffer = null; // 오디오 트랙이 없거나 디코딩 불가 → 균등 분할로 대체
  }
}

$('file').addEventListener('change', (e) => loadFile(e.target.files[0]));
['dragenter', 'dragover'].forEach((t) => stage.addEventListener(t, (e) => e.preventDefault()));
stage.addEventListener('drop', (e) => { e.preventDefault(); loadFile(e.dataTransfer.files[0]); });

// ---------- 오디오 분석 ----------
// 100ms 단위 RMS로 발화/무음 구간을 나눕니다.
function detectSpeech() {
  const dur = video.duration;
  if (!audioBuffer) {
    const out = [];
    for (let t = 0; t < dur; t += 3) out.push({ start: t, end: Math.min(t + 2.8, dur) });
    return out;
  }
  const data = audioBuffer.getChannelData(0);
  const rate = audioBuffer.sampleRate;
  const win = Math.floor(rate * 0.1);
  const rms = [];
  for (let i = 0; i < data.length; i += win) {
    let sum = 0;
    const end = Math.min(i + win, data.length);
    for (let j = i; j < end; j++) sum += data[j] * data[j];
    rms.push(Math.sqrt(sum / (end - i)));
  }
  const sorted = [...rms].sort((a, b) => a - b);
  const threshold = Math.max(0.01, sorted[Math.floor(sorted.length * 0.2)] * 2.5);

  const segs = [];
  let start = null, quiet = 0;
  rms.forEach((v, i) => {
    const t = i * 0.1;
    if (v > threshold) {
      if (start === null) start = t;
      quiet = 0;
    } else if (start !== null && ++quiet >= 5) { // 0.5초 이상 조용하면 문장 끝
      segs.push({ start, end: t - 0.4 });
      start = null; quiet = 0;
    }
  });
  if (start !== null) segs.push({ start, end: rms.length * 0.1 });

  // 너무 긴 구간은 4초 단위로 쪼개고, 너무 짧은 잡음은 버립니다.
  return segs.filter((s) => s.end - s.start > 0.3).flatMap((s) => {
    const parts = [];
    for (let t = s.start; t < s.end; t += 4) parts.push({ start: t, end: Math.min(t + 4, s.end) });
    return parts;
  });
}

function transcribe(segments) {
  return segments.map((s, i) => ({ ...s, text: DEMO_LINES[i % DEMO_LINES.length] }));
}

function requireVideo() {
  if (!video.src || !video.duration) { toast('먼저 영상을 올려 주세요'); return false; }
  return true;
}

function chargeUsage() {
  if (usedSec) return true; // 같은 영상 재편집은 차감하지 않음
  const need = video.duration;
  if (need / 60 > FREE_MINUTES) { toast(`Free 플랜은 ${FREE_MINUTES}분까지 편집할 수 있어요`); return false; }
  usedSec = need;
  const min = Math.ceil(need / 60);
  $('usedMin').textContent = min;
  $('usedBar').style.width = Math.min(100, (min / FREE_MINUTES) * 100) + '%';
  return true;
}

async function runAI(label, fn) {
  const p = $('progress');
  p.classList.add('show');
  for (const pct of [12, 37, 64, 88, 100]) {
    p.textContent = `🤖 ${label} 중… ${pct}%`;
    await new Promise((r) => setTimeout(r, 260));
  }
  fn();
  p.classList.remove('show');
}

$('aiSub').addEventListener('click', () => {
  if (!requireVideo() || !chargeUsage()) return;
  runAI('음성 분석 및 자막 생성', () => {
    speech = speech || detectSpeech();
    subs = transcribe(speech);
    renderSubs(); renderTimeline();
    $('aiSub').classList.add('on');
    toast(`자막 ${subs.length}개를 생성했어요 (데모 문장 — 직접 수정 가능)`);
  });
});

$('aiCut').addEventListener('click', () => {
  if (!requireVideo()) return;
  if (cuts.length) { cuts = []; $('aiCut').classList.remove('on'); renderTimeline(); toast('컷편집을 해제했어요'); return; }
  if (!chargeUsage()) return;
  runAI('무음 구간 탐지', () => {
    speech = speech || detectSpeech();
    const dur = video.duration;
    let prev = 0;
    cuts = [];
    speech.forEach((s) => { if (s.start - prev > 0.7) cuts.push({ start: prev + 0.15, end: s.start - 0.15 }); prev = s.end; });
    if (dur - prev > 0.7) cuts.push({ start: prev + 0.15, end: dur });
    const saved = cuts.reduce((a, c) => a + c.end - c.start, 0);
    $('aiCut').classList.toggle('on', cuts.length > 0);
    renderTimeline();
    toast(cuts.length ? `무음 ${cuts.length}곳, ${saved.toFixed(1)}초를 잘라냈어요` : '잘라낼 무음 구간이 없어요');
  });
});

$('aiShort').addEventListener('click', () => {
  if (!requireVideo()) return;
  stage.classList.toggle('vertical');
  $('aiShort').classList.toggle('on');
});

document.querySelectorAll('[data-style]').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('[data-style]').forEach((x) => x.classList.toggle('on', x === b));
  caption.className = 'caption ' + b.dataset.style;
}));

// ---------- 자막 목록 ----------
function renderSubs() {
  const box = $('subs');
  if (!subs.length) { box.innerHTML = '<p style="color: var(--muted); font-size: 14px;">영상을 올리고 "AI 자동 자막"을 눌러 보세요.</p>'; return; }
  box.innerHTML = subs.map((s, i) => `
    <div class="sub" data-i="${i}">
      <time data-seek="${s.start}">${fmt(s.start)}</time>
      <input value="${s.text.replace(/"/g, '&quot;')}" data-edit="${i}" />
      <button data-del="${i}" aria-label="삭제">✕</button>
    </div>`).join('');
}

$('subs').addEventListener('click', (e) => {
  if (e.target.dataset.seek) video.currentTime = +e.target.dataset.seek;
  if (e.target.dataset.del) { subs.splice(+e.target.dataset.del, 1); renderSubs(); renderTimeline(); }
});
$('subs').addEventListener('input', (e) => {
  if (e.target.dataset.edit) subs[+e.target.dataset.edit].text = e.target.value;
});

$('addSub').addEventListener('click', () => {
  if (!requireVideo()) return;
  const t = video.currentTime;
  subs.push({ start: t, end: Math.min(t + 2.5, video.duration), text: '새 자막' });
  subs.sort((a, b) => a.start - b.start);
  renderSubs(); renderTimeline();
});

// ---------- 타임라인 / 재생 ----------
function renderTimeline() {
  const tl = $('timeline');
  const dur = video.duration || 1;
  const pct = (t) => (t / dur) * 100 + '%';
  tl.innerHTML =
    subs.map((s) => `<div class="seg" style="left:${pct(s.start)};width:${pct(s.end - s.start)}"></div>`).join('') +
    cuts.map((c) => `<div class="cut" style="left:${pct(c.start)};width:${pct(c.end - c.start)}"></div>`).join('') +
    `<div class="head" id="head" style="left:${pct(video.currentTime || 0)}"></div>`;
}

$('timeline').addEventListener('click', (e) => {
  if (!video.duration) return;
  const r = e.currentTarget.getBoundingClientRect();
  video.currentTime = ((e.clientX - r.left) / r.width) * video.duration;
});

video.addEventListener('loadedmetadata', renderTimeline);
video.addEventListener('timeupdate', () => {
  const t = video.currentTime;
  const cut = cuts.find((c) => t >= c.start && t < c.end);
  if (cut && !video.paused) { video.currentTime = cut.end; return; }

  const idx = subs.findIndex((s) => t >= s.start && t <= s.end);
  caption.hidden = idx < 0;
  if (idx >= 0) caption.textContent = subs[idx].text;
  document.querySelectorAll('.sub').forEach((el) => el.classList.toggle('active', +el.dataset.i === idx));
  const head = $('head');
  if (head) head.style.left = (t / video.duration) * 100 + '%';
});

// ---------- 내보내기 ----------
$('exportSrt').addEventListener('click', () => {
  if (!subs.length) { toast('내보낼 자막이 없어요'); return; }
  const srt = subs.map((s, i) => `${i + 1}\n${fmt(s.start, true)} --> ${fmt(s.end, true)}\n${s.text}\n`).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([srt], { type: 'text/plain;charset=utf-8' }));
  a.download = `${fileName}.srt`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast('SRT 파일을 저장했어요');
});

$('exportVideo').addEventListener('click', () => {
  if (!requireVideo()) return;
  toast('영상 렌더링은 Basic 플랜부터 가능해요');
  setTimeout(() => { location.href = 'pricing.html'; }, 1200);
});
