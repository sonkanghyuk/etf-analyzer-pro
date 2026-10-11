// 요금제 데이터 — 가격/한도는 여기서만 수정하면 카드·비교표·계산기에 모두 반영됩니다.
// 원본 약 5분당 숏폼 1개를 기준으로 개수를 안내합니다.
const MIN_PER_SHORT = 5;

const PLANS = [
  {
    id: 'free', name: 'Free', desc: '가입하면 바로 받는 무료 시간',
    price: 0, minutes: 90, oneTime: true, cta: '무료로 시작',
    features: ['가입 즉시 90분 (1회)', '숏폼 약 15개', '자동 자막 · 9:16 변환', '구간 지정'],
    off: ['워터마크 제거', '커스텀 페르소나', 'SNS 자동 업로드'],
  },
  {
    id: 'lite', name: '라이트', desc: '한 달에 강의 몇 편 올리는 개인 강사',
    price: 9900, minutes: 150, cta: '라이트 시작하기',
    features: ['매달 150분', '숏폼 약 30개', '자동 자막 · 9:16 변환', '구간 지정', '1080p 다운로드'],
    off: ['워터마크 제거', '커스텀 페르소나', 'SNS 자동 업로드'],
  },
  {
    id: 'standard', name: '스탠다드', desc: '숏폼으로 채널을 키우는 크리에이터', popular: true,
    price: 19900, minutes: 300, cta: '스탠다드 시작하기',
    features: ['매달 300분', '숏폼 약 60개', '워터마크 제거', '커스텀 페르소나 슬롯 5개', 'SNS 자동 업로드', '우선 처리'],
    off: [],
  },
  {
    id: 'pro', name: '프로', desc: '강연·교육 콘텐츠를 대량으로 운영하는 팀',
    price: 39900, listPrice: 47900, minutes: 600, cta: '프로 시작하기',
    features: ['매달 600분', '숏폼 약 100개+', '스탠다드의 모든 기능', '커스텀 페르소나 무제한', '4K 다운로드', '전담 지원'],
    off: [],
  },
];

const COMPARE = [
  { group: '기본' },
  { label: '제공 시간', values: ['90분 (1회)', '150분 / 월', '300분 / 월', '600분 / 월'] },
  { label: '예상 숏폼 수', values: ['약 15개', '약 30개', '약 60개', '약 100개+'] },
  { label: '최대 화질', values: ['720p', '1080p', '1080p', '4K'] },
  { label: '워터마크 제거', values: [false, false, true, true] },
  { group: 'AI 기능' },
  { label: '하이라이트 자동 선별', values: [true, true, true, true] },
  { label: '자동 자막 · 9:16 리프레이밍', values: [true, true, true, true] },
  { label: '구간 지정', values: [true, true, true, true] },
  { label: '커스텀 페르소나', values: [false, false, '5개', '무제한'] },
  { group: '배포 · 지원' },
  { label: 'SNS 자동 업로드', values: [false, false, true, true] },
  { label: '우선 처리', values: [false, false, true, true] },
  { label: '고객 지원', values: ['이메일', '이메일', '우선 이메일', '전담 매니저'] },
];

const won = (n) => '₩' + n.toLocaleString('ko-KR');

function renderPlans() {
  document.getElementById('plans').innerHTML = PLANS.map((p) => {
    const sub = p.oneTime
      ? '카드 등록 불필요'
      : p.listPrice
        ? `<s>${won(p.listPrice)}</s>${Math.round((1 - p.price / p.listPrice) * 100)}% 할인 중`
        : '부가세 포함 · 언제든 해지';
    return `
      <article class="plan ${p.popular ? 'popular' : ''}">
        ${p.popular ? '<span class="tag">가장 인기</span>' : ''}
        <h3>${p.name}</h3>
        <p class="desc">${p.desc}</p>
        <div class="price"><b>${won(p.price)}</b><span>${p.oneTime ? '' : '/ 월'}</span></div>
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
  document.getElementById('countOut').textContent = `${count}편`;
  document.getElementById('lenOut').textContent = `${len}분`;
  document.getElementById('needMin').textContent = `${need.toLocaleString('ko-KR')}분 / 월`;
  document.getElementById('needShorts').textContent = `숏폼 약 ${Math.max(1, Math.round(need / MIN_PER_SHORT))}개`;
  const paid = PLANS.filter((p) => !p.oneTime);
  const rec = paid.find((p) => p.minutes >= need) || paid[paid.length - 1];
  document.getElementById('recPlan').textContent = need > rec.minutes ? `${rec.name} + 구간 지정 활용` : rec.name;
  document.getElementById('recBtn').dataset.plan = rec.id;
}

function openCheckout(id) {
  const p = PLANS.find((x) => x.id === id);
  if (!p) return;
  if (p.oneTime) { location.href = 'editor.html'; return; }
  document.getElementById('coTitle').textContent = `${p.name} 플랜 구독`;
  document.getElementById('coCycle').textContent = `월간 결제 · 매달 ${p.minutes}분`;
  document.getElementById('coPrice').textContent = `${won(p.price)} / 월`;
  document.getElementById('checkout').classList.add('open');
}

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
