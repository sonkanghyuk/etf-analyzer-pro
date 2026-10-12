// 내 콘텐츠: IndexedDB에 저장된 숏폼 목록
let items = [];
let playerUrl = null;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const dur = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const date = (t) => new Date(t).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const fileName = (it) => `${it.title.replace(/[\\/:*?"<>|]/g, '').slice(0, 40) || 'short'}.webm`;

function renderUsage() {
  const card = document.querySelector('.usage-card > div');
  if (Auth.user) {
    const left = Math.floor(Auth.user.balanceSec / 60);
    card.innerHTML = `${Auth.user.planName} · 남은 시간 <b id="remain">${left}분</b>`;
    document.getElementById('usageBar').style.width = '100%';
    return;
  }
  const usedMin = Math.ceil(Store.usedSec() / 60);
  const remain = Math.max(0, FREE_MINUTES - usedMin);
  document.getElementById('remain').textContent = `${remain}분`;
  document.getElementById('usageBar').style.width = Math.min(100, (usedMin / FREE_MINUTES) * 100) + '%';
}

function render() {
  const q = document.getElementById('q').value.trim();
  const sort = document.getElementById('sort').value;
  let list = items.filter((it) => !q || (it.title + it.sourceName).includes(q));
  if (sort === 'old') list = [...list].reverse();
  if (sort === 'score') list = [...list].sort((a, b) => b.score - a.score);

  document.getElementById('sCount').textContent = items.length;
  document.getElementById('sDur').textContent = dur(items.reduce((a, b) => a + b.duration, 0));
  document.getElementById('sSrc').textContent = new Set(items.map((i) => i.sourceName)).size;

  const grid = document.getElementById('grid');
  if (!items.length) {
    grid.innerHTML = `
      <div class="empty-state">
        <div style="font-size: 44px;">🎬</div>
        <h3>아직 만든 숏폼이 없어요</h3>
        <p>촬영본을 올리면 AI가 하이라이트를 골라 숏폼으로 만들어 드려요.</p>
        <a href="editor.html" class="btn btn-primary">첫 숏폼 만들기</a>
      </div>`;
    return;
  }
  grid.innerHTML = list.map((it) => `
    <article class="content-card" data-id="${it.id}">
      <button class="content-thumb" data-play="${it.id}" aria-label="재생">
        <img src="${it.thumb}" alt="" />
        <span class="dur">${dur(it.duration)}</span>
        <span class="score">AI ${it.score}점</span>
        <span class="play">▶</span>
      </button>
      <div class="content-meta">
        <b title="${esc(it.title)}">${esc(it.title)}</b>
        <span>${esc(getTemplate(it.templateId).name)} · ${esc(it.sourceName)}</span>
        <span>${date(it.createdAt)}</span>
      </div>
      <div class="content-actions">
        <button class="chip" data-dl="${it.id}">⬇ 다운로드</button>
        <button class="chip" data-share="${it.id}">공유</button>
        <button class="chip" data-del="${it.id}" aria-label="삭제">🗑</button>
      </div>
    </article>`).join('') || '<p class="empty-msg">검색 결과가 없어요.</p>';
}

function download(it) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(it.blob);
  a.download = fileName(it);
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

document.addEventListener('click', async (e) => {
  const find = (attr) => { const el = e.target.closest(`[data-${attr}]`); return el && items.find((i) => i.id === el.dataset[attr]); };
  const play = find('play');
  if (play) {
    playerUrl = URL.createObjectURL(play.blob);
    const v = document.getElementById('playerVideo');
    v.src = playerUrl; v.play().catch(() => {});
    const dl = document.getElementById('playerDl');
    dl.href = playerUrl; dl.download = fileName(play);
    document.getElementById('player').classList.add('open');
  }
  const dl = find('dl');
  if (dl) download(dl);
  const share = find('share');
  if (share) {
    const file = new File([share.blob], fileName(share), { type: share.blob.type });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      navigator.share({ files: [file], title: share.title }).catch(() => {});
    } else {
      toast('SNS 자동 업로드는 스탠다드 플랜부터 가능해요');
    }
  }
  const del = find('del');
  if (del && confirm(`"${del.title}" 숏폼을 삭제할까요?`)) {
    await Store.remove(del.id);
    items = items.filter((i) => i.id !== del.id);
    render();
    toast('삭제했어요');
  }
  if (e.target.matches('[data-close]') || e.target.id === 'player') {
    const v = document.getElementById('playerVideo');
    v.pause(); v.removeAttribute('src');
    if (playerUrl) URL.revokeObjectURL(playerUrl);
    document.getElementById('player').classList.remove('open');
  }
});

['q', 'sort'].forEach((id) => document.getElementById(id).addEventListener('input', render));

(async () => {
  renderUsage();
  authReady.then(renderUsage);
  items = await Store.all();
  render();
})();
