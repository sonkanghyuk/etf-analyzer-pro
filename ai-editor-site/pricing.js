// 요금제 데이터 — 가격/한도는 여기서만 수정하면 카드·비교표·계산기에 모두 반영됩니다.
const PLANS = [
  {
    id: 'free', name: 'Free', desc: '가볍게 AI 편집을 체험해 보세요',
    monthly: 0, minutes: 30, cta: '무료로 시작',
    features: ['월 30분 편집', 'AI 자동 자막', '720p 내보내기', '기본 템플릿 10종'],
    off: ['워터마크 제거', 'AI 컷편집', 'AI 숏폼 추출'],
  },
  {
    id: 'basic', name: 'Basic', desc: '정기적으로 영상을 올리는 크리에이터',
    monthly: 14900, minutes: 150, cta: 'Basic 시작하기',
    features: ['월 150분 편집', 'AI 자동 자막 + 번역 3개 언어', '1080p 내보내기', '워터마크 제거', 'AI 컷편집 (무음·말실수)'],
    off: ['AI 숏폼 추출'],
  },
  {
    id: 'pro', name: 'Pro', desc: '숏폼까지 빠르게 양산하는 전업 크리에이터',
    monthly: 29900, minutes: 600, cta: 'Pro 시작하기', popular: true,
    features: ['월 600분 편집', 'AI 자막 + 번역 30개 언어', '4K 내보내기', 'AI 숏폼 자동 추출', 'AI 보이스·더빙', '브랜드 키트', '우선 처리'],
    off: [],
  },
  {
    id: 'team', name: 'Team', desc: '여러 명이 함께 쓰는 팀·에이전시',
    monthly: 79000, minutes: 2000, cta: '팀 플랜 시작', perSeat: '3인 포함',
    features: ['월 2,000분 편집 (공유)', 'Pro의 모든 기능', '팀원 3명 포함 (추가 가능)', '공유 워크스페이스', '세금계산서 발행', '전담 매니저'],
    off: [],
  },
];

const COMPARE = [
  { group: '기본' },
  { label: '월 편집 시간', values: ['30분', '150분', '600분', '2,000분'] },
  { label: '최대 해상도', values: ['720p', '1080p', '4K', '4K'] },
  { label: '워터마크 제거', values: [false, true, true, true] },
  { label: '클라우드 저장 공간', values: ['2GB', '50GB', '200GB', '1TB'] },
  { group: 'AI 기능' },
  { label: 'AI 자동 자막', values: [true, true, true, true] },
  { label: '자막 번역', values: [false, '3개 언어', '30개 언어', '30개 언어'] },
  { label: 'AI 컷편집 (무음·말실수 제거)', values: [false, true, true, true] },
  { label: 'AI 숏폼 자동 추출', values: [false, false, true, true] },
  { label: 'AI 보이스·더빙', values: [false, false, true, true] },
  { group: '협업 · 지원' },
  { label: '브랜드 키트', values: [false, false, true, true] },
  { label: '공유 워크스페이스', values: [false, false, false, true] },
  { label: '고객 지원', values: ['커뮤니티', '이메일', '우선 이메일', '전담 매니저'] },
];

const YEARLY_DISCOUNT = 0.3;
let billing = 'monthly';

const won = (n) => '₩' + n.toLocaleString('ko-KR');
const monthlyPrice = (p) => billing === 'yearly' ? Math.round(p.monthly * (1 - YEARLY_DISCOUNT) / 100) * 100 : p.monthly;

function renderPlans() {
  document.getElementById('plans').innerHTML = PLANS.map((p) => {
    const price = monthlyPrice(p);
    const sub = p.monthly === 0
      ? '영원히 무료'
      : billing === 'yearly'
        ? `<s>${won(p.monthly)}</s>연 ${won(price * 12)} 청구`
        : (p.perSeat || '부가세 별도');
    return `
      <article class="plan ${p.popular ? 'popular' : ''}">
        ${p.popular ? '<span class="tag">가장 인기</span>' : ''}
        <h3>${p.name}</h3>
        <p class="desc">${p.desc}</p>
        <div class="price"><b>${won(price)}</b><span>/ 월</span></div>
        <div class="price-sub">${sub}</div>
        <button class="btn ${p.popular ? 'btn-primary' : 'btn-ghost'} btn-block" data-plan="${p.id}">${p.cta}</button>
        <ul>
          ${p.features.map((f) => `<li>${f}</li>`).join('')}
          ${p.off.map((f) => `<li class="off">${f}</li>`).join('')}
        </ul>
      </article>`;
  }).join('');
}

function renderCompare() {
  const cell = (v) => v === true ? '<span class="y">✓</span>' : v === false ? '<span class="n">—</span>' : v;
  const head = `<thead><tr><th>기능</th>${PLANS.map((p) => `<th>${p.name}</th>`).join('')}</tr></thead>`;
  const body = COMPARE.map((r) => r.group
    ? `<tr class="group"><td colspan="${PLANS.length + 1}">${r.group}</td></tr>`
    : `<tr><td>${r.label}</td>${r.values.map((v) => `<td>${cell(v)}</td>`).join('')}</tr>`).join('');
  document.getElementById('compare').innerHTML = head + `<tbody>${body}</tbody>`;
}

function updateCalc() {
  const count = +document.getElementById('count').value;
  const len = +document.getElementById('len').value;
  const need = count * len;
  document.getElementById('countOut').textContent = `${count}개`;
  document.getElementById('lenOut').textContent = `${len}분`;
  document.getElementById('needMin').textContent = `${need.toLocaleString('ko-KR')}분 / 월`;
  const rec = PLANS.find((p) => p.minutes >= need) || PLANS[PLANS.length - 1];
  document.getElementById('recPlan').textContent = need > rec.minutes ? `${rec.name} + 추가 시간` : rec.name;
  document.getElementById('recBtn').dataset.plan = rec.id;
}

function openCheckout(id) {
  const p = PLANS.find((x) => x.id === id);
  if (!p) return;
  if (p.monthly === 0) { location.href = 'editor.html'; return; }
  const price = monthlyPrice(p);
  document.getElementById('coTitle').textContent = `${p.name} 플랜 구독`;
  document.getElementById('coCycle').textContent = billing === 'yearly' ? '연간 결제 (30% 할인)' : '월간 결제';
  document.getElementById('coPrice').textContent = billing === 'yearly' ? `${won(price * 12)} / 년` : `${won(price)} / 월`;
  document.getElementById('checkout').classList.add('open');
}

document.querySelectorAll('[data-billing]').forEach((b) => b.addEventListener('click', () => {
  billing = b.dataset.billing;
  document.querySelectorAll('[data-billing]').forEach((x) => x.classList.toggle('on', x === b));
  renderPlans();
}));

document.addEventListener('click', (e) => {
  const planBtn = e.target.closest('[data-plan]');
  if (planBtn) { e.preventDefault(); openCheckout(planBtn.dataset.plan); }
  if (e.target.matches('[data-close]') || e.target.id === 'checkout') {
    document.getElementById('checkout').classList.remove('open');
  }
});

document.getElementById('coPay').addEventListener('click', () => {
  const email = document.getElementById('coEmail').value.trim();
  if (!/^\S+@\S+\.\S+$/.test(email)) { toast('이메일을 정확히 입력해 주세요'); return; }
  document.getElementById('checkout').classList.remove('open');
  toast('구독이 완료되었어요! (데모)');
});

['count', 'len'].forEach((id) => document.getElementById(id).addEventListener('input', updateCalc));

renderPlans();
renderCompare();
updateCalc();
