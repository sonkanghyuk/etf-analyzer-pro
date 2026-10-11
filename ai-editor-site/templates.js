// 숏폼 템플릿 정의 + 9:16 프레임 렌더러
// 템플릿 갤러리 미리보기, 에디터 미리보기, 실제 내보내기가 모두 renderFrame() 하나로 그려집니다.

const TEMPLATES = [
  {
    id: 'lecture-clean', name: '강의 · 클린', category: '강의',
    desc: '검은 배경에 영상을 가운데 두고 위에 제목, 아래 자막. 가장 무난한 강의용.',
    bg: '#000', layout: 'fit',
    title: { color: '#fff', size: 52, y: 0.16 },
    caption: { color: '#fff', stroke: '#000', size: 44, y: 0.74 },
  },
  {
    id: 'lecture-board', name: '강의 · 칠판', category: '강의',
    desc: '칠판 느낌의 녹색 배경과 노란 제목으로 수업 분위기를 살려요.',
    bg: '#1f3a2e', layout: 'fit',
    title: { color: '#ffe066', size: 54, y: 0.15 },
    caption: { color: '#fff', box: 'rgba(0,0,0,.55)', size: 40, y: 0.74 },
  },
  {
    id: 'talk-quote', name: '강연 · 명언', category: '강연',
    desc: '흐린 배경 위에 큰 따옴표 제목. 한 마디가 강한 강연 클립에.',
    bg: 'blur', layout: 'fit',
    title: { color: '#fff', size: 50, y: 0.15, quote: true },
    caption: { color: '#fff', stroke: '#000', highlight: '#ffd43b', size: 50, y: 0.72 },
  },
  {
    id: 'interview-talk', name: '인터뷰 · 토크', category: '인터뷰',
    desc: '화면을 꽉 채우고 상단에 빨간 제목 띠. 인터뷰·팟캐스트용.',
    bg: '#000', layout: 'fill',
    title: { color: '#fff', bar: '#e03131', size: 46, y: 0.1 },
    caption: { color: '#fff', box: 'rgba(0,0,0,.75)', size: 42, y: 0.78 },
  },
  {
    id: 'variety-pop', name: '예능 · 팝', category: '예능',
    desc: '두꺼운 테두리 노란 자막과 핑크 강조. 반응형 클립에 딱.',
    bg: '#000', layout: 'fill',
    title: { color: '#fff', stroke: '#000', size: 58, y: 0.12 },
    caption: { color: '#ffe14d', stroke: '#000', highlight: '#ff5c8a', size: 56, y: 0.74 },
  },
  {
    id: 'info-card', name: '정보 · 카드뉴스', category: '정보',
    desc: '밝은 배경에 검은 굵은 제목. 정보 전달형 숏폼에 깔끔해요.',
    bg: '#f4f4f6', layout: 'fit',
    title: { color: '#111', size: 54, y: 0.15 },
    caption: { color: '#111', highlight: '#7c5cff', size: 42, y: 0.72 },
  },
  {
    id: 'webinar-brand', name: '웨비나 · 브랜드', category: '비즈니스',
    desc: '브랜드 그라데이션 배경. 웨비나·사내 교육 홍보용.',
    bg: ['#4c2fd6', '#0b8f88'], layout: 'fit',
    title: { color: '#fff', size: 50, y: 0.15 },
    caption: { color: '#fff', box: 'rgba(255,255,255,.18)', size: 42, y: 0.74 },
  },
  {
    id: 'minimal', name: '미니멀', category: '정보',
    desc: '제목 없이 영상과 작은 자막만. 영상 자체가 강할 때.',
    bg: '#000', layout: 'fill',
    title: null,
    caption: { color: '#fff', shadow: true, size: 38, y: 0.82 },
  },
];

const getTemplate = (id) => TEMPLATES.find((t) => t.id === id) || TEMPLATES[0];

// 영상이 없을 때 쓰는 가짜 촬영본(강연자 실루엣)
let _placeholder;
function placeholderSource() {
  if (_placeholder) return _placeholder;
  const c = document.createElement('canvas');
  c.width = 640; c.height = 360;
  const g = c.getContext('2d');
  const grad = g.createLinearGradient(0, 0, 640, 360);
  grad.addColorStop(0, '#3b3f5c'); grad.addColorStop(1, '#1d2033');
  g.fillStyle = grad; g.fillRect(0, 0, 640, 360);
  g.fillStyle = 'rgba(255,255,255,.08)'; g.fillRect(380, 60, 200, 120); // 슬라이드
  g.fillStyle = '#c9a27e'; g.beginPath(); g.arc(320, 150, 42, 0, Math.PI * 2); g.fill(); // 얼굴
  g.fillStyle = '#2b2b2b'; g.beginPath(); g.arc(320, 132, 44, Math.PI, 0); g.fill(); // 머리
  g.fillStyle = '#5c7cfa'; g.beginPath(); g.roundRect(250, 200, 140, 160, 40); g.fill(); // 몸
  g.fillStyle = '#6b4f3a'; g.fillRect(270, 270, 100, 90); // 단상
  _placeholder = c;
  return c;
}

function wrapText(ctx, text, maxW) {
  const lines = [];
  let line = '';
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const test = line ? line + ' ' + word : word;
    if (ctx.measureText(test).width <= maxW) { line = test; continue; }
    if (line) lines.push(line);
    line = word;
    while (ctx.measureText(line).width > maxW && line.length > 1) { // 띄어쓰기 없는 긴 단어
      let i = line.length;
      while (i > 1 && ctx.measureText(line.slice(0, i)).width > maxW) i--;
      lines.push(line.slice(0, i));
      line = line.slice(i);
    }
  }
  if (line) lines.push(line);
  return lines;
}

// 텍스트 블록 그리기. style: { color, stroke, box, bar, highlight, shadow, size }
function drawTextBlock(ctx, text, W, H, style, yFrac, weight = 800) {
  if (!text) return;
  const size = style.size;
  ctx.font = `${weight} ${size}px Pretendard, "Noto Sans KR", sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  const lines = wrapText(ctx, text, W * 0.84).slice(0, 3);
  const lh = size * 1.3;
  const cy = H * yFrac;
  const top = cy - (lines.length * lh) / 2;
  const longest = text.split(/\s+/).reduce((a, b) => (b.length > a.length ? b : a), '');

  if (style.bar) {
    ctx.fillStyle = style.bar;
    ctx.fillRect(0, top - size * 0.5, W, lines.length * lh + size);
  }
  lines.forEach((ln, i) => {
    const y = top + lh * i + lh / 2;
    const w = ctx.measureText(ln).width;
    if (style.box) {
      ctx.fillStyle = style.box;
      ctx.beginPath(); ctx.roundRect(W / 2 - w / 2 - 18, y - lh / 2 + 4, w + 36, lh - 8, 12); ctx.fill();
    }
    // 단어 단위로 그려서 핵심어(가장 긴 단어)를 강조색으로
    let x = W / 2 - w / 2;
    ctx.textAlign = 'left';
    ln.split(' ').forEach((word, wi, arr) => {
      const piece = wi < arr.length - 1 ? word + ' ' : word;
      ctx.shadowColor = style.shadow ? 'rgba(0,0,0,.9)' : 'transparent';
      ctx.shadowBlur = style.shadow ? 12 : 0;
      if (style.stroke) {
        ctx.lineJoin = 'round'; ctx.lineWidth = size * 0.18; ctx.strokeStyle = style.stroke;
        ctx.strokeText(piece, x, y);
      }
      ctx.fillStyle = style.highlight && word === longest ? style.highlight : style.color;
      ctx.fillText(piece, x, y);
      x += ctx.measureText(piece).width;
    });
    ctx.shadowBlur = 0;
    ctx.textAlign = 'center';
  });
}

// opts: { source, tpl, caption, title, watermark }
function renderFrame(ctx, W, H, opts) {
  const tpl = opts.tpl;
  const src = opts.source || placeholderSource();
  const sw = src.videoWidth || src.width;
  const sh = src.videoHeight || src.height;
  ctx.save();
  ctx.clearRect(0, 0, W, H);

  // 배경
  if (tpl.bg === 'blur') {
    const s = Math.max(W / sw, H / sh);
    ctx.filter = 'blur(28px) brightness(.55)';
    ctx.drawImage(src, (W - sw * s) / 2, (H - sh * s) / 2, sw * s, sh * s);
    ctx.filter = 'none';
  } else if (Array.isArray(tpl.bg)) {
    const g = ctx.createLinearGradient(0, 0, W, H);
    g.addColorStop(0, tpl.bg[0]); g.addColorStop(1, tpl.bg[1]);
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  } else {
    ctx.fillStyle = tpl.bg; ctx.fillRect(0, 0, W, H);
  }

  // 영상
  if (tpl.layout === 'fill') {
    const s = Math.max(W / sw, H / sh);
    ctx.drawImage(src, (W - sw * s) / 2, (H - sh * s) / 2, sw * s, sh * s);
  } else {
    const s = W / sw;
    const h = sh * s;
    ctx.drawImage(src, 0, H * 0.45 - h / 2, W, h);
  }

  if (tpl.title && opts.title) {
    const text = tpl.title.quote ? `“${opts.title}”` : opts.title;
    drawTextBlock(ctx, text, W, H, tpl.title, tpl.title.y, 900);
  }
  if (opts.caption) drawTextBlock(ctx, opts.caption, W, H, tpl.caption, tpl.caption.y);

  if (opts.watermark) {
    ctx.font = '700 26px Pretendard, sans-serif';
    ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
    ctx.fillStyle = 'rgba(255,255,255,.55)';
    ctx.fillText('▶ Clipora', W - 24, H - 24);
  }
  ctx.restore();
}
