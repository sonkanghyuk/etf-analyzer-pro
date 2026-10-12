// 공통 스크립트: 모바일 메뉴, 토스트, 로그인 상태, API 호출
function toast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), 2600);
}

const CFG = window.CLIPORA || {};

const Auth = {
  get token() { try { return localStorage.getItem('clipora.token'); } catch (_) { return null; } },
  set token(v) { try { v ? localStorage.setItem('clipora.token', v) : localStorage.removeItem('clipora.token'); } catch (_) {} },
  user: null,
  enabled: () => !!CFG.apiBase,
  loggedIn() { return !!(this.enabled() && this.token); },
};

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

async function api(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (Auth.token) headers.Authorization = 'Bearer ' + Auth.token;
  let res;
  try {
    res = await fetch(CFG.apiBase.replace(/\/$/, '') + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch (_) {
    throw new ApiError(0, '서버에 연결하지 못했어요');
  }
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && Auth.token) { Auth.token = null; Auth.user = null; }
  if (!res.ok) {
    const detail = Array.isArray(data.detail) ? '입력값을 확인해 주세요' : data.detail;
    throw new ApiError(res.status, detail || '요청에 실패했어요');
  }
  return data;
}

async function loadMe() {
  if (!Auth.loggedIn()) return null;
  try { Auth.user = await api('/api/me'); } catch (_) { Auth.user = null; }
  return Auth.user;
}

function renderAuthNav() {
  const slot = document.querySelector('[data-login]');
  if (!slot) return;
  if (!Auth.enabled()) {
    slot.addEventListener('click', (e) => { e.preventDefault(); toast('로그인은 백엔드를 연결하면 사용할 수 있어요 (config.js)'); });
    return;
  }
  if (Auth.user) {
    slot.textContent = Auth.user.email.split('@')[0] + ' · 로그아웃';
    slot.onclick = async (e) => {
      e.preventDefault();
      try { await api('/api/auth/logout', { method: 'POST' }); } catch (_) {}
      Auth.token = null; Auth.user = null;
      location.reload();
    };
  } else {
    slot.textContent = '로그인';
    slot.href = 'login.html?next=' + encodeURIComponent(location.pathname.split('/').pop() + location.search);
  }
}

const authReady = loadMe().then((u) => { renderAuthNav(); return u; });

document.querySelector('[data-menu]')?.addEventListener('click', () => {
  document.getElementById('nav').classList.toggle('open');
});
