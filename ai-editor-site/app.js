// 공통 스크립트: 모바일 메뉴, 토스트, 로그인 안내
function toast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2400);
}

document.querySelector('[data-menu]')?.addEventListener('click', () => {
  document.getElementById('nav').classList.toggle('open');
});

document.querySelectorAll('[data-login]').forEach((el) => el.addEventListener('click', (e) => {
  e.preventDefault();
  toast('로그인은 데모에서 지원되지 않아요');
}));
