import { api, h, fill, fmtMs, fmtDate, fmtSize, toast, errMsg, STATUS_LABEL, KIND_LABEL } from "./api.js";
import { mountEditor } from "./editor.js";

const view = document.getElementById("view");
export const state = { status: null, jobs: [], jobListeners: new Set(), unmount: null };
window.__jss = { state };

// ------------------------------------------------------------ 작업 상태(실제 서버 상태를 폴링)
const known = new Map();
const pageStart = Date.now() / 1000;
async function pollJobs() {
  try {
    const list = await api.get("/api/jobs");
    state.jobs = list;
    for (const j of list) {
      const prev = known.get(j.id);
      const terminal = ["succeeded", "failed", "canceled", "interrupted"].includes(j.status);
      const newlyDone = prev ? prev !== j.status : j.created_at > pageStart - 2;
      if (terminal && newlyDone) {
        for (const fn of state.jobListeners) fn(j);
        if (j.status === "failed") toast(`${KIND_LABEL[j.kind] || j.kind} 실패: ${j.error_message || ""}`, true, 7000);
        if (j.status === "succeeded") toast(`${KIND_LABEL[j.kind] || j.kind} 완료`);
      }
      known.set(j.id, j.status);
    }
    const active = list.filter((j) => j.status === "queued" || j.status === "running").length;
    const c = document.getElementById("jobsCount");
    c.hidden = !active;
    c.textContent = active;
    if (!document.getElementById("drawer").classList.contains("hidden")) renderDrawer();
    for (const fn of state.jobListeners) fn(null);
  } catch (e) {
    /* 서버 중단 시 다음 주기에 재시도 */
  }
  const active = state.jobs.some((j) => j.status === "queued" || j.status === "running");
  setTimeout(pollJobs, active ? 1000 : 4000);
}

export function onJobs(fn) {
  state.jobListeners.add(fn);
  return () => state.jobListeners.delete(fn);
}

export function jobProgress(j) {
  const running = j.status === "running";
  const det = typeof j.progress === "number" && j.status === "running";
  const bar = running ? h("div", { class: "progress" + (det ? "" : " indeterminate") }, h("div", { style: det ? { width: (j.progress * 100).toFixed(1) + "%" } : {} })) : null;
  const pct = det ? ` ${(j.progress * 100).toFixed(0)}%` : "";
  const el = j.elapsed_s != null ? ` · ${j.elapsed_s}초` : "";
  return h("div", {}, h("div", { class: "small" }, `${STATUS_LABEL[j.status] || j.status}${pct} · ${j.stage || ""}${el}`), bar);
}

async function renderDrawer() {
  const d = document.getElementById("drawer");
  fill(d, 
    h("div", { class: "row" }, h("h2", { style: { margin: 0 } }, "작업 상태"), h("div", { class: "spacer" }), h("button", { onclick: () => d.classList.add("hidden") }, "닫기")),
    h("p", { class: "muted small" }, "진행률은 FFmpeg·전사 엔진이 실제로 보고한 값입니다. 측정할 수 없는 단계는 단계명과 경과 시간만 표시합니다."),
    ...state.jobs.slice(0, 40).map((j) =>
      h("div", { class: "job" },
        h("div", { class: "row" }, h("b", {}, KIND_LABEL[j.kind] || j.kind), h("span", { class: "badge " + (j.status === "succeeded" ? "ok" : j.status === "failed" ? "err" : j.status === "running" ? "warn" : "") }, STATUS_LABEL[j.status]),
          h("span", { class: "muted small" }, fmtDate(j.created_at)), h("div", { class: "spacer" }),
          (j.status === "queued" || j.status === "running") ? h("button", { class: "small danger", onclick: async () => { await api.post(`/api/jobs/${j.id}/cancel`); pollJobs(); } }, "취소") : null,
          (["failed", "canceled", "interrupted"].includes(j.status) && j.retryable) ? h("button", { class: "small", onclick: async () => { await api.post(`/api/jobs/${j.id}/retry`); toast("재시도를 대기열에 넣었습니다"); } }, "재시도") : null,
          h("button", { class: "small ghost", onclick: async (e) => {
            const box = e.target.closest(".job");
            const ex = box.querySelector("pre");
            if (ex) return ex.remove();
            const full = await api.get(`/api/jobs/${j.id}`);
            box.append(h("pre", {}, full.log || "(로그 없음)"));
          } }, "로그")),
        jobProgress(j),
        j.error_message ? h("div", { class: "errbox" }, `[${j.error_code}] ${j.error_message}`) : null,
        j.result?.filename ? h("div", { class: "small muted" }, j.result.filename) : null,
      )),
  );
}

document.getElementById("jobsBtn").onclick = () => {
  const d = document.getElementById("drawer");
  d.classList.toggle("hidden");
  if (!d.classList.contains("hidden")) renderDrawer();
};

// ------------------------------------------------------------ 라우팅
async function route() {
  if (state.unmount) { try { state.unmount(); } catch {} state.unmount = null; }
  const hash = location.hash || "#/projects";
  const [path, qs] = hash.split("?");
  const [, page, id] = path.split("/");
  const query = Object.fromEntries(new URLSearchParams(qs || ""));
  document.querySelectorAll("nav.main a").forEach((a) => a.classList.toggle("active", a.dataset.nav === page || (page === "project" && a.dataset.nav === "projects")));
  fill(view, );
  try {
    if (page === "project" && id) state.unmount = await mountEditor(view, id, query);
    else if (page === "templates") await pageTemplates();
    else if (page === "outputs") await pageOutputs();
    else if (page === "settings") await pageSettings();
    else await pageProjects();
  } catch (e) {
    view.append(h("div", { class: "page" }, h("div", { class: "errbox" }, errMsg(e))));
  }
}
window.addEventListener("hashchange", route);

async function loadStatus() {
  state.status = await api.get("/api/status");
  const s = state.status;
  fill(document.getElementById("sysBadges"), 
    h("span", { class: "badge " + (s.ffmpeg.found ? "ok" : "err") }, s.ffmpeg.found ? "FFmpeg 정상" : "FFmpeg 없음"),
    h("span", { class: "badge " + (s.ai.connected ? "ai" : "") }, s.ai.connected ? `AI: ${s.ai.model}` : "AI 미연결"),
    h("span", { class: "badge " + (s.transcribe.installed ? "" : "err") }, s.transcribe.installed ? "로컬 전사 엔진 설치됨" : "전사 엔진 없음"),
  );
}

// ------------------------------------------------------------ 프로젝트 목록
async function pageProjects() {
  const page = h("div", { class: "page" });
  view.append(page);
  let mode = localStorage.getItem("jss.projView") || "card";
  let q = "";
  const listBox = h("div");
  const fileInput = h("input", { type: "file", accept: "video/*,.mp4,.mov,.mkv,.m4v", hidden: true });
  const upStatus = h("div", { class: "small" });
  const titleIn = h("input", { type: "text", placeholder: "프로젝트 제목(비우면 파일 이름)" });
  const pathIn = h("input", { type: "text", placeholder: "예: D:\\강의\\2026-10 ETF 강의.mp4 (복사하지 않고 원본 위치에서 읽기)", style: { flex: 1, minWidth: "320px" } });
  const drop = h("div", { class: "drop" }, "영상 파일을 여기로 끌어오거나 ", h("button", { onclick: () => fileInput.click() }, "파일 선택"),
    h("div", { class: "small muted", style: { marginTop: "6px" } }, "MP4 권장 · 앱 데이터 폴더에 원본 사본을 보관합니다(원본은 수정하지 않음). 파일 내용을 실제로 검사합니다."));

  async function doUpload(file) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("title", titleIn.value);
    fill(upStatus, h("div", {}, `업로드 중: ${file.name}`), h("div", { class: "progress" }, h("div", { style: { width: "0%" } })));
    try {
      const p = await api.upload("/api/projects/upload", fd, (r) => {
        upStatus.querySelector(".progress > div").style.width = (r * 100).toFixed(1) + "%";
        if (r >= 1) upStatus.firstChild.textContent = "업로드 완료 — 영상 검사 중(길이·해상도·음성·해시)…";
      });
      fill(upStatus, h("div", { class: "infobox" }, `등록 완료: ${p.title}`));
      location.hash = `#/project/${p.id}`;
    } catch (e) {
      fill(upStatus, h("div", { class: "errbox" }, errMsg(e)));
    }
  }
  fileInput.onchange = () => fileInput.files[0] && doUpload(fileInput.files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); e.dataTransfer.files[0] && doUpload(e.dataTransfer.files[0]); };

  async function fromPath() {
    fill(upStatus, h("div", { class: "progress indeterminate" }, h("div")));
    try {
      const p = await api.post("/api/projects/from-path", { path: pathIn.value, title: titleIn.value });
      location.hash = `#/project/${p.id}`;
    } catch (e) { fill(upStatus, h("div", { class: "errbox" }, errMsg(e))); }
  }

  async function refresh() {
    let items;
    try { items = await api.get("/api/projects" + (q ? `?q=${encodeURIComponent(q)}` : "")); }
    catch (e) { fill(listBox, h("div", { class: "errbox" }, errMsg(e))); return; }
    if (!items.length) { fill(listBox, h("p", { class: "muted" }, q ? "검색 결과가 없습니다." : "아직 프로젝트가 없습니다. 위에서 긴 영상을 등록하세요.")); return; }
    const actions = (p) => h("div", { class: "row" },
      h("button", { class: "small primary", onclick: () => (location.hash = `#/project/${p.id}`) }, "열기"),
      h("button", { class: "small", onclick: async () => { const t = prompt("새 이름", p.title); if (t) { await api.patch(`/api/projects/${p.id}`, { title: t }); refresh(); } } }, "이름 변경"),
      h("button", { class: "small", onclick: async () => { await api.post(`/api/projects/${p.id}/duplicate`); toast("복제했습니다"); refresh(); } }, "복제"),
      h("button", { class: "small danger", onclick: () => confirmDelete(p, refresh) }, "삭제"));
    const statusBadge = (p) => {
      const map = { none: ["분석 전", ""], transcribed: ["전사/자막 있음", "ok"], recommended: ["AI 추천 완료", "ai"], rule_candidates: ["규칙 후보", ""] };
      const [t, c] = map[p.analysis_status] || [p.analysis_status, ""];
      return h("span", { class: "badge " + c }, t);
    };
    if (mode === "card") {
      fill(listBox, h("div", { class: "grid" }, items.map((p) => h("div", { class: "pcard" },
        h("img", { src: `/api/projects/${p.id}/thumb`, alt: "", onerror: (e) => (e.target.style.visibility = "hidden") }),
        h("div", { class: "body" },
          h("div", { class: "title" }, p.title),
          h("div", { class: "small muted" }, p.source ? `${fmtMs(p.source.duration_ms, false)} · ${p.source.width}×${p.source.height} · ${p.source.fps?.toFixed(2)}fps · ${p.source.has_audio ? "음성 있음" : "음성 없음"}` : "원본 없음"),
          h("div", { class: "row small" }, statusBadge(p), h("span", { class: "badge" }, `클립 ${p.clip_count}`), h("span", { class: "badge" }, `완성 ${p.artifact_count}`)),
          h("div", { class: "small muted" }, `생성 ${fmtDate(p.created_at)} · 해시 ${p.source?.sha256?.slice(0, 10) || "-"}`),
          actions(p))))));
    } else {
      fill(listBox, h("table", { class: "list" },
        h("tr", {}, ["제목", "길이", "해상도", "fps", "음성", "상태", "클립", "생성", ""].map((t) => h("th", {}, t))),
        items.map((p) => h("tr", {},
          h("td", {}, p.title), h("td", {}, fmtMs(p.source?.duration_ms, false)), h("td", {}, p.source ? `${p.source.width}×${p.source.height}` : "-"),
          h("td", {}, p.source?.fps?.toFixed(2) || "-"), h("td", {}, p.source?.has_audio ? "있음" : "없음"), h("td", {}, statusBadge(p)),
          h("td", {}, p.clip_count), h("td", {}, fmtDate(p.created_at)), h("td", {}, actions(p))))));
    }
  }

  page.append(
    h("h1", {}, "프로젝트"),
    h("div", { class: "card" },
      h("h3", { style: { marginTop: 0 } }, "새 프로젝트 — 긴 강의 영상 등록"),
      h("div", { class: "row", style: { marginBottom: "8px" } }, titleIn),
      drop, fileInput,
      h("div", { class: "row", style: { marginTop: "10px" } }, h("span", { class: "small muted" }, "또는 PC 경로로 등록:"), pathIn, h("button", { onclick: fromPath }, "경로로 등록")),
      h("div", { class: "row small muted", style: { marginTop: "6px" } }, "YouTube URL 가져오기", h("span", { class: "badge soon" }, "준비 중"), "— 권한 있는 원본 파일을 직접 등록하세요."),
      upStatus),
    h("div", { class: "row", style: { margin: "16px 0 10px" } },
      h("input", { type: "search", placeholder: "제목·파일명 검색", oninput: (e) => { q = e.target.value; refresh(); } }),
      h("div", { class: "spacer" }),
      h("button", { class: mode === "card" ? "primary small" : "small", onclick: () => { mode = "card"; localStorage.setItem("jss.projView", mode); pageRerender(); } }, "카드"),
      h("button", { class: mode === "list" ? "primary small" : "small", onclick: () => { mode = "list"; localStorage.setItem("jss.projView", mode); pageRerender(); } }, "목록")),
    listBox);
  function pageRerender() { fill(view, ); pageProjects(); }
  refresh();
}

function confirmDelete(p, after) {
  const chk = h("input", { type: "checkbox" });
  const owned = p.source?.owned;
  const dlg = h("dialog", {},
    h("h3", {}, `'${p.title}' 삭제`),
    h("p", {}, "프로젝트 데이터(전사·클립·편집 기록)를 목록에서 지웁니다. 완성 MP4 파일은 출력 폴더에 남습니다."),
    owned ? h("label", { class: "row" }, chk, "앱이 보관한 원본 사본도 삭제(다른 프로젝트가 쓰지 않을 때만)") :
      h("p", { class: "muted small" }, "원본은 PC 경로에서 읽은 파일이므로 절대 삭제하지 않습니다."),
    h("div", { class: "row" }, h("div", { class: "spacer" }),
      h("button", { onclick: () => dlg.close() }, "취소"),
      h("button", { class: "danger", onclick: async () => { await api.del(`/api/projects/${p.id}?delete_source_copy=${chk.checked}`); dlg.close(); toast("삭제했습니다"); after(); } }, "삭제")));
  document.body.append(dlg);
  dlg.showModal();
  dlg.addEventListener("close", () => dlg.remove());
}

// ------------------------------------------------------------ 템플릿·에셋
async function pageTemplates() {
  const page = h("div", { class: "page" });
  view.append(page);
  const [tpls, assets, fonts] = await Promise.all([api.get("/api/templates"), api.get("/api/assets"), api.get("/api/fonts")]);
  const importIn = h("input", { type: "file", accept: ".json", hidden: true, onchange: async () => {
    const fd = new FormData(); fd.append("file", importIn.files[0]);
    try { await api.form("/api/templates/import", fd); toast("템플릿을 가져왔습니다"); route(); } catch (e) { toast(errMsg(e), true); }
  } });
  page.append(
    h("h1", {}, "템플릿·에셋"),
    h("p", { class: "muted" }, "템플릿은 배경 이미지 한 장이 아니라 영상 배치·제목·자막·강조·로고·색 설정을 담은 버전 데이터입니다. 편집 화면에서 ‘현재 스타일을 템플릿으로 저장’하면 새 템플릿/새 버전이 만들어집니다. 이미 편집한 클립은 템플릿을 고쳐도 자동으로 바뀌지 않습니다."),
    h("div", { class: "row" }, h("button", { onclick: () => importIn.click() }, "템플릿 가져오기(JSON)"), importIn),
    h("div", { class: "grid", style: { marginTop: "12px" } }, tpls.map((t) => h("div", { class: "pcard" },
      h("img", { src: `/api/templates/${t.id}/preview.png?v=${t.current_version}`, style: { aspectRatio: "9/16", objectFit: "contain" } }),
      h("div", { class: "body" },
        h("div", { class: "title" }, t.name),
        h("div", { class: "row small" }, h("span", { class: "badge" }, `v${t.current_version}`), t.builtin ? h("span", { class: "badge" }, "기본 제공") : null, h("span", { class: "muted" }, fmtDate(t.updated_at))),
        h("div", { class: "row" },
          h("button", { class: "small", onclick: async () => { await api.post(`/api/templates/${t.id}/duplicate`, {}); route(); } }, "복제"),
          t.builtin ? null : h("button", { class: "small", onclick: async () => { const n = prompt("새 이름", t.name); if (n) { await api.put(`/api/templates/${t.id}`, { name: n }); route(); } } }, "이름 변경"),
          h("a", { class: "small", href: `/api/templates/${t.id}/export` }, "내보내기"),
          t.builtin ? null : h("button", { class: "small danger", onclick: async () => { if (confirm("템플릿을 삭제할까요? 이미 적용된 클립의 스타일은 유지됩니다.")) { await api.del(`/api/templates/${t.id}`); route(); } } }, "삭제")))))),
    h("h2", {}, "에셋(로고·배경·글꼴)"),
    h("p", { class: "muted small" }, "직접 만들었거나 이용 조건을 확인한 파일만 등록하세요. 참고 서비스의 로고·배경·글꼴은 포함하지 않습니다."),
    assetUploader(),
    h("table", { class: "list" }, h("tr", {}, ["종류", "파일", "이용 조건 메모", "등록", ""].map((x) => h("th", {}, x))),
      assets.map((a) => h("tr", {}, h("td", {}, { logo: "로고", background: "배경", font: "글꼴" }[a.kind] || a.kind), h("td", {}, a.filename), h("td", {}, a.license_note), h("td", {}, fmtDate(a.created_at)),
        h("td", {}, h("button", { class: "small danger", onclick: async () => { await api.del(`/api/assets/${a.id}`); route(); } }, "삭제"))))),
    h("h2", {}, "사용 가능한 글꼴"),
    h("table", { class: "list" }, h("tr", {}, ["이름", "출처", "라이선스"].map((x) => h("th", {}, x))),
      fonts.map((f) => h("tr", {}, h("td", {}, f.name), h("td", {}, f.source), h("td", {}, f.license)))),
  );
}

function assetUploader() {
  const kind = h("select", {}, h("option", { value: "logo" }, "로고(PNG 권장)"), h("option", { value: "background" }, "배경 이미지"), h("option", { value: "font" }, "글꼴(TTF/OTF)"));
  const lic = h("input", { type: "text", placeholder: "이용 조건 메모(예: 직접 제작, OFL 등)", style: { minWidth: "260px" } });
  const file = h("input", { type: "file" });
  return h("div", { class: "row card" }, kind, file, lic, h("button", { onclick: async () => {
    if (!file.files[0]) return toast("파일을 선택하세요", true);
    const fd = new FormData(); fd.append("file", file.files[0]); fd.append("kind", kind.value); fd.append("license_note", lic.value);
    try { await api.form("/api/assets", fd); toast("등록했습니다"); route(); } catch (e) { toast(errMsg(e), true); }
  } }, "등록"));
}

// ------------------------------------------------------------ 완성 영상
async function pageOutputs() {
  const page = h("div", { class: "page" });
  view.append(page);
  const [arts, zips] = await Promise.all([api.get("/api/artifacts"), api.get("/api/artifacts?kind=zip")]);
  const selected = new Set();
  page.append(
    h("h1", {}, "완성 영상"),
    h("p", { class: "muted small" }, "파일은 검사(코덱·해상도·길이·음성)를 통과한 경우에만 여기에 나타납니다. 다시 렌더링해도 이전 성공본은 지우지 않습니다."),
    h("div", { class: "row" }, h("button", { onclick: async () => {
      if (!selected.size) return toast("ZIP으로 묶을 영상을 선택하세요", true);
      try { await api.post("/api/artifacts/zip", { artifact_ids: [...selected] }); toast("ZIP 작업을 시작했습니다(작업 상태 참고)"); } catch (e) { toast(errMsg(e), true); }
    } }, "선택 항목 ZIP 저장")),
    arts.length ? h("table", { class: "list" },
      h("tr", {}, ["", "", "제목", "프로젝트", "길이", "템플릿", "상태", "생성", ""].map((x) => h("th", {}, x))),
      arts.map((a) => h("tr", {},
        h("td", {}, h("input", { type: "checkbox", onchange: (e) => (e.target.checked ? selected.add(a.id) : selected.delete(a.id)) })),
        h("td", {}, h("img", { src: `/api/artifacts/${a.id}/thumb`, style: { width: "54px", height: "96px", objectFit: "cover", background: "#000" }, onerror: (e) => (e.target.style.visibility = "hidden") })),
        h("td", {}, h("div", {}, a.meta?.title || a.clip_title), h("div", { class: "small muted" }, a.filename)),
        h("td", {}, a.project_title || "-"), h("td", {}, fmtMs(a.duration_ms)),
        h("td", {}, a.meta?.template ? `${a.meta.template.name} v${a.meta.template.version}` : "-"),
        h("td", {}, a.exists ? h("span", { class: "badge ok" }, `검사 통과 · ${a.probe?.width}×${a.probe?.height} · ${a.probe?.audio_kind === "silent" ? "무음 오디오" : "원본 음성"}`) : h("span", { class: "badge err" }, "파일 없음")),
        h("td", {}, fmtDate(a.created_at)),
        h("td", {}, h("div", { class: "row" },
          a.exists ? h("a", { href: `/api/artifacts/${a.id}/download` }, "MP4 저장") : null,
          a.exists ? h("a", { href: `/api/artifacts/${a.id}/srt` }, "SRT") : null,
          h("a", { href: `#/project/${a.project_id}?clip=${a.clip_id}` }, "편집"),
          h("button", { class: "small danger", onclick: async () => { if (confirm("이 완성 영상 파일을 삭제할까요?")) { await api.del(`/api/artifacts/${a.id}`); route(); } } }, "삭제")))))) :
      h("p", { class: "muted" }, "아직 완성 영상이 없습니다."),
    h("h2", {}, "ZIP 일괄 저장본"),
    zips.length ? h("table", { class: "list" }, zips.map((z) => h("tr", {}, h("td", {}, z.filename), h("td", {}, `${z.meta?.files?.filter((f) => f.endsWith(".mp4")).length || 0}개 영상`), h("td", {}, fmtSize(z.size)), h("td", {}, fmtDate(z.created_at)),
      h("td", {}, z.exists ? h("a", { href: `/api/artifacts/${z.id}/download` }, "ZIP 저장") : "파일 없음")))) : h("p", { class: "muted" }, "없음"),
  );
}

// ------------------------------------------------------------ 설정
async function pageSettings() {
  await loadStatus();
  const s = state.status;
  const dict = await api.get("/api/dictionary");
  const dictBox = h("textarea", { rows: 6 }, dict.words.join("\n"));
  const page = h("div", { class: "page" });
  view.append(page);
  page.append(
    h("h1", {}, "설정"),
    h("div", { class: "grid" },
      h("div", { class: "card" }, h("h3", {}, "영상 처리 (로컬)"),
        h("p", {}, s.ffmpeg.found ? h("span", { class: "badge ok" }, "정상") : h("span", { class: "badge err" }, "FFmpeg 없음"), " ", h("span", { class: "small muted" }, s.ffmpeg.version || "README의 설치 안내 참고")),
        h("p", { class: "small muted" }, `데이터 폴더: ${s.data_dir}`), h("p", { class: "small muted" }, `완성 영상 폴더: ${s.output_dir}`), h("p", { class: "small muted" }, `남은 디스크: ${s.disk_free_gb}GB`),
        h("p", { class: "small" }, "출력: H.264 / AAC / 1080×1920 / 30fps / yuv420p / faststart. GPU 가속 ", h("span", { class: "badge soon" }, "준비 중"))),
      h("div", { class: "card" }, h("h3", {}, "자동 전사 (로컬 · 외부 API 요금 없음)"),
        h("p", {}, h("span", { class: "badge " + (s.transcribe.installed ? "ok" : "err") }, s.transcribe.installed ? "faster-whisper 설치됨" : "미설치")),
        h("p", { class: "small" }, `모델: ${s.transcribe.model} — ${s.transcribe.label}`),
        h("p", { class: "small muted" }, `언어: 한국어, 장치: ${s.transcribe.device}. 로컬 처리는 PC 성능·시간·전기를 사용합니다. .env의 JSS_WHISPER_MODEL로 모델을 바꿀 수 있습니다.`),
        h("p", { class: "small" }, "외부 전사 API ", h("span", { class: "badge soon" }, "준비 중"))),
      h("div", { class: "card" }, h("h3", {}, "AI 구간 추천 (외부 API · 비용 발생)"),
        h("p", {}, h("span", { class: "badge " + (s.ai.connected ? "ai" : "") }, s.ai.label)),
        h("p", { class: "small" }, `제공자: Anthropic · 모델: ${s.ai.model}`),
        h("p", { class: "small muted" }, s.ai.sends),
        h("p", { class: "small" }, s.ai.price_known ? `단가(.env): 입력 $${s.ai.price_input_per_mtok}/백만 토큰, 출력 $${s.ai.price_output_per_mtok}/백만 토큰` : "단가 미설정 → 비용 미확인으로 표시합니다. 공식 요금표를 확인해 .env에 넣으세요."),
        h("p", { class: "small muted" }, "키는 .env 파일(서버)에만 저장되고 브라우저로 전송되지 않습니다.")),
    ),
    h("h2", {}, "사용자 사전 (전사 힌트·교정 제안)"),
    h("p", { class: "small muted" }, "한 줄에 하나. 자동으로 바꾸지 않고, 전사문 교정 화면에 ‘제안’으로만 표시합니다. 사전을 바꾸면 다음 전사부터 반영됩니다."),
    dictBox,
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "primary", onclick: async () => { await api.put("/api/dictionary", { words: dictBox.value.split("\n") }); toast("사전을 저장했습니다"); } }, "사전 저장")),
    h("h2", {}, "준비 중 기능"),
    h("div", { class: "row" }, Object.entries({ youtube_import: "YouTube 가져오기", music: "배경음악", transitions: "후킹 전환", mosaic: "모자이크", emphasis_animation: "강조 애니메이션", external_stt: "외부 전사 API", gpu_encode: "GPU 인코딩" }).map(([k, v]) => h("span", { class: "badge soon" }, `${v}: ${s.features[k]}`))),
    h("h2", {}, "키보드"),
    h("p", { class: "small" }, h("span", { class: "kbd" }, "Space"), " 재생/정지 · ", h("span", { class: "kbd" }, "Ctrl+S"), " 저장 · ", h("span", { class: "kbd" }, "Ctrl+Z / Ctrl+Shift+Z"), " 실행 취소/다시 실행 · ", h("span", { class: "kbd" }, "Alt+↑/↓"), " 이전/다음 문장 · 선택한 요소 ", h("span", { class: "kbd" }, "방향키"), " 1px 이동(Shift 10px)"),
  );
}

loadStatus().catch(() => {});
pollJobs();
route();
