import { api, h, fmtMs, parseTime, fmtDate, toast, errMsg, clone, debounce, STATUS_LABEL } from "./api.js";
import { onJobs, jobProgress } from "./app.js";

const CANVAS_W = 1080, CANVAS_H = 1920;
const getPath = (o, p) => p.split(".").reduce((a, k) => (a == null ? undefined : a[k]), o);
function setPath(o, p, v) {
  const ks = p.split(".");
  let cur = o;
  for (const k of ks.slice(0, -1)) { if (cur[k] == null || typeof cur[k] !== "object") cur[k] = {}; cur = cur[k]; }
  cur[ks[ks.length - 1]] = v;
}

export async function mountEditor(root, pid, query = {}) {
  const S = {
    pid, project: null, transcript: null, clips: [], clip: null, draft: null, dirty: false, saving: false, saveErr: null,
    scene: null, sceneErr: null, sel: "subtitle", styleEl: "subtitle", cueScope: "clip", currentCueId: null, outTime: 0,
    playing: false, rightTab: "ai", midTab: "clip", recs: [], templates: [], fonts: [], assets: [], status: null,
    silence: null, transcriptDraft: null, transcriptDirty: false, rangeSel: { a: null, b: null }, filter: "",
    lastLabel: "편집", estimate: null, selectedClipIds: new Set(), videoError: null,
  };
  const disposers = [];

  // ---------------------------------------------------------- 뼈대
  const el = {
    bar: h("div", { class: "ebar" }),
    left: h("section", { class: "pane" }),
    mid: h("section", { class: "pane" }),
    right: h("section", { class: "pane" }),
  };
  const panes = h("div", { class: "panes" }, el.left, el.mid, el.right);
  root.append(h("div", { class: "editor" }, el.bar, panes));

  // ---------------------------------------------------------- 데이터 적재
  async function loadProject() {
    [S.project, S.status, S.templates, S.fonts, S.assets] = await Promise.all([
      api.get(`/api/projects/${pid}`), api.get("/api/status"), api.get("/api/templates"), api.get("/api/fonts"), api.get("/api/assets"),
    ]);
    S.transcript = await api.get(`/api/projects/${pid}/transcript`);
    S.transcriptDraft = S.transcript.working ? clone(S.transcript.working.cues) : null;
    S.transcriptDirty = false;
    S.clips = await api.get(`/api/projects/${pid}/clips`);
    S.recs = await api.get(`/api/projects/${pid}/recommendations`);
  }

  async function openClip(cid) {
    await flushSave();
    if (!cid) { S.clip = null; S.draft = null; S.scene = null; renderAll(); return; }
    S.clip = await api.get(`/api/clips/${cid}`);
    S.draft = { title: S.clip.title, data: clone(S.clip.data) };
    S.dirty = false;
    S.currentCueId = null;
    S.silence = null;
    S.cueScope = "clip";
    history.replaceState(null, "", `#/project/${pid}?clip=${cid}`);
    renderAll();
    await refreshScene(true);
    seekOut(0);
  }

  // ---------------------------------------------------------- 저장
  const autosave = debounce(() => saveNow(), 1500);
  function markDirty(label = "편집", sceneToo = true) {
    S.dirty = true;
    S.lastLabel = label;
    renderSaveState();
    if (sceneToo) refreshSceneDebounced();
    autosave();
  }
  async function saveNow() {
    if (!S.clip || !S.dirty || S.saving) return;
    S.saving = true;
    renderSaveState();
    try {
      const sentData = clone(S.draft.data), sentTitle = S.draft.title;
      const res = await api.put(`/api/clips/${S.clip.id}`, { data: sentData, title: sentTitle, label: S.lastLabel });
      S.clip = res;
      // 저장 중 추가 수정이 없으면 서버 정규화본으로 교체
      if (JSON.stringify(sentData) === JSON.stringify(S.draft.data) && sentTitle === S.draft.title) {
        S.draft = { title: res.title, data: clone(res.data) };
        S.dirty = false;
      }
      S.saveErr = null;
      const i = S.clips.findIndex((c) => c.id === res.id);
      if (i >= 0) S.clips[i] = res;
    } catch (e) {
      S.saveErr = errMsg(e);
    } finally {
      S.saving = false;
      renderSaveState();
      renderBarButtons();
    }
    if (S.dirty) autosave();
  }
  async function flushSave() { if (S.dirty) await saveNow(); }

  async function undoRedo(kind) {
    if (!S.clip) return;
    await flushSave();
    const res = await api.post(`/api/clips/${S.clip.id}/${kind}`);
    S.clip = res;
    S.draft = { title: res.title, data: clone(res.data) };
    S.dirty = false;
    renderAll();
    refreshScene(true);
  }

  // ---------------------------------------------------------- 장면(서버 렌더러가 만든 PNG)
  let sceneSeq = 0;
  async function refreshScene() {
    if (!S.clip) return;
    const seq = ++sceneSeq;
    try {
      const sc = await api.post(`/api/clips/${S.clip.id}/scene`, { data: S.draft.data, title: S.draft.title });
      if (seq !== sceneSeq) return;
      S.scene = sc;
      S.sceneErr = null;
    } catch (e) {
      if (seq !== sceneSeq) return;
      S.sceneErr = errMsg(e);
    }
    layoutStage();
    renderWarnings();
    renderCueTimes();
  }
  const refreshSceneDebounced = debounce(refreshScene, 200);

  // ---------------------------------------------------------- 상단 바
  const saveState = h("span", { class: "small" });
  const undoBtn = h("button", { title: "실행 취소 (Ctrl+Z)", onclick: () => undoRedo("undo") }, "↶ 실행 취소");
  const redoBtn = h("button", { title: "다시 실행 (Ctrl+Shift+Z)", onclick: () => undoRedo("redo") }, "↷ 다시 실행");
  const saveBtn = h("button", { onclick: () => saveNow() }, "변경 저장");
  const titleInput = h("input", { type: "text", class: "title", placeholder: "쇼츠 제목(화면 상단에 표시)", oninput: (e) => { S.draft.title = e.target.value; markDirty("제목 수정"); } });
  const clipSelect = h("select", { onchange: (e) => openClip(e.target.value) });

  function renderSaveState() {
    saveState.className = "small badge " + (S.saveErr ? "err" : S.dirty ? "warn" : "ok");
    saveState.textContent = S.saveErr ? `저장 실패: ${S.saveErr}` : S.saving ? "저장 중…" : S.dirty ? "저장 안 됨" : "저장됨";
  }
  function renderBarButtons() {
    undoBtn.disabled = !S.clip || (!S.clip.undo_count && !S.dirty);
    redoBtn.disabled = !S.clip || !S.clip.redo_count || S.dirty;
    saveBtn.disabled = !S.clip || !S.dirty;
  }
  function renderBar() {
    clipSelect.replaceChildren(h("option", { value: "" }, S.clips.length ? "— 클립 선택 —" : "— 클립 없음(오른쪽·가운데에서 만들기) —"),
      ...S.clips.map((c) => h("option", { value: c.id, selected: S.clip?.id === c.id }, `${String(c.idx).padStart(2, "0")}. ${c.title}`)));
    titleInput.value = S.draft?.title ?? "";
    titleInput.disabled = !S.clip;
    el.bar.replaceChildren(
      h("a", { href: "#/projects" }, "← 프로젝트"),
      h("b", {}, S.project.title),
      h("span", { class: "muted small" }, S.project.source ? `${fmtMs(S.project.source.duration_ms, false)} · ${S.project.source.width}×${S.project.source.height}` : ""),
      clipSelect, titleInput, saveState, undoBtn, redoBtn, saveBtn,
      h("button", { disabled: !S.clip, onclick: () => startRender(true), title: "저해상도(540×960)로 실제 렌더링해 최종 결과를 확인" }, "확정 미리보기"),
      h("button", { class: "primary", disabled: !S.clip, onclick: () => startRender(false) }, "MP4 내보내기"),
    );
    renderSaveState();
    renderBarButtons();
  }

  // ---------------------------------------------------------- 왼쪽: 9:16 미리보기
  const stage = h("div", { class: "stage", tabindex: "0" });
  const bgImg = h("img", { class: "layer", alt: "" });
  const vwrap = h("div", { class: "vwrap" });
  const video = h("video", { preload: "auto", playsinline: true });
  vwrap.append(video);
  const fgImg = h("img", { class: "layer", alt: "" });
  const cueImg = h("img", { class: "cue", alt: "" });
  const notice = h("div", { class: "notice", hidden: true });
  stage.append(bgImg, vwrap, fgImg, cueImg, notice);
  const scrub = h("input", { type: "range", min: 0, max: 1000, step: 1, value: 0 });
  const playBtn = h("button", { onclick: () => togglePlay() }, "▶ 재생");
  const timeLabel = h("span", { class: "times" });
  const safeChk = h("input", { type: "checkbox", checked: true, onchange: () => layoutStage() });
  const warnBox = h("div");
  let k = 0.3;

  video.addEventListener("error", () => {
    S.videoError = "브라우저가 이 원본 코덱을 재생하지 못합니다. 편집은 가능하며 ‘확정 미리보기’로 실제 결과를 확인하세요.";
    layoutStage();
  });

  function stageSize() {
    const paneW = el.left.clientWidth - 24;
    const avail = Math.max(320, window.innerHeight - 52 - 50 - 150);
    return Math.max(180, Math.min(paneW, avail * 9 / 16));
  }

  function layoutStage() {
    const w = stageSize();
    k = w / CANVAS_W;
    stage.style.width = w + "px";
    stage.style.height = w * 16 / 9 + "px";
    for (const n of [...stage.querySelectorAll(".sel, .safe, .safe-label, .guide")]) n.remove();
    if (!S.clip || !S.scene) {
      bgImg.src = ""; fgImg.src = ""; cueImg.hidden = true; vwrap.hidden = true;
      notice.hidden = false;
      notice.textContent = S.sceneErr || (S.clip ? "장면 준비 중…" : "클립을 선택하거나 만들면 9:16 미리보기가 나타납니다.");
      return;
    }
    notice.hidden = !S.videoError;
    notice.textContent = S.videoError || "";
    const sc = S.scene;
    bgImg.src = sc.background_url;
    fgImg.src = sc.foreground_url;
    const v = sc.video;
    vwrap.hidden = false;
    Object.assign(vwrap.style, { left: v.x * k + "px", top: v.y * k + "px", width: v.w * k + "px", height: v.h * k + "px" });
    const vk = (v.w / v.crop.w) * k;
    Object.assign(video.style, { width: v.src_w * vk + "px", height: v.src_h * vk + "px", left: -v.crop.x * vk + "px", top: -v.crop.y * vk + "px" });
    if (!video.src) video.src = `/api/projects/${pid}/source`;
    video.playbackRate = sc.speed;
    if ("preservesPitch" in video) video.preservesPitch = true;
    updateCueOverlay();
    // 안전영역(편집 가능한 안내선, 플랫폼 공식 규격 아님)
    const sa = sc.safe_area;
    if (safeChk.checked && sa?.show !== false) {
      const add = (x, y, w2, h2, label) => {
        stage.append(h("div", { class: "safe", style: { left: x * k + "px", top: y * k + "px", width: w2 * k + "px", height: h2 * k + "px" } }));
        stage.append(h("div", { class: "safe-label", style: { left: (x + 6) * k + "px", top: (y + 4) * k + "px" } }, label));
      };
      add(0, 0, CANVAS_W, sa.top, "상단 UI 가능 영역");
      add(0, CANVAS_H - sa.bottom, CANVAS_W, sa.bottom, "하단 UI 가능 영역");
      add(CANVAS_W - sa.right, sa.top, sa.right, CANVAS_H - sa.top - sa.bottom, "버튼");
    }
    addSelectionBoxes();
  }

  function elementBox(name) {
    const st = S.draft.data.style, sc = S.scene;
    if (name === "video") { const b = st.video.box; return { x: b.x, y: b.y, w: b.w, h: b.h, resize: "wh" }; }
    if (name === "title" && st.title.enabled) {
      const tb = sc.title?.text_box; const b = st.title.box;
      return { x: b.x, y: tb ? tb.y : b.y, w: b.w, h: tb ? tb.h : 80, resize: "w" };
    }
    if (name === "subtitle") {
      const c = currentSceneCue() || sc.cues[0];
      const b = st.subtitle.box;
      const tb = c?.text_box;
      return { x: b.x, y: tb ? tb.y : b.y, w: b.w, h: tb ? tb.h : 80, resize: "w" };
    }
    if (name === "fixed_text" && st.fixed_text.enabled && st.fixed_text.text) {
      const b = st.fixed_text.box; return { x: b.x, y: b.y, w: b.w, h: st.fixed_text.size * 1.4, resize: "w" };
    }
    if (name === "logo" && st.logo.enabled && st.logo.asset_id) return { x: st.logo.x, y: st.logo.y, w: st.logo.w, h: st.logo.w * 0.5, resize: "w" };
    return null;
  }
  const ELEMENT_LABEL = { video: "영상", title: "제목", subtitle: "자막", fixed_text: "고정문구", logo: "로고" };

  function addSelectionBoxes() {
    for (const name of ["video", "title", "subtitle", "fixed_text", "logo"]) {
      const b = elementBox(name);
      if (!b) continue;
      const box = h("div", { class: "sel" + (S.sel === name ? " active" : ""), style: { left: b.x * k + "px", top: b.y * k + "px", width: b.w * k + "px", height: b.h * k + "px" } },
        h("div", { class: "tag" }, ELEMENT_LABEL[name]), h("div", { class: "h" }));
      box.addEventListener("pointerdown", (e) => startDrag(e, name, b, e.target.classList.contains("h")));
      stage.append(box);
    }
  }

  function movePos(name, dx, dy) {
    const st = S.draft.data.style;
    if (name === "video") { st.video.box.x = Math.round(st.video.box.x + dx); st.video.box.y = Math.round(st.video.box.y + dy); }
    else if (name === "logo") { st.logo.x = Math.round(st.logo.x + dx); st.logo.y = Math.round(st.logo.y + dy); }
    else {
      const target = name === "subtitle" && S.cueScope === "cue" && currentCue() ? ensureCueOverride(currentCue(), st.subtitle) : st[name];
      target.box.x = Math.round(target.box.x + dx); target.box.y = Math.round(target.box.y + dy);
    }
  }

  function startDrag(e, name, b, resize) {
    e.preventDefault();
    e.stopPropagation();
    S.sel = name;
    S.styleEl = name;
    S.rightTab = "style";
    renderRight();
    const box = e.currentTarget;
    box.setPointerCapture(e.pointerId);
    const sx = e.clientX, sy = e.clientY;
    const st = S.draft.data.style;
    const orig = clone(st);
    const origCue = currentCue() ? clone(currentCue().style_override || null) : null;
    let guide = null;
    const onMove = (ev) => {
      let dx = (ev.clientX - sx) / k, dy = (ev.clientY - sy) / k;
      S.draft.data.style = clone(orig);
      if (currentCue()) currentCue().style_override = clone(origCue);
      if (resize) {
        const s2 = S.draft.data.style;
        if (name === "video") { s2.video.box.w = Math.max(100, Math.round(orig.video.box.w + dx)); s2.video.box.h = Math.max(100, Math.round(orig.video.box.h + dy)); }
        else if (name === "logo") s2.logo.w = Math.max(16, Math.round(orig.logo.w + dx));
        else {
          const t = name === "subtitle" && S.cueScope === "cue" && currentCue() ? ensureCueOverride(currentCue(), s2.subtitle) : s2[name];
          t.box.w = Math.max(120, Math.round(getPath(orig, name).box.w + dx));
        }
        box.style.width = (b.w + dx) * k + "px";
        if (name === "video") box.style.height = (b.h + dy) * k + "px";
        return;
      }
      // 중앙 스냅
      const cx = b.x + dx + b.w / 2;
      guide?.remove(); guide = null;
      if (Math.abs(cx - CANVAS_W / 2) < 12 && !ev.altKey) {
        dx = CANVAS_W / 2 - b.w / 2 - b.x;
        guide = h("div", { class: "guide", style: { left: (CANVAS_W / 2) * k + "px", top: 0, width: "1px", height: "100%" } });
        stage.append(guide);
      }
      movePos(name, dx, dy);
      box.style.left = (b.x + dx) * k + "px";
      box.style.top = (b.y + dy) * k + "px";
      if (name === "subtitle" && !cueImg.hidden) cueImg.style.transform = `translate(${dx * k}px, ${dy * k}px)`;
    };
    const onUp = () => {
      box.removeEventListener("pointermove", onMove);
      box.removeEventListener("pointerup", onUp);
      guide?.remove();
      cueImg.style.transform = "";
      markDirty(resize ? `${ELEMENT_LABEL[name]} 크기 조정` : `${ELEMENT_LABEL[name]} 위치 이동`);
      renderRight();
      stage.focus();
    };
    box.addEventListener("pointermove", onMove);
    box.addEventListener("pointerup", onUp);
  }

  function currentSceneCue() {
    if (!S.scene) return null;
    return S.scene.cues.find((c) => S.outTime >= c.out_start_ms && S.outTime < c.out_end_ms) || null;
  }
  function currentCue() {
    const id = S.currentCueId;
    return id ? S.draft?.data.cues.find((c) => c.id === id) : null;
  }
  function ensureCueOverride(cue, base) {
    if (!cue.style_override) cue.style_override = {};
    if (!cue.style_override.box) cue.style_override.box = clone(base.box);
    return cue.style_override;
  }

  function updateCueOverlay() {
    const c = currentSceneCue();
    if (!c) { cueImg.hidden = true; return; }
    cueImg.hidden = false;
    if (cueImg.getAttribute("src") !== c.url) cueImg.src = c.url;
    Object.assign(cueImg.style, { left: c.x * k + "px", top: c.y * k + "px", width: c.w * k + "px", height: c.h * k + "px" });
    if (S.currentCueId !== c.id && !S.playing) { /* 정지 중에는 사용자가 고른 문장을 유지 */ }
    if (S.playing && S.currentCueId !== c.id) { S.currentCueId = c.id; highlightCue(); }
  }

  // 시간 매핑(서버 EDL과 같은 세그먼트 사용)
  function srcToOut(srcMs) {
    for (const s of S.scene.segments) if (srcMs >= s.src_start && srcMs <= s.src_start + s.dur) return (s.edit_start + srcMs - s.src_start) / S.scene.speed;
    return null;
  }
  function outToSrc(outMs) {
    const e = outMs * S.scene.speed;
    for (const s of S.scene.segments) if (e >= s.edit_start && e <= s.edit_start + s.dur) return s.src_start + (e - s.edit_start);
    const last = S.scene.segments[S.scene.segments.length - 1];
    return last ? last.src_start + last.dur : 0;
  }
  function seekOut(outMs) {
    if (!S.scene) return;
    S.outTime = Math.max(0, Math.min(outMs, S.scene.output_ms - 1));
    try { video.currentTime = outToSrc(S.outTime) / 1000; } catch {}
    updateTransport();
    updateCueOverlay();
  }
  function updateTransport() {
    if (!S.scene) { timeLabel.textContent = ""; return; }
    scrub.max = Math.round(S.scene.output_ms);
    scrub.value = Math.round(S.outTime);
    const src = outToSrc(S.outTime);
    timeLabel.textContent = `출력 ${fmtMs(S.outTime)} / ${fmtMs(S.scene.output_ms)} · 원본 ${fmtMs(src)} · ${S.scene.speed}배`;
  }
  let raf = 0;
  function tick() {
    if (!S.playing || !S.scene) return;
    const src = video.currentTime * 1000;
    const segs = S.scene.segments;
    let seg = segs.find((s) => src >= s.src_start - 1 && src < s.src_start + s.dur);
    if (!seg) {
      const next = segs.find((s) => s.src_start > src);
      if (next) { video.currentTime = next.src_start / 1000; seg = next; }
      else { pause(); seekOut(S.scene.output_ms - 1); return; }
    }
    S.outTime = (seg.edit_start + Math.max(0, src - seg.src_start)) / S.scene.speed;
    updateTransport();
    updateCueOverlay();
    raf = requestAnimationFrame(tick);
  }
  async function togglePlay() {
    if (!S.scene) return;
    if (S.playing) return pause();
    if (S.outTime >= S.scene.output_ms - 50) seekOut(0);
    video.playbackRate = S.scene.speed;
    try { await video.play(); } catch (e) { S.videoError = "재생할 수 없습니다: " + e.message; layoutStage(); return; }
    S.playing = true;
    playBtn.textContent = "❚❚ 정지";
    raf = requestAnimationFrame(tick);
  }
  function pause() {
    S.playing = false;
    video.pause();
    cancelAnimationFrame(raf);
    playBtn.textContent = "▶ 재생";
  }
  scrub.addEventListener("input", () => { pause(); seekOut(Number(scrub.value)); });

  function renderLeft() {
    el.left.replaceChildren(
      h("div", { class: "phead row" }, h("b", {}, "9:16 미리보기"), h("div", { class: "spacer" }), h("label", { class: "small row" }, safeChk, "안전영역")),
      h("div", { class: "stage-wrap" }, stage,
        h("div", { class: "transport" }, h("div", { class: "row" }, playBtn,
          h("button", { class: "small", onclick: () => seekOut(S.outTime - 1000) }, "-1초"), h("button", { class: "small", onclick: () => seekOut(S.outTime + 1000) }, "+1초"), timeLabel), scrub),
        h("div", { class: "small muted" }, "미리보기의 제목·자막 이미지는 MP4 렌더러가 쓰는 것과 같은 파일입니다. 상자를 끌어 이동, 오른쪽 아래 모서리로 크기 조정, 가운데 근처에서 자동 정렬(Alt 누르면 해제)."),
        warnBox));
    layoutStage();
    updateTransport();
    renderWarnings();
  }
  function renderWarnings() {
    const ws = [...(S.scene?.warnings || [])];
    const c = currentSceneCue();
    if (c) ws.push(...c.warnings.map((w) => ({ ...w, element: "현재 자막" })));
    const longCues = (S.scene?.cues || []).filter((x) => x.warnings.some((w) => w.code === "too_many_lines" || w.code === "out_of_canvas"));
    warnBox.replaceChildren(
      ...ws.map((w) => h("div", { class: "warnbox" }, (w.element ? `[${{ title: "제목", fixed_text: "고정문구" }[w.element] || w.element}] ` : "") + w.message)),
      longCues.length ? h("div", { class: "warnbox" }, `넘침 경고가 있는 자막 ${longCues.length}개 — 가운데 목록에서 ‘⚠’ 표시를 확인하세요.`) : null,
    );
  }

  // ---------------------------------------------------------- 가운데: 자막·전사
  const midBody = h("div", { class: "pbody" });
  function renderMid() {
    el.mid.replaceChildren(
      h("div", { class: "phead" },
        h("div", { class: "tabs" },
          h("button", { class: S.midTab === "clip" ? "active" : "", onclick: () => { S.midTab = "clip"; renderMid(); } }, "클립 자막"),
          h("button", { class: S.midTab === "transcript" ? "active" : "", onclick: () => { S.midTab = "transcript"; renderMid(); } }, "전사문·구간 선택")),
        h("input", { type: "search", placeholder: "문장 검색", value: S.filter, style: { width: "100%", marginTop: "6px" }, oninput: (e) => { S.filter = e.target.value; renderMidBody(); } })),
      midBody);
    renderMidBody();
  }
  function renderMidBody() {
    if (S.midTab === "transcript" || !S.clip) return renderTranscript();
    renderClipCues();
  }

  function adjustSpans(spans, oldText, newText) {
    let p = 0;
    while (p < oldText.length && p < newText.length && oldText[p] === newText[p]) p++;
    let s = 0;
    while (s < oldText.length - p && s < newText.length - p && oldText[oldText.length - 1 - s] === newText[newText.length - 1 - s]) s++;
    const delta = newText.length - oldText.length;
    const oldEditEnd = oldText.length - s;
    const out = [];
    for (const [a, b] of spans || []) {
      if (b <= p) out.push([a, b]);
      else if (a >= oldEditEnd) out.push([a + delta, b + delta]);
      else if (a < p && b > oldEditEnd) out.push([a, b + delta]);
    }
    return out.filter(([a, b]) => b > a && a >= 0 && b <= newText.length);
  }

  function cueOutRange(cue) {
    return S.scene?.cues.find((c) => c.id === cue.id);
  }

  function renderClipCues() {
    const cues = S.draft.data.cues;
    const f = S.filter.trim();
    const list = cues.filter((c) => !f || c.text.includes(f));
    midBody.replaceChildren(
      h("div", { class: "infobox" }, "글자 수정은 자막 텍스트만 바꿉니다(영상·음성 그대로). 그 말 자체를 영상에서 빼려면 ‘발화 삭제’를 누르세요 — 되돌릴 수 있습니다."),
      !cues.length ? h("div", { class: "warnbox" }, "이 클립 구간에 자막이 없습니다. ‘전사문·구간 선택’ 탭에서 SRT를 불러오거나 수동 자막을 입력한 뒤 ‘전사문에서 자막 다시 가져오기’를 누르세요.") : null,
      h("div", { class: "row", style: { margin: "6px 0" } },
        h("button", { class: "small", onclick: async () => { await flushSave(); const r = await api.post(`/api/clips/${S.clip.id}/reload-cues`); applyServerClip(r); } }, "전사문에서 자막 다시 가져오기"),
        h("button", { class: "small", onclick: () => addCueAtPlayhead() }, "현재 위치에 자막 추가")),
      ...list.map((cue) => cueItem(cue)));
    highlightCue();
  }

  function addCueAtPlayhead() {
    const src = Math.round(outToSrc(S.outTime));
    const cue = { id: "c_" + Math.random().toString(16).slice(2, 12), start_ms: src, end_ms: Math.min(S.draft.data.range.end_ms, src + 2000), text: "새 자막", emphasis: [], style_override: null, deleted_speech: false };
    S.draft.data.cues.push(cue);
    S.draft.data.cues.sort((a, b) => a.start_ms - b.start_ms);
    S.currentCueId = cue.id;
    markDirty("자막 추가");
    renderClipCues();
  }

  function cueItem(cue) {
    const ta = h("textarea", { rows: Math.min(4, cue.text.split("\n").length + 1) }, cue.text);
    ta.addEventListener("input", () => {
      cue.emphasis = adjustSpans(cue.emphasis, cue.text, ta.value);
      cue.text = ta.value;
      markDirty("자막 텍스트 교정");
    });
    ta.addEventListener("focus", () => { S.currentCueId = cue.id; highlightCue(); seekToCue(cue); });
    const out = cueOutRange(cue);
    const nudge = (field, d) => {
      cue[field] = Math.max(S.draft.data.range.start_ms, Math.min(S.draft.data.range.end_ms, cue[field] + d));
      if (cue.end_ms <= cue.start_ms) cue[field === "start_ms" ? "start_ms" : "end_ms"] -= d;
      markDirty("자막 시각 조정");
      renderClipCues();
    };
    const hasWarn = out?.warnings?.some((w) => ["too_many_lines", "out_of_canvas", "missing_glyph"].includes(w.code));
    const item = h("div", { class: "cue" + (cue.deleted_speech ? " deleted" : "") + (S.currentCueId === cue.id ? " current" : ""), "data-cue": cue.id },
      h("div", { class: "meta" },
        h("span", { class: "tc", title: "이 문장으로 이동", onclick: () => { S.currentCueId = cue.id; seekToCue(cue); highlightCue(); } }, `원본 ${fmtMs(cue.start_ms)}–${fmtMs(cue.end_ms)}`),
        h("span", {}, out ? `출력 ${fmtMs(out.out_start_ms)}–${fmtMs(out.out_end_ms)}` : cue.deleted_speech ? "발화 삭제됨" : "출력 안 됨"),
        cue.style_override ? h("span", { class: "badge" }, "개별 스타일") : null,
        cue.emphasis?.length ? h("span", { class: "badge warn" }, `강조 ${cue.emphasis.length}`) : null,
        hasWarn ? h("span", { class: "flag", title: out.warnings.map((w) => w.message).join("\n") }, "⚠ 넘침/글리프") : null,
        out ? h("span", { class: "muted" }, `${out.lines.length}줄 · ${out.size}px`) : null),
      ta,
      h("div", { class: "actions" },
        h("button", { class: "small", title: "글자를 드래그로 선택한 뒤 누르세요", onclick: () => {
          const a = ta.selectionStart, b = ta.selectionEnd;
          if (a === b) return toast("강조할 글자를 먼저 선택하세요");
          cue.emphasis = [...(cue.emphasis || []), [a, b]];
          markDirty("강조 지정"); renderClipCues();
        } }, "강조"),
        h("button", { class: "small", disabled: !cue.emphasis?.length, onclick: () => {
          const a = ta.selectionStart, b = ta.selectionEnd;
          cue.emphasis = a === b ? [] : cue.emphasis.filter(([x, y]) => y <= a || x >= b);
          markDirty("강조 해제"); renderClipCues();
        } }, "강조 해제"),
        h("button", { class: "small", title: "커서 위치에서 줄을 바꿉니다", onclick: () => {
          const a = ta.selectionStart;
          const nt = cue.text.slice(0, a) + "\n" + cue.text.slice(a);
          cue.emphasis = adjustSpans(cue.emphasis, cue.text, nt); cue.text = nt;
          markDirty("수동 줄바꿈"); renderClipCues();
        } }, "줄바꿈"),
        h("button", { class: "small", title: "커서 위치에서 두 자막으로 나눕니다(시각은 글자 비율로 추정)", onclick: () => splitCue(cue, ta.selectionStart) }, "문장 분리"),
        h("button", { class: "small", onclick: () => mergeNext(cue) }, "다음과 병합"),
        h("span", { class: "small muted" }, "시작"), h("button", { class: "small", onclick: () => nudge("start_ms", -100) }, "-0.1"), h("button", { class: "small", onclick: () => nudge("start_ms", 100) }, "+0.1"),
        h("span", { class: "small muted" }, "끝"), h("button", { class: "small", onclick: () => nudge("end_ms", -100) }, "-0.1"), h("button", { class: "small", onclick: () => nudge("end_ms", 100) }, "+0.1"),
        h("button", { class: "small", onclick: () => { S.currentCueId = cue.id; S.cueScope = "cue"; S.styleEl = "subtitle"; S.sel = "subtitle"; S.rightTab = "style"; seekToCue(cue); renderRight(); highlightCue(); } }, "이 문장만 스타일"),
        h("button", { class: "small " + (cue.deleted_speech ? "" : "danger"), title: "이 자막 구간의 영상·음성을 삭제(비파괴, 되돌리기 가능)", onclick: () => toggleSpeech(cue) }, cue.deleted_speech ? "발화 복구" : "발화 삭제")));
    return item;
  }

  function splitCue(cue, pos) {
    if (pos <= 0 || pos >= cue.text.length) return toast("나눌 위치에 커서를 두세요");
    const ratio = pos / cue.text.length;
    const mid = Math.round(cue.start_ms + (cue.end_ms - cue.start_ms) * ratio);
    const second = { ...clone(cue), id: "c_" + Math.random().toString(16).slice(2, 12), start_ms: mid, text: cue.text.slice(pos).trim(),
      emphasis: (cue.emphasis || []).filter(([a]) => a >= pos).map(([a, b]) => [a - pos, b - pos]) };
    cue.text = cue.text.slice(0, pos).trim();
    cue.emphasis = (cue.emphasis || []).filter(([, b]) => b <= pos);
    cue.end_ms = mid;
    const i = S.draft.data.cues.indexOf(cue);
    S.draft.data.cues.splice(i + 1, 0, second);
    markDirty("문장 분리");
    renderClipCues();
  }
  function mergeNext(cue) {
    const cues = S.draft.data.cues;
    const i = cues.indexOf(cue);
    const nx = cues[i + 1];
    if (!nx) return;
    const off = cue.text.length + 1;
    cue.emphasis = [...(cue.emphasis || []), ...(nx.emphasis || []).map(([a, b]) => [a + off, b + off])];
    cue.text = cue.text + " " + nx.text;
    cue.end_ms = nx.end_ms;
    cues.splice(i + 1, 1);
    markDirty("문장 병합");
    renderClipCues();
  }
  async function toggleSpeech(cue) {
    await flushSave();
    try {
      const r = await api.post(`/api/clips/${S.clip.id}/cues/${cue.id}/delete-speech`, { restore: cue.deleted_speech });
      applyServerClip(r);
      toast(cue.deleted_speech ? "발화를 복구했습니다" : "발화 구간을 삭제했습니다 — 영상·음성·자막 시간이 함께 줄어듭니다. ‘실행 취소’로 되돌릴 수 있습니다.");
    } catch (e) { toast(errMsg(e), true); }
  }
  function applyServerClip(r) {
    S.clip = r;
    S.draft = { title: r.title, data: clone(r.data) };
    S.dirty = false;
    const i = S.clips.findIndex((c) => c.id === r.id);
    if (i >= 0) S.clips[i] = r;
    renderAll();
    refreshScene();
  }
  function seekToCue(cue) {
    if (!S.scene) return;
    const o = cueOutRange(cue);
    if (o) seekOut(o.out_start_ms + 1);
  }
  function highlightCue() {
    for (const n of midBody.querySelectorAll(".cue[data-cue]")) {
      const on = n.dataset.cue === S.currentCueId;
      n.classList.toggle("current", on);
      if (on && S.playing) n.scrollIntoView({ block: "nearest" });
    }
  }
  function renderCueTimes() { if (S.midTab === "clip" && S.clip && document.activeElement?.tagName !== "TEXTAREA") renderClipCues(); }

  // 전사문(프로젝트 전체)
  function renderTranscript() {
    const tr = S.transcript;
    const st = S.status;
    const srtIn = h("input", { type: "file", accept: ".srt,.vtt,text/vtt", hidden: true, onchange: async () => {
      const fd = new FormData(); fd.append("file", srtIn.files[0]);
      try {
        const r = await api.form(`/api/projects/${pid}/subtitles`, fd);
        toast(`자막 ${r.transcript.cues.length}개를 불러왔습니다 (${r.encoding})`);
        S.importIssues = r.issues;
        await reloadTranscript();
      } catch (e) { toast(errMsg(e), true); }
    } });
    const trJob = latestJob("transcribe");
    const sources = h("div", { class: "card", style: { marginBottom: "10px" } },
      h("div", { class: "row" },
        h("button", { onclick: () => srtIn.click() }, "SRT/VTT 불러오기"), srtIn,
        h("button", { onclick: manualDialog }, "수동 자막 입력"),
        h("button", { disabled: !st.transcribe.installed || isActive(trJob), onclick: async () => {
          if (!confirm(`로컬 자동 전사(한국어, ${st.transcribe.model})를 시작할까요?\n외부 API 요금은 없지만 PC 성능에 따라 영상 길이보다 오래 걸릴 수 있습니다.\n${st.transcribe.label}\n같은 영상·설정은 다시 전사하지 않고 저장된 결과를 재사용합니다.`)) return;
          try { await api.post(`/api/projects/${pid}/transcribe`, {}); toast("자동 전사를 시작했습니다"); } catch (e) { toast(errMsg(e), true); }
        } }, "자동 전사(로컬)"),
        tr.working ? h("a", { class: "small", href: `/api/projects/${pid}/transcript.srt` }, "작업본 SRT") : null,
        tr.original_meta ? h("a", { class: "small", href: `/api/projects/${pid}/transcript.srt?which=original` }, "원문 SRT") : null),
      h("div", { class: "small muted", style: { marginTop: "6px" } }, `전사 엔진: ${st.transcribe.installed ? "faster-whisper(로컬)" : "미설치"} · 모델 ${st.transcribe.model} — ${st.transcribe.label}`),
      trJob && (isActive(trJob) || trJob.status !== "succeeded") ? h("div", {}, jobProgress(trJob), trJob.error_message ? h("div", { class: "errbox" }, trJob.error_message) : null) : null,
      (S.importIssues || []).length ? h("div", { class: "warnbox" }, h("b", {}, `자막 검사 결과 ${S.importIssues.length}건`), h("ul", {}, S.importIssues.slice(0, 20).map((i) => h("li", {}, i.message)))) : null);

    const rangeBox = h("div", { class: "card", style: { marginBottom: "10px" } },
      h("b", {}, "수동 구간으로 클립 만들기"),
      h("div", { class: "small muted" }, "문장 왼쪽의 ‘시작’·‘끝’ 버튼으로 고르거나 시각을 직접 입력하세요(예: 12:34.5)."),
      rangeForm());

    if (!tr.working) {
      midBody.replaceChildren(sources, rangeBox, h("p", { class: "muted" }, "전사문이 없습니다. SRT/VTT를 불러오거나 수동 자막을 입력하거나 자동 전사를 실행하세요. 자막이 없어도 수동 구간으로 클립을 만들 수 있습니다."));
      return;
    }
    const cues = S.transcriptDraft;
    const origMap = new Map((tr.original_cues || []).map((c) => [c.id, c.text]));
    const sugBy = new Map();
    for (const s of tr.suggestions || []) { if (!sugBy.has(s.cue_id)) sugBy.set(s.cue_id, []); sugBy.get(s.cue_id).push(s); }
    const f = S.filter.trim();
    const shown = cues.filter((c) => !f || c.text.includes(f)).slice(0, 1500);
    midBody.replaceChildren(sources, rangeBox,
      h("div", { class: "row", style: { margin: "6px 0" } },
        h("span", { class: "small" }, `전사 작업본 v${tr.working.version} · ${cues.length}문장 · 출처 ${tr.working.origin}${tr.working.model ? " / " + tr.working.model : ""}`),
        h("div", { class: "spacer" }),
        h("button", { class: "small primary", disabled: !S.transcriptDirty, onclick: saveTranscript }, "교정 저장(새 버전)")),
      h("div", { class: "infobox" }, "전사문을 고쳐도 원본 음성은 바뀌지 않습니다. 원문 보존본은 따로 남습니다. 숫자·티커·저신뢰 문장은 표시를 확인하세요."),
      ...shown.map((c) => {
        const ta = h("textarea", { rows: 2 }, c.text);
        ta.addEventListener("input", () => { c.text = ta.value; S.transcriptDirty = true; });
        ta.addEventListener("change", () => renderMidBody());
        const sel = (S.rangeSel.a && c.start_ms >= S.rangeSel.a.start_ms && S.rangeSel.b && c.end_ms <= S.rangeSel.b.end_ms);
        const orig = origMap.get(c.id);
        return h("div", { class: "cue" + (sel ? " selected" : "") },
          h("div", { class: "meta" },
            h("span", { class: "tc" }, `${fmtMs(c.start_ms)}–${fmtMs(c.end_ms)}`),
            h("button", { class: "small", onclick: () => { S.rangeSel.a = c; if (S.rangeSel.b && S.rangeSel.b.end_ms <= c.start_ms) S.rangeSel.b = null; renderMidBody(); } }, "시작"),
            h("button", { class: "small", onclick: () => { S.rangeSel.b = c; if (S.rangeSel.a && S.rangeSel.a.start_ms >= c.end_ms) S.rangeSel.a = null; renderMidBody(); } }, "끝"),
            ...(c.flags || []).map((fl) => h("span", { class: "flag" }, { low_conf: "저신뢰", number: "숫자 확인", ticker: "티커 확인", overlap: "겹침", empty: "빈 문장", reversed: "시각 역전" }[fl] || fl))),
          ta,
          orig !== undefined && orig !== c.text ? h("div", { class: "orig" }, `원문: ${orig}`) : null,
          ...(sugBy.get(c.id) || []).map((s) => h("div", { class: "row small" }, h("span", { class: "flag" }, "사전 제안"), `‘${s.found}’ → ‘${s.suggestion}’ (${s.reason})`,
            h("button", { class: "small", onclick: () => { c.text = c.text.slice(0, s.start) + s.suggestion + c.text.slice(s.end); S.transcriptDirty = true; tr.suggestions = tr.suggestions.filter((x) => x !== s); renderMidBody(); } }, "적용"))));
      }),
      cues.length > shown.length ? h("p", { class: "muted small" }, "표시 개수를 1500개로 제한했습니다. 검색으로 좁히세요.") : null);
  }

  function rangeForm() {
    const a = h("input", { type: "text", style: { width: "110px" }, value: S.rangeSel.a ? fmtMs(S.rangeSel.a.start_ms) : "" });
    const b = h("input", { type: "text", style: { width: "110px" }, value: S.rangeSel.b ? fmtMs(S.rangeSel.b.end_ms) : "" });
    const t = h("input", { type: "text", placeholder: "클립 제목", style: { flex: 1, minWidth: "160px" }, value: S.rangeSel.a ? S.rangeSel.a.text.split("\n")[0].slice(0, 30) : "" });
    const len = () => { const x = parseTime(a.value), y = parseTime(b.value); return isNaN(x) || isNaN(y) ? "" : `길이 ${((y - x) / 1000).toFixed(1)}초`; };
    const lenEl = h("span", { class: "small muted" }, len());
    a.oninput = b.oninput = () => (lenEl.textContent = len());
    return h("div", { class: "row", style: { marginTop: "6px" } }, "시작", a, "끝", b, lenEl, t,
      h("button", { class: "primary small", onclick: async () => {
        const x = parseTime(a.value), y = parseTime(b.value);
        if (isNaN(x) || isNaN(y) || y <= x) return toast("시작·끝 시각을 확인하세요", true);
        try {
          const c = await api.post(`/api/projects/${pid}/clips`, { start_ms: x, end_ms: y, title: t.value });
          S.clips.push(c); S.rangeSel = { a: null, b: null }; S.midTab = "clip";
          await openClip(c.id);
          toast("클립을 만들었습니다");
        } catch (e) { toast(errMsg(e), true); }
      } }, "클립 만들기"));
  }

  async function saveTranscript() {
    try {
      await api.put(`/api/projects/${pid}/transcript`, { cues: S.transcriptDraft });
      toast("교정본을 새 버전으로 저장했습니다. 기존 클립 자막은 ‘전사문에서 자막 다시 가져오기’로 갱신할 수 있습니다.");
      await reloadTranscript();
    } catch (e) { toast(errMsg(e), true); }
  }
  async function reloadTranscript() {
    S.transcript = await api.get(`/api/projects/${pid}/transcript`);
    S.transcriptDraft = S.transcript.working ? clone(S.transcript.working.cues) : null;
    S.transcriptDirty = false;
    S.project = await api.get(`/api/projects/${pid}`);
    renderMid();
    renderRight();
  }
  function manualDialog() {
    const ta = h("textarea", { rows: 10, placeholder: "00:00:01.0 - 00:00:03.5 첫 문장\n3.5-6 두 번째 문장\n줄 안의 \\n 은 줄바꿈" });
    const dlg = h("dialog", {}, h("h3", {}, "수동 자막 입력"),
      h("p", { class: "small muted" }, "한 줄에 ‘시작 - 끝 문장’. 시각이 없는 줄은 동기화할 수 없어 받지 않습니다. 기존 작업본은 새 원문으로 대체됩니다(이전 버전은 보관)."), ta,
      h("div", { class: "row", style: { marginTop: "8px" } }, h("div", { class: "spacer" }), h("button", { onclick: () => dlg.close() }, "취소"),
        h("button", { class: "primary", onclick: async () => {
          try { await api.post(`/api/projects/${pid}/subtitles/manual`, { text: ta.value }); dlg.close(); await reloadTranscript(); toast("수동 자막을 저장했습니다"); }
          catch (e) { toast(errMsg(e), true); }
        } }, "저장")));
    document.body.append(dlg); dlg.showModal(); dlg.addEventListener("close", () => dlg.remove());
  }

  // ---------------------------------------------------------- 오른쪽 패널
  const rightBody = h("div", { class: "pbody" });
  function renderRight() {
    const tabs = [["ai", "AI 추천"], ["style", "스타일·템플릿"], ["range", "구간·속도"], ["export", "내보내기"]];
    el.right.replaceChildren(h("div", { class: "phead" }, h("div", { class: "tabs" }, tabs.map(([id, label]) =>
      h("button", { class: S.rightTab === id ? "active" : "", onclick: () => { S.rightTab = id; renderRight(); } }, label)))), rightBody);
    if (S.rightTab === "ai") renderAI();
    else if (S.rightTab === "style") renderStyle();
    else if (S.rightTab === "range") renderRange();
    else renderExport();
  }

  // AI 추천
  const recSettings = { min_s: 30, max_s: 60, count: 8 };
  function renderAI() {
    const st = S.status.ai;
    const job = latestJob("recommend");
    const num = (key, min, max) => h("input", { type: "number", min, max, value: recSettings[key], onchange: (e) => { recSettings[key] = Number(e.target.value); S.estimate = null; } });
    const hasTr = !!S.transcript.working;
    const latest = S.recs[0];
    rightBody.replaceChildren(
      h("div", { class: "card" },
        h("div", { class: "row" }, h("b", {}, "AI 구간 추천"), h("span", { class: "badge " + (st.connected ? "ai" : "") }, st.connected ? `연결됨 · ${st.model}` : "미연결")),
        !st.connected ? h("div", { class: "warnbox" }, "AI 제공자가 연결되지 않았습니다(.env의 ANTHROPIC_API_KEY). 가짜 추천은 만들지 않습니다. SRT·수동 자막·수동 구간·스타일 편집·MP4 출력은 그대로 쓸 수 있습니다.") : null,
        h("div", { class: "small muted" }, `외부 API 처리 · 비용 발생 · ${st.sends}`),
        h("div", { class: "form", style: { marginTop: "8px" } }, h("label", {}, "최소 길이(초)"), num("min_s", 10, 180), h("label", {}, "최대 길이(초)"), num("max_s", 15, 300), h("label", {}, "최대 후보 수"), num("count", 1, 20)),
        h("div", { class: "row", style: { marginTop: "8px" } },
          h("button", { disabled: !hasTr, onclick: async () => {
            try { S.estimate = await api.get(`/api/projects/${pid}/recommend/estimate?min_s=${recSettings.min_s}&max_s=${recSettings.max_s}&count=${recSettings.count}`); renderAI(); }
            catch (e) { toast(errMsg(e), true); }
          } }, "전송 내용·비용 확인"),
          h("button", { class: "primary", disabled: !st.connected || !hasTr || !S.estimate || isActive(job), onclick: () => runRecommend(false) }, "AI 추천 실행"),
          h("button", { class: "small", disabled: !st.connected || !hasTr || !S.estimate || isActive(job), onclick: () => runRecommend(true) }, "다시 분석(캐시 무시)")),
        !hasTr ? h("div", { class: "small muted" }, "먼저 전사문(SRT·수동 자막·자동 전사)이 필요합니다.") : null,
        S.estimate ? h("div", { class: "infobox" },
          h("div", {}, `제공자: Anthropic · 모델 ${S.estimate.status.model}`),
          h("div", {}, `보낼 데이터: 전사문 텍스트 ${S.estimate.cue_count}문장, 약 ${S.estimate.chars.toLocaleString()}자 (영상·음성 파일은 보내지 않음)`),
          h("div", {}, `입력 토큰: ${S.estimate.input_tokens ?? "확인 불가(미연결)"} · 출력 최대 ${S.estimate.max_output_tokens} 토큰`),
          h("div", {}, `예상 요금: ${S.estimate.cost}`),
          S.estimate.cached_recommendation_id ? h("div", {}, "같은 전사·설정의 이전 결과가 있어 다시 요금을 내지 않고 재사용합니다.") : null,
          S.estimate.estimate_error ? h("div", { class: "errbox" }, S.estimate.estimate_error.message + (S.estimate.estimate_error.detail ? " — " + S.estimate.estimate_error.detail : "")) : null) : null,
        job ? jobProgress(job) : null,
        job?.error_message ? h("div", { class: "errbox" }, job.error_message) : null),
      h("div", { class: "row", style: { margin: "10px 0" } },
        h("button", { class: "small", disabled: !hasTr, onclick: async () => {
          try { await api.post(`/api/projects/${pid}/rule-candidates`, { settings: recSettings }); S.recs = await api.get(`/api/projects/${pid}/recommendations`); renderAI(); }
          catch (e) { toast(errMsg(e), true); }
        } }, "규칙 기반 후보 만들기(AI 아님, 무료)"),
        S.recs.length > 1 ? h("select", { onchange: (e) => { const r = S.recs.find((x) => x.id === e.target.value); S.recs = [r, ...S.recs.filter((x) => x !== r)]; renderAI(); } },
          S.recs.map((r) => h("option", { value: r.id }, `${fmtDate(r.created_at)} · ${r.provider === "rule" ? "규칙" : "AI " + r.model} · ${r.candidates.length}개`))) : null),
      latest ? recList(latest) : h("p", { class: "muted small" }, "추천 결과가 없습니다."));
  }
  async function runRecommend(force) {
    try { await api.post(`/api/projects/${pid}/recommend`, { settings: recSettings, force }); toast("AI 추천을 요청했습니다"); renderAI(); }
    catch (e) { toast(errMsg(e), true); }
  }
  function recList(rec) {
    const isAI = rec.provider !== "rule";
    const cueText = new Map((S.transcript.working?.cues || []).map((c) => [c.id, c.text]));
    return h("div", {},
      h("div", { class: "row small" }, isAI ? h("span", { class: "badge ai" }, `AI 추천 · ${rec.model}`) : h("span", { class: "badge" }, "규칙 기반 후보 — AI 판단 아님"),
        h("span", { class: "muted" }, fmtDate(rec.created_at)), rec.usage ? h("span", { class: "muted" }, `토큰 입력 ${rec.usage.input_tokens} / 출력 ${rec.usage.output_tokens}`) : null),
      rec.rejected?.length ? h("details", { class: "small" }, h("summary", {}, `검증에서 거부된 후보 ${rec.rejected.length}개`), h("ul", {}, rec.rejected.map((r) => h("li", {}, `#${r.index + 1}: ${r.reason}`)))) : null,
      !rec.candidates.length ? h("p", { class: "muted" }, "조건에 맞는 독립 구간이 없었습니다(개수를 억지로 채우지 않음).") : null,
      ...rec.candidates.map((c) => {
        let ti = 0;
        const radios = c.titles.map((t, i) => h("label", { class: "row small" }, h("input", { type: "radio", name: `t_${rec.id}_${c.rank}`, checked: i === 0, onchange: () => (ti = i) }), t));
        return h("div", { class: "cand" },
          h("div", { class: "row" }, h("b", {}, `#${c.rank}`), h("span", { class: "small" }, `원본 ${fmtMs(c.start_ms)}–${fmtMs(c.end_ms)} · ${(c.duration_ms / 1000).toFixed(1)}초`),
            c.score != null ? h("span", { class: "badge ai", title: c.score_note }, `점수 ${c.score} (모델 평가)`) : null, c.topic ? h("span", { class: "badge" }, c.topic) : null),
          ...radios,
          c.summary ? h("div", { class: "small" }, c.summary) : null,
          c.reason ? h("div", { class: "small muted" }, `이유: ${c.reason}`) : null,
          ...(c.cautions || []).map((x) => h("div", { class: "warnbox" }, x)),
          h("details", { class: "small" }, h("summary", {}, `근거 문장 ${c.evidence_cue_ids.length}개`), h("div", { class: "muted" }, c.evidence_cue_ids.map((id) => cueText.get(id) || "(전사문이 바뀌어 찾을 수 없음)").join(" / "))),
          h("div", { class: "row", style: { marginTop: "6px" } }, h("button", { class: "small primary", onclick: async () => {
            try {
              const clip = await api.post(`/api/projects/${pid}/clips/from-candidate`, { recommendation_id: rec.id, rank: c.rank, title_index: ti });
              S.clips.push(clip); await openClip(clip.id); toast("후보로 클립을 만들었습니다");
            } catch (e) { toast(errMsg(e), true); }
          } }, "이 구간으로 클립 만들기")));
      }));
  }

  // 스타일
  function renderStyle() {
    if (!S.clip) { rightBody.replaceChildren(h("p", { class: "muted" }, "클립을 선택하세요.")); return; }
    const els = [["video", "영상"], ["title", "제목"], ["subtitle", "일반 자막"], ["emphasis", "강조 자막"], ["fixed_text", "고정문구"], ["logo", "로고"], ["canvas", "배경"], ["safe_area", "안전영역"]];
    const st = S.draft.data.style;
    rightBody.replaceChildren(
      h("div", { class: "tabs", style: { marginBottom: "8px" } }, els.map(([id, label]) => h("button", { class: S.styleEl === id ? "active" : "", onclick: () => { S.styleEl = id; if (ELEMENT_LABEL[id]) S.sel = id; renderRight(); layoutStage(); } }, label))),
      styleForm(S.styleEl, st),
      templateBox());
  }

  const FONT_WEIGHTS = () => S.fonts.map((f) => [f.id, f.name]);
  function textFields(withText) {
    return [
      ["enabled", "사용", "check"], ...(withText ? [["text", "문구", "text"]] : []),
      ["font", "글꼴", "select", FONT_WEIGHTS()], ["size", "크기(px)", "num", { min: 12, max: 200 }], ["bold", "굵게", "check"],
      ["color", "글자색", "color"], ["letter_spacing", "자간", "num", { min: -10, max: 30, step: 0.5 }], ["line_height", "행간(배)", "num", { min: 0.8, max: 2.5, step: 0.05 }],
      ["align", "정렬", "select", [["left", "왼쪽"], ["center", "가운데"], ["right", "오른쪽"]]],
      ["stroke_width", "외곽선 두께", "num", { min: 0, max: 20 }], ["stroke_color", "외곽선 색", "color"],
      ["shadow.enabled", "그림자", "check"], ["shadow.dx", "그림자 X", "num"], ["shadow.dy", "그림자 Y", "num"], ["shadow.color", "그림자 색", "color"], ["shadow.opacity", "그림자 불투명", "num", { min: 0, max: 1, step: 0.05 }], ["shadow.blur", "그림자 흐림", "num", { min: 0, max: 20 }],
      ["bg.enabled", "배경 상자", "check"], ["bg.mode", "배경 방식", "select", [["block", "전체 묶음"], ["line", "줄마다"]]], ["bg.color", "배경색", "color"], ["bg.opacity", "배경 불투명", "num", { min: 0, max: 1, step: 0.05 }],
      ["bg.pad_x", "가로 여백", "num", { min: 0, max: 120 }], ["bg.pad_y", "세로 여백", "num", { min: 0, max: 80 }], ["bg.radius", "모서리 반경", "num", { min: 0, max: 80 }],
      ["box.x", "X", "num"], ["box.y", "Y", "num"], ["box.w", "너비", "num", { min: 100, max: 1080 }],
      ["anchor_y", "Y 기준", "select", [["top", "윗변"], ["center", "가운데"], ["bottom", "아랫변"]]],
      ["max_lines", "최대 줄 수", "num", { min: 1, max: 6 }], ["auto_shrink", "넘치면 자동 축소", "check"], ["min_size", "최소 크기", "num", { min: 10, max: 200 }],
    ];
  }
  function styleForm(name, st) {
    let target = st[name], fields = [], note = null, reset = null;
    const cue = currentCue();
    if (name === "title") fields = textFields(false);
    else if (name === "subtitle") {
      fields = textFields(false);
      if (S.cueScope === "cue" && cue) {
        const merged = deepMerge(st.subtitle, cue.style_override || {});
        target = new Proxy(merged, {});
        note = h("div", {},
          h("div", { class: "infobox" }, `적용 범위: 현재 문장만 — “${cue.text.slice(0, 24)}”`),
          h("div", { class: "row" }, h("button", { class: "small", onclick: () => { S.cueScope = "clip"; renderRight(); } }, "클립 전체로 전환"),
            h("button", { class: "small", disabled: !cue.style_override, onclick: () => { cue.style_override = null; markDirty("개별 자막 스타일 해제"); renderRight(); } }, "개별 스타일 해제")));
        return h("div", {}, note, buildForm(fields, merged, (path, v) => { cue.style_override = cue.style_override || {}; setPath(cue.style_override, path, v); markDirty("현재 문장 스타일"); }));
      }
      note = h("div", { class: "row small" }, h("span", { class: "badge" }, "적용 범위: 클립 전체"),
        cue ? h("button", { class: "small", onclick: () => { S.cueScope = "cue"; renderRight(); } }, "현재 문장만 바꾸기") : h("span", { class: "muted" }, "(가운데 목록에서 문장을 선택하면 개별 스타일 가능)"),
        h("span", { class: "muted" }, "템플릿 전체에 반영하려면 아래 ‘템플릿 업데이트’"));
    } else if (name === "fixed_text") fields = textFields(true);
    else if (name === "emphasis") {
      fields = [["color", "강조 색", "color"], ["bold", "굵게", "check"], ["scale", "크기 배율", "num", { min: 0.7, max: 1.6, step: 0.05 }], ["bg_enabled", "강조 배경", "check"], ["bg_color", "강조 배경색", "color"]];
      note = h("div", { class: "small muted" }, "가운데 목록에서 글자를 선택하고 ‘강조’를 누르면 그 부분만 이 스타일로 출력됩니다. 강조 애니메이션(팝업·밑줄 슬라이드) ", h("span", { class: "badge soon" }, "준비 중"), " — 출력과 일치가 보장된 색·굵기·크기만 제공합니다.");
    } else if (name === "video") {
      fields = [["fit", "맞춤 방식", "select", [["contain", "전체 보존(기본, 자료 잘림 없음)"], ["cover", "확대 배치(가장자리 손실)"]]],
        ["box.x", "X", "num"], ["box.y", "Y", "num"], ["box.w", "너비", "num", { min: 100, max: 2000 }], ["box.h", "높이", "num", { min: 100, max: 1920 }],
        ["crop.enabled", "사용자 지정 크롭", "check"], ["crop.x", "크롭 X(0~1)", "num", { min: 0, max: 1, step: 0.01 }], ["crop.y", "크롭 Y(0~1)", "num", { min: 0, max: 1, step: 0.01 }],
        ["crop.w", "크롭 너비(0~1)", "num", { min: 0.05, max: 1, step: 0.01 }], ["crop.h", "크롭 높이(0~1)", "num", { min: 0.05, max: 1, step: 0.01 }]];
      note = h("div", {}, h("div", { class: "small muted" }, "기본은 원본 전체 보존입니다. 얼굴 자동 크롭·자동 추적은 사용하지 않습니다. 크롭·확대·가리기는 선택한 영역 밖 정보가 출력되지 않습니다."), masksEditor(st.video));
    } else if (name === "logo") {
      const logos = S.assets.filter((a) => a.kind === "logo");
      fields = [["enabled", "사용", "check"], ["asset_id", "로고 파일", "select", [["", "(없음)"], ...logos.map((a) => [a.id, a.filename])]], ["x", "X", "num"], ["y", "Y", "num"], ["w", "너비", "num", { min: 16, max: 1080 }], ["opacity", "불투명", "num", { min: 0, max: 1, step: 0.05 }]];
      note = h("div", { class: "small muted" }, logos.length ? "" : "등록된 로고가 없습니다. ‘템플릿·에셋’ 화면에서 직접 만든 로고를 등록하세요.");
    } else if (name === "canvas") {
      const bgs = S.assets.filter((a) => a.kind === "background");
      fields = [["bg_color", "배경색", "color"], ["bg_asset_id", "배경 이미지", "select", [["", "(없음)"], ...bgs.map((a) => [a.id, a.filename])]]];
    } else if (name === "safe_area") {
      fields = [["show", "표시", "check"], ["top", "상단(px)", "num"], ["bottom", "하단(px)", "num"], ["right", "오른쪽(px)", "num"]];
      note = h("div", { class: "small muted" }, "플랫폼 버튼·설명이 덮을 수 있는 영역을 보여주는 편집용 안내선입니다(플랫폼 공식 고정 규격 아님). 출력 영상에는 그려지지 않습니다.");
    }
    if (ELEMENT_LABEL[name] || name === "emphasis" || name === "canvas") {
      reset = h("button", { class: "small", onclick: async () => {
        const t = S.draft.data.template;
        const tpl = t?.id ? await api.get(`/api/templates/${t.id}`).catch(() => null) : null;
        if (!tpl) return toast("기준 템플릿을 찾을 수 없습니다", true);
        const base = tpl.versions.includes(t.version) ? null : tpl.data;
        const data = base || (await fetchTemplateVersion(t.id, t.version));
        st[name] = clone(data[name]);
        markDirty(`${name} 기본값 복구`); renderRight();
      } }, "이 요소 템플릿 값으로 복구");
    }
    return h("div", {}, note, buildForm(fields, target, (path, v) => { setPath(target, path, v); markDirty("스타일 변경"); }), h("div", { class: "row", style: { marginTop: "6px" } }, reset,
      ELEMENT_LABEL[name] ? h("span", { class: "small muted" }, "미세 이동: 미리보기 클릭 후 방향키(Shift=10px)") : null));
  }
  async function fetchTemplateVersion(tid, v) {
    // 클립이 적용한 시점의 버전 데이터(서버 미리보기 API와 같은 데이터)
    const tpl = await api.get(`/api/templates/${tid}`);
    return tpl.current_version === v ? tpl.data : (await api.get(`/api/templates/${tid}?v=${v}`)).data;
  }
  function deepMerge(a, b) {
    const out = clone(a);
    for (const [k2, v] of Object.entries(b || {})) out[k2] = v && typeof v === "object" && !Array.isArray(v) && typeof out[k2] === "object" ? deepMerge(out[k2], v) : clone(v);
    return out;
  }
  function buildForm(fields, target, onChange) {
    const form = h("div", { class: "form" });
    for (const [path, label, type, opt] of fields) {
      const val = getPath(target, path);
      let input;
      if (type === "check") input = h("input", { type: "checkbox", checked: !!val, onchange: (e) => onChange(path, e.target.checked) });
      else if (type === "color") input = h("div", { class: "row" },
        h("input", { type: "color", value: (val || "#000000").slice(0, 7), oninput: (e) => { e.target.nextSibling.value = e.target.value; onChange(path, e.target.value); } }),
        h("input", { type: "text", value: val || "", style: { width: "90px" }, onchange: (e) => onChange(path, e.target.value) }));
      else if (type === "select") input = h("select", { onchange: (e) => onChange(path, e.target.value || null) }, (opt || []).map(([v, l]) => h("option", { value: v, selected: String(val ?? "") === String(v) }, l)));
      else if (type === "text") input = h("input", { type: "text", value: val || "", oninput: (e) => onChange(path, e.target.value) });
      else input = h("input", { type: "number", value: val ?? 0, min: opt?.min, max: opt?.max, step: opt?.step ?? 1, onchange: (e) => { const n = Number(e.target.value); if (!isNaN(n)) onChange(path, n); } });
      form.append(h("label", {}, label), input);
    }
    return form;
  }
  function masksEditor(vstyle) {
    const masks = vstyle.masks || (vstyle.masks = []);
    return h("div", { class: "card", style: { margin: "8px 0" } },
      h("div", { class: "row" }, h("b", { class: "small" }, "가리기 영역(원본에 박힌 자막 등)"), h("div", { class: "spacer" }),
        h("button", { class: "small", onclick: () => { const v = S.scene.video; masks.push({ x: v.x, y: Math.round(v.y + v.h * 0.82), w: v.w, h: Math.round(v.h * 0.18), color: "#000000", opacity: 1 }); markDirty("가리기 영역 추가"); renderRight(); } }, "추가")),
      h("div", { class: "small muted" }, "가린 부분의 정보는 출력에서 보이지 않습니다. 기존 자막을 지우거나 복원하는 기능이 아닙니다."),
      ...masks.map((m, i) => h("div", { class: "row small" }, `#${i + 1}`,
        ...["x", "y", "w", "h"].map((kk) => h("input", { type: "number", value: m[kk], style: { width: "64px" }, onchange: (e) => { m[kk] = Number(e.target.value); markDirty("가리기 영역 수정"); } })),
        h("input", { type: "color", value: m.color, oninput: (e) => { m.color = e.target.value; markDirty("가리기 영역 수정"); } }),
        h("button", { class: "small danger", onclick: () => { masks.splice(i, 1); markDirty("가리기 영역 삭제"); renderRight(); } }, "삭제"))));
  }

  function templateBox() {
    const t = S.draft.data.template || {};
    const sel = h("select", {}, S.templates.map((x) => h("option", { value: x.id, selected: x.id === t.id }, `${x.name} (v${x.current_version})`)));
    const mode = h("select", {}, h("option", { value: "keep" }, "내가 바꾼 항목 유지"), h("option", { value: "overwrite" }, "템플릿으로 모두 덮어쓰기"));
    const curTpl = S.templates.find((x) => x.id === t.id);
    const mod = S.clip.modified_keys || [];
    return h("div", { class: "card", style: { marginTop: "12px" } },
      h("b", {}, "템플릿"),
      h("div", { class: "small" }, `현재: ${t.name || "-"} v${t.version || "-"}`, curTpl && curTpl.current_version > t.version ? h("span", { class: "badge warn", style: { marginLeft: "6px" } }, `새 버전 v${curTpl.current_version} 있음 — 자동 적용 안 됨`) : null),
      h("div", { class: "small muted" }, mod.length ? `템플릿과 다른 항목 ${mod.length}개: ${mod.slice(0, 8).join(", ")}${mod.length > 8 ? "…" : ""}` : "템플릿 그대로 사용 중"),
      h("div", { class: "row", style: { marginTop: "6px" } }, sel, mode),
      h("div", { class: "row", style: { marginTop: "6px" } },
        h("button", { class: "small", onclick: async () => {
          await flushSave();
          try { const r = await api.post(`/api/clips/${S.clip.id}/apply-template`, { template_id: sel.value, mode: mode.value }); applyServerClip(r); toast(`적용했습니다${r.kept_keys?.length ? ` (유지 ${r.kept_keys.length}항목)` : ""}`); }
          catch (e) { toast(errMsg(e), true); }
        } }, "이 클립에 적용"),
        h("button", { class: "small", onclick: async () => {
          const n = S.clips.length;
          if (!confirm(`이 프로젝트의 클립 ${n}개 모두에 적용합니다.\n방식: ${mode.selectedOptions[0].text}\n${mode.value === "keep" ? "각 클립에서 사용자가 바꾼 항목은 유지됩니다." : "각 클립의 사용자 수정이 모두 덮어써집니다(실행 취소 가능)."}`)) return;
          await flushSave();
          try { await api.post(`/api/projects/${pid}/apply-template`, { template_id: sel.value, mode: mode.value }); S.clips = await api.get(`/api/projects/${pid}/clips`); await openClip(S.clip.id); toast("모든 클립에 적용했습니다"); }
          catch (e) { toast(errMsg(e), true); }
        } }, "모든 클립에 일괄 적용")),
      h("div", { class: "row", style: { marginTop: "6px" } },
        h("button", { class: "small", onclick: async () => {
          const name = prompt("새 템플릿 이름", "내 강의 템플릿");
          if (!name) return;
          const tpl = await api.post("/api/templates", { name, data: S.draft.data.style });
          S.templates = await api.get("/api/templates");
          S.draft.data.template = { id: tpl.id, version: tpl.current_version, name: tpl.name };
          markDirty("템플릿으로 저장", false); renderRight(); toast("새 템플릿으로 저장했습니다");
        } }, "현재 스타일을 새 템플릿으로 저장"),
        h("button", { class: "small", disabled: !curTpl || curTpl.builtin, title: curTpl?.builtin ? "기본 템플릿은 복제 후 수정하세요" : "", onclick: async () => {
          if (!confirm(`‘${curTpl.name}’의 새 버전(v${curTpl.current_version + 1})을 만듭니다. 이미 편집한 다른 클립은 바뀌지 않습니다.`)) return;
          const tpl = await api.put(`/api/templates/${curTpl.id}`, { data: S.draft.data.style });
          S.templates = await api.get("/api/templates");
          S.draft.data.template = { id: tpl.id, version: tpl.current_version, name: tpl.name };
          markDirty("템플릿 새 버전", false); renderRight(); toast(`v${tpl.current_version}로 저장했습니다`);
        } }, "템플릿 업데이트(새 버전)")));
  }

  // 구간·속도
  function renderRange() {
    if (!S.clip) { rightBody.replaceChildren(h("p", { class: "muted" }, "클립을 선택하세요.")); return; }
    const d = S.draft.data;
    const sm = S.clip.summary;
    const sIn = h("input", { type: "text", value: fmtMs(d.range.start_ms), style: { width: "110px" } });
    const eIn = h("input", { type: "text", value: fmtMs(d.range.end_ms), style: { width: "110px" } });
    const applyRange = () => {
      const a = parseTime(sIn.value), b = parseTime(eIn.value);
      if (isNaN(a) || isNaN(b) || b <= a) return toast("구간 시각을 확인하세요", true);
      d.range = { start_ms: a, end_ms: b };
      markDirty("구간 변경"); toast("구간을 바꿨습니다. 새 구간의 자막은 ‘전사문에서 자막 다시 가져오기’로 갱신하세요.");
    };
    const speedIn = h("input", { type: "number", min: 0.5, max: 2.5, step: 0.05, value: d.speed, onchange: (e) => { d.speed = Number(e.target.value); markDirty("배속 변경"); renderRange(); } });
    const sj = latestJob("silence", S.clip.id);
    const silParams = S.silParams || (S.silParams = { noise_db: -35, min_ms: 700, keep_ms: 150 });
    const silResult = sj?.status === "succeeded" ? sj.result : null;
    rightBody.replaceChildren(
      h("div", { class: "card" }, h("b", {}, "구간"),
        h("div", { class: "row", style: { marginTop: "6px" } }, "원본 시작", sIn, "끝", eIn, h("button", { class: "small", onclick: applyRange }, "적용")),
        h("div", { class: "small muted", style: { marginTop: "6px" } }, `원본 ${fmtMs(sm.source_ms)} − 삭제 ${fmtMs(sm.removed_ms)} = 편집 ${fmtMs(sm.edited_ms)} ÷ ${sm.speed}배 = 출력 ${fmtMs(sm.output_ms)} (저장 기준)`)),
      h("div", { class: "card", style: { marginTop: "10px" } }, h("b", {}, "배속"),
        h("div", { class: "row", style: { marginTop: "6px" } }, speedIn, ...[0.75, 1, 1.25, 1.5, 2].map((v) => h("button", { class: "small" + (d.speed === v ? " primary" : ""), onclick: () => { d.speed = v; markDirty("배속 변경"); renderRange(); } }, `${v}배`))),
        h("div", { class: "small muted" }, "음 높이 보존(atempo). 미리보기와 출력 모두 같은 배속·시간 매핑을 사용합니다.")),
      h("div", { class: "card", style: { marginTop: "10px" } }, h("b", {}, "무음 제거(제안 모드)"),
        h("div", { class: "form", style: { marginTop: "6px" } },
          h("label", {}, "무음 기준(dB)"), h("input", { type: "number", value: silParams.noise_db, onchange: (e) => (silParams.noise_db = Number(e.target.value)) }),
          h("label", {}, "최소 길이(ms)"), h("input", { type: "number", value: silParams.min_ms, onchange: (e) => (silParams.min_ms = Number(e.target.value)) }),
          h("label", {}, "남길 여백(ms)"), h("input", { type: "number", value: silParams.keep_ms, onchange: (e) => (silParams.keep_ms = Number(e.target.value)) })),
        h("div", { class: "row", style: { marginTop: "6px" } }, h("button", { disabled: isActive(sj) || !S.project.source?.has_audio, onclick: async () => {
          await flushSave();
          try { await api.post(`/api/clips/${S.clip.id}/silence`, silParams); renderRange(); } catch (e) { toast(errMsg(e), true); }
        } }, "무음 찾기"), !S.project.source?.has_audio ? h("span", { class: "small muted" }, "음성 트랙 없음") : null),
        sj && sj.status !== "succeeded" ? jobProgress(sj) : null,
        silResult ? silenceList(silResult) : null),
      h("div", { class: "card", style: { marginTop: "10px" } }, h("b", {}, `삭제 구간(EDL) ${d.cuts.length}개`),
        h("div", { class: "small muted" }, "원본은 그대로 두고 출력에서만 빠집니다. 끄기/삭제/실행 취소로 되돌릴 수 있습니다."),
        h("table", { class: "list small" }, d.cuts.map((c, i) => h("tr", {},
          h("td", {}, h("input", { type: "checkbox", checked: c.enabled, onchange: (e) => { c.enabled = e.target.checked; markDirty("삭제 구간 켜기/끄기"); } })),
          h("td", {}, { manual: "수동", silence: "무음", cue: "발화 삭제" }[c.reason] || c.reason),
          h("td", { class: "tc", onclick: () => { const o = srcToOut(Math.max(d.range.start_ms, c.start_ms - 500)); if (o != null) seekOut(o); } }, `${fmtMs(c.start_ms)}–${fmtMs(c.end_ms)}`),
          h("td", {}, `${((c.end_ms - c.start_ms) / 1000).toFixed(2)}초`),
          h("td", {}, h("button", { class: "small danger", onclick: () => {
            d.cuts.splice(i, 1);
            if (c.cue_id) { const cue = d.cues.find((x) => x.id === c.cue_id); if (cue) cue.deleted_speech = false; }
            markDirty("삭제 구간 제거"); renderRange(); renderMid();
          } }, "제거"))))),
        manualCutForm()),
      h("div", { class: "card", style: { marginTop: "10px" } }, h("b", {}, "오디오"),
        h("div", { class: "row" }, h("select", { onchange: (e) => { d.render = { ...(d.render || {}), audio_mode: e.target.value }; markDirty("오디오 설정", false); } },
          h("option", { value: "auto", selected: (d.render?.audio_mode || "auto") === "auto" }, "원본 음성 사용"),
          h("option", { value: "silent", selected: d.render?.audio_mode === "silent" }, "무음으로 출력")),
          h("span", { class: "small muted" }, "배경음악 ", h("span", { class: "badge soon" }, "준비 중")))));
  }
  function manualCutForm() {
    const a = h("input", { type: "text", placeholder: "시작", style: { width: "90px" } });
    const b = h("input", { type: "text", placeholder: "끝", style: { width: "90px" } });
    return h("div", { class: "row", style: { marginTop: "6px" } }, "수동 삭제", a, b,
      h("button", { class: "small", onclick: () => { a.value = fmtMs(outToSrc(S.outTime)); } }, "현재→시작"),
      h("button", { class: "small", onclick: () => { b.value = fmtMs(outToSrc(S.outTime)); } }, "현재→끝"),
      h("button", { class: "small", onclick: () => {
        const x = parseTime(a.value), y = parseTime(b.value);
        if (isNaN(x) || isNaN(y) || y <= x) return toast("시각을 확인하세요", true);
        S.draft.data.cuts.push({ start_ms: x, end_ms: y, reason: "manual", enabled: true });
        markDirty("수동 삭제 구간 추가"); renderRange();
      } }, "추가"));
  }
  function silenceList(res) {
    const picks = new Set(res.suggestions.map((_, i) => i));
    return h("div", { style: { marginTop: "6px" } },
      h("div", { class: "small" }, `무음 후보 ${res.suggestions.length}개, 합계 ${(res.total_ms / 1000).toFixed(2)}초 (기준 ${res.settings.noise_db}dB, 최소 ${res.settings.min_ms}ms, 여백 ${res.settings.keep_ms}ms 유지)`),
      h("table", { class: "list small" }, res.suggestions.map((s, i) => h("tr", {},
        h("td", {}, h("input", { type: "checkbox", checked: true, onchange: (e) => (e.target.checked ? picks.add(i) : picks.delete(i)) })),
        h("td", { class: "tc", onclick: () => { const o = srcToOut(Math.max(S.draft.data.range.start_ms, s.start_ms - 800)); if (o != null) { seekOut(o); togglePlay(); } } }, `${fmtMs(s.start_ms)}–${fmtMs(s.end_ms)} ▶`),
        h("td", {}, `${((s.end_ms - s.start_ms) / 1000).toFixed(2)}초`)))),
      h("button", { class: "small primary", onclick: () => {
        for (const i of picks) { const s = res.suggestions[i]; S.draft.data.cuts.push({ start_ms: s.start_ms, end_ms: s.end_ms, reason: "silence", enabled: true }); }
        markDirty(`무음 ${picks.size}개 삭제`); renderRange(); toast("삭제 구간에 추가했습니다. 단어 첫·끝음절이 잘리지 않았는지 재생해 확인하세요.");
      } }, "선택한 무음을 삭제 구간으로 추가"));
  }

  // 내보내기
  let arts = [];
  async function loadArtifacts() { arts = await api.get(`/api/artifacts?project_id=${pid}`); }
  function renderExport() {
    if (!S.clip) { rightBody.replaceChildren(exportBatch()); return; }
    const mine = arts.filter((a) => a.clip_id === S.clip.id);
    const rj = latestJob("render", S.clip.id), pj = latestJob("preview", S.clip.id);
    const previews = [];
    rightBody.replaceChildren(
      h("div", { class: "card" }, h("b", {}, "이 클립"),
        h("div", { class: "row", style: { marginTop: "6px" } },
          h("button", { class: "primary", disabled: isActive(rj), onclick: () => startRender(false) }, isActive(rj) ? "렌더링 중…" : "MP4 렌더링"),
          h("button", { disabled: isActive(pj), onclick: () => startRender(true) }, "확정 미리보기(540×960)"),
          h("a", { class: "small", href: `/api/clips/${S.clip.id}/srt` }, "SRT"), h("a", { class: "small", href: `/api/clips/${S.clip.id}/text` }, "제목·설명 TXT")),
        h("div", { class: "small muted" }, "SRT는 글자·시간만 담습니다(색·위치·강조는 프로젝트/템플릿 데이터에 저장)."),
        rj ? h("div", {}, h("span", { class: "small" }, "MP4: "), jobProgress(rj), rj.error_message ? h("div", { class: "errbox" }, rj.error_message) : null,
          isActive(rj) ? h("button", { class: "small danger", onclick: () => api.post(`/api/jobs/${rj.id}/cancel`) }, "취소") : null,
          ["failed", "canceled", "interrupted"].includes(rj.status) ? h("button", { class: "small", onclick: () => api.post(`/api/jobs/${rj.id}/retry`) }, "재시도") : null) : null,
        pj ? h("div", {}, h("span", { class: "small" }, "확정 미리보기: "), jobProgress(pj), pj.error_message ? h("div", { class: "errbox" }, pj.error_message) : null) : null,
        h("label", { class: "small" }, "설명(제목·설명 TXT에 포함)"),
        h("textarea", { rows: 2, oninput: (e) => { S.draft.data.description = e.target.value; markDirty("설명 수정", false); } }, S.draft.data.description || "")),
      ...previewsOf(previews),
      h("h3", {}, "완성본"),
      mine.length ? h("table", { class: "list small" }, mine.map((a) => h("tr", {},
        h("td", {}, h("div", {}, a.filename), h("div", { class: "muted" }, `${fmtMs(a.duration_ms)} · ${a.probe?.width}×${a.probe?.height} · ${fmtDate(a.created_at)}`),
          a.meta?.clip_updated_at && a.meta.clip_updated_at < S.clip.updated_at ? h("span", { class: "badge warn" }, "이후 편집됨 — 다시 렌더링 필요") : h("span", { class: "badge ok" }, "최신 편집 반영")),
        h("td", {}, a.exists ? h("a", { href: `/api/artifacts/${a.id}/download` }, "저장") : "파일 없음")))) : h("p", { class: "muted small" }, "아직 없음"),
      exportBatch());
  }
  function previewsOf() {
    const p = arts.length ? null : null;
    void p;
    return [];
  }
  function exportBatch() {
    const box = h("div", { class: "card", style: { marginTop: "12px" } }, h("b", {}, "여러 클립 일괄 내보내기"),
      h("div", { class: "small muted" }, "선택한 클립을 각각 MP4로 렌더링하고 ZIP으로 묶습니다. 같은 편집 상태의 중복 요청은 하나로 합칩니다."),
      ...S.clips.map((c) => h("label", { class: "row small" }, h("input", { type: "checkbox", checked: S.selectedClipIds.has(c.id), onchange: (e) => (e.target.checked ? S.selectedClipIds.add(c.id) : S.selectedClipIds.delete(c.id)) }), `${String(c.idx).padStart(2, "0")}. ${c.title}`)),
      h("div", { class: "row", style: { marginTop: "6px" } },
        h("button", { class: "small", onclick: () => { S.clips.forEach((c) => S.selectedClipIds.add(c.id)); renderRight(); } }, "모두 선택"),
        h("button", { class: "primary small", onclick: async () => {
          if (!S.selectedClipIds.size) return toast("클립을 선택하세요", true);
          await flushSave();
          try { const r = await api.post(`/api/projects/${pid}/batch-export`, { clip_ids: [...S.selectedClipIds], zip: true }); toast(`렌더링 ${r.render_jobs.length}개 + ZIP 작업을 시작했습니다`); }
          catch (e) { toast(errMsg(e), true); }
        } }, "선택 클립 MP4 + ZIP")));
    const zips = latestJob("export_zip");
    if (zips) box.append(h("div", {}, h("span", { class: "small" }, "ZIP: "), jobProgress(zips),
      zips.status === "succeeded" ? h("a", { href: `/api/artifacts/${zips.result.artifact_id}/download` }, `ZIP 저장 (${zips.result.count}개)`) : null,
      zips.error_message ? h("div", { class: "errbox" }, zips.error_message) : null));
    return box;
  }

  async function startRender(preview) {
    if (!S.clip) return;
    await flushSave();
    if (S.saveErr) return toast("저장에 실패해 렌더링하지 않았습니다: " + S.saveErr, true);
    try {
      const j = await api.post(`/api/clips/${S.clip.id}/render`, { preview });
      toast(j.deduplicated ? "같은 편집 상태의 작업이 이미 진행 중입니다" : preview ? "확정 미리보기 렌더링을 시작했습니다" : "MP4 렌더링을 시작했습니다");
      S.rightTab = "export";
      renderRight();
    } catch (e) { toast(errMsg(e), true); }
  }

  // ---------------------------------------------------------- 작업 연동
  function latestJob(kind, clipId) {
    const { state } = window.__jss || {};
    const list = (state?.jobs || []).filter((j) => j.kind === kind && j.project_id === pid && (!clipId || j.clip_id === clipId));
    return list[0] || null;
  }
  const isActive = (j) => j && (j.status === "queued" || j.status === "running");

  let lastJobsSig = "";
  disposers.push(onJobs(async (finished) => {
    if (finished && finished.project_id === pid) {
      if (finished.kind === "transcribe" && finished.status === "succeeded") await reloadTranscript();
      if (finished.kind === "recommend" && finished.status === "succeeded") { S.recs = await api.get(`/api/projects/${pid}/recommendations`); S.project = await api.get(`/api/projects/${pid}`); }
      if (["render", "preview", "export_zip"].includes(finished.kind)) await loadArtifacts();
      if (finished.kind === "preview" && finished.status === "succeeded") showPreviewVideo(finished.result.artifact_id);
    }
    const sig = JSON.stringify(((window.__jss?.state?.jobs) || []).filter((j) => j.project_id === pid).slice(0, 20).map((j) => [j.id, j.status, Math.round((j.progress || 0) * 50), j.stage]));
    if (sig !== lastJobsSig) {
      lastJobsSig = sig;
      if (document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
        renderRight();
        if (S.midTab === "transcript" || !S.clip) renderMidBody();
      }
    }
  }));

  function showPreviewVideo(aid) {
    const dlg = h("dialog", {}, h("h3", {}, "확정 미리보기 (실제 렌더링 결과, 540×960)"),
      h("video", { src: `/api/artifacts/${aid}/file`, controls: true, autoplay: true, style: { height: "70vh", background: "#000" } }),
      h("div", { class: "row" }, h("div", { class: "spacer" }), h("button", { onclick: () => dlg.close() }, "닫기")));
    document.body.append(dlg); dlg.showModal(); dlg.addEventListener("close", () => dlg.remove());
  }

  // ---------------------------------------------------------- 키보드
  function onKey(e) {
    const tag = document.activeElement?.tagName;
    const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveNow(); return; }
    if (typing) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undoRedo(e.shiftKey ? "redo" : "undo"); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); undoRedo("redo"); return; }
    if (e.code === "Space") { e.preventDefault(); togglePlay(); return; }
    if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp") && S.scene) {
      e.preventDefault();
      const cs = S.scene.cues;
      let i = cs.findIndex((c) => S.outTime < c.out_start_ms);
      if (e.key === "ArrowUp") { const cur = cs.findIndex((c) => S.outTime >= c.out_start_ms && S.outTime < c.out_end_ms); i = Math.max(0, (cur >= 0 ? cur : i) - 1); }
      if (i < 0) i = cs.length - 1;
      const c = cs[i];
      if (c) { S.currentCueId = c.id; seekOut(c.out_start_ms + 1); highlightCue(); }
      return;
    }
    if (S.clip && ELEMENT_LABEL[S.sel] && e.key.startsWith("Arrow") && !e.altKey) {
      e.preventDefault();
      const step = e.shiftKey ? 10 : 1;
      const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
      const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
      movePos(S.sel, dx, dy);
      layoutStage();
      markDirty(`${ELEMENT_LABEL[S.sel]} 미세 이동`);
      if (S.rightTab === "style") renderRight();
    }
  }
  document.addEventListener("keydown", onKey);
  disposers.push(() => document.removeEventListener("keydown", onKey));
  const onResize = debounce(() => layoutStage(), 100);
  window.addEventListener("resize", onResize);
  disposers.push(() => window.removeEventListener("resize", onResize));
  const onBefore = (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } };
  window.addEventListener("beforeunload", onBefore);
  disposers.push(() => window.removeEventListener("beforeunload", onBefore));

  function renderAll() {
    renderBar();
    renderLeft();
    renderMid();
    renderRight();
  }

  // ---------------------------------------------------------- 시작
  await loadProject();
  await loadArtifacts();
  renderAll();
  const want = query.clip || (S.clips[0] && S.clips[0].id);
  if (want && S.clips.some((c) => c.id === want)) await openClip(want);
  else { S.midTab = "transcript"; renderMid(); }

  return () => {
    flushSave();
    pause();
    video.removeAttribute("src");
    video.load();
    disposers.forEach((d) => d());
  };
}
