// 서버 API 호출과 공통 도우미
export class ApiError extends Error {
  constructor(err, status) {
    super(err?.message || "요청 실패");
    this.code = err?.code || "INTERNAL";
    this.detail = err?.detail;
    this.retryable = err?.retryable;
    this.status = status;
  }
}

async function handle(res) {
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) throw new ApiError(body?.error || { message: typeof body === "string" ? body : "요청 실패" }, res.status);
  return body;
}

export const api = {
  get: (url) => fetch(url).then(handle),
  post: (url, data) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) }).then(handle),
  put: (url, data) => fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) }).then(handle),
  patch: (url, data) => fetch(url, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data ?? {}) }).then(handle),
  del: (url) => fetch(url, { method: "DELETE" }).then(handle),
  form: (url, formData) => fetch(url, { method: "POST", body: formData }).then(handle),
  upload(url, formData, onProgress) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", url);
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress?.(e.loaded / e.total);
      xhr.onload = () => {
        let body;
        try { body = JSON.parse(xhr.responseText); } catch { body = null; }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body);
        else reject(new ApiError(body?.error || { message: `업로드 실패 (${xhr.status})` }, xhr.status));
      };
      xhr.onerror = () => reject(new ApiError({ message: "네트워크 오류로 업로드에 실패했습니다.", code: "NETWORK" }, 0));
      xhr.send(formData);
    });
  },
};

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function fmtMs(ms, withMs = true) {
  if (ms === null || ms === undefined || isNaN(ms)) return "-";
  ms = Math.max(0, Math.round(ms));
  const h = Math.floor(ms / 3600000), m = Math.floor((ms % 3600000) / 60000), s = Math.floor((ms % 60000) / 1000), r = ms % 1000;
  const base = (h ? String(h).padStart(2, "0") + ":" : "") + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
  return withMs ? base + "." + String(Math.floor(r / 100)) : base;
}

export function parseTime(str) {
  const v = String(str).trim().replace(",", ".");
  if (!v) return NaN;
  const parts = v.split(":").map(Number);
  if (parts.some(isNaN)) return NaN;
  let sec = 0;
  for (const p of parts) sec = sec * 60 + p;
  return Math.round(sec * 1000);
}

export function fmtDate(ts) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  return d.toLocaleString("ko-KR", { year: "2-digit", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function fmtSize(b) {
  if (!b) return "-";
  if (b > 1024 ** 3) return (b / 1024 ** 3).toFixed(2) + "GB";
  if (b > 1024 ** 2) return (b / 1024 ** 2).toFixed(1) + "MB";
  return Math.round(b / 1024) + "KB";
}

export function toast(msg, isErr = false, ms = 4000) {
  const box = document.getElementById("toast");
  const el = h("div", { class: isErr ? "err" : "" }, msg);
  box.append(el);
  setTimeout(() => el.remove(), ms);
}

export function errMsg(e) {
  if (e instanceof ApiError) return `${e.message}${e.detail ? " — " + e.detail : ""}`;
  return String(e?.message || e);
}

export const clone = (o) => JSON.parse(JSON.stringify(o));

export function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export const STATUS_LABEL = {
  queued: "대기", running: "실행 중", succeeded: "성공", failed: "실패", canceled: "취소됨", interrupted: "중단됨",
};
export const KIND_LABEL = {
  render: "MP4 렌더링", preview: "확정 미리보기", export_zip: "ZIP 묶기", silence: "무음 감지", transcribe: "자동 전사", recommend: "AI 구간 추천",
};
