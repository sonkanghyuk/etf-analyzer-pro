"""브라우저 실사용 흐름 검수(서버가 떠 있어야 함).

python tests/ui_e2e.py http://127.0.0.1:8790 <영상.mp4> <자막.srt> <증거폴더>
등록 → SRT 불러오기 → 수동 구간 → 자막 이동(드래그)·스타일 변경 → 저장 → 새로고침 복원 → 렌더링 → 1366×768 화면 확인.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

base, video, srt, out = sys.argv[1], sys.argv[2], sys.argv[3], Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
errors: list[str] = []
report: dict = {}

with sync_playwright() as p:
    import os
    exe = os.environ.get("JSS_CHROMIUM")
    b = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    page = b.new_page(viewport={"width": 1920, "height": 1080})
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
    page.goto(base + "/#/projects")
    page.wait_for_selector("text=새 프로젝트")
    page.fill("input[placeholder^='프로젝트 제목']", "UI 검수 강의")
    page.fill("input[placeholder^='예: D:']", video)
    page.click("button:has-text('경로로 등록')")
    page.wait_for_function("location.hash.startsWith('#/project/')", timeout=60000)
    page.wait_for_selector("text=SRT/VTT 불러오기")
    with page.expect_file_chooser() as fc:
        page.click("button:has-text('SRT/VTT 불러오기')")
    fc.value.set_files(srt)
    page.wait_for_selector("text=교정 저장(새 버전)", timeout=20000)
    # 수동 구간
    form = page.locator("text=수동 구간으로 클립 만들기").locator("..")
    inputs = form.locator("input[type=text]")
    inputs.nth(0).fill("00:03.0")
    inputs.nth(1).fill("00:21.0")
    inputs.nth(2).fill("UI에서 만든 SOXL 클립")
    form.locator("button:has-text('클립 만들기')").click()
    page.wait_for_selector(".stage .sel", timeout=20000)
    page.wait_for_timeout(800)
    page.screenshot(path=str(out / "ui_editor_1920.png"))
    # 자막 상자를 위로 120px(화면 기준) 드래그
    sub = page.locator(".stage .sel", has_text="자막").first
    box = sub.bounding_box()
    page.mouse.move(box["x"] + 20, box["y"] + 10)
    page.mouse.down()
    page.mouse.move(box["x"] + 20, box["y"] - 40, steps=5)
    page.mouse.up()
    page.wait_for_timeout(500)
    # 스타일 탭: 자막 크기 변경
    page.click(".tabs button:has-text('일반 자막')")
    size_in = page.locator(".form label:has-text('크기(px)') + input")
    size_in.fill("66")
    size_in.dispatch_event("change")
    page.wait_for_timeout(300)
    page.keyboard.press("Control+s")
    page.wait_for_selector(".badge:has-text('저장됨')", timeout=10000)
    clip_url = page.url
    page.reload()
    page.wait_for_selector(".stage .sel", timeout=20000)
    page.click(".pane .tabs button:has-text('스타일·템플릿')")
    page.click(".tabs button:has-text('일반 자막')")
    restored_size = page.locator(".form label:has-text('크기(px)') + input").input_value()
    restored_y = page.locator(".form label:text-is('Y') + input").input_value()
    report["restored_subtitle_size"] = restored_size
    report["restored_subtitle_y"] = restored_y
    # 재생 1초
    report["browser_can_play_h264"] = page.evaluate("document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E\"')")
    page.click("text=▶ 재생")
    page.wait_for_timeout(1500)
    if page.locator("text=❚❚ 정지").count():
        page.click("text=❚❚ 정지")
    else:
        report["play_notice"] = page.locator(".stage .notice").inner_text()
        page.click("button:has-text('재생용 프록시 만들기')")
        page.wait_for_function("document.querySelector('.stage video').src.includes('proxy=1')", timeout=120000)
        page.wait_for_timeout(1000)
        page.click("text=▶ 재생")
        page.wait_for_timeout(2500)
        report["time_label_while_playing"] = page.locator(".times").inner_text()
        report["cue_visible_while_playing"] = page.locator(".stage img.cueimg").is_visible()
        page.click("text=❚❚ 정지")
    report["time_label_after_play"] = page.locator(".times").inner_text()
    page.screenshot(path=str(out / "ui_editor_after_edit.png"))
    # 렌더링
    page.click("button.primary:has-text('MP4 내보내기')")
    try:
        page.wait_for_selector("text=최신 편집 반영", timeout=60000)
    except Exception:
        page.screenshot(path=str(out / "ui_fail.png"))
        print(page.locator(".pane").nth(2).inner_text()[:1500])
        raise
    page.screenshot(path=str(out / "ui_export_done.png"))
    # 1366×768
    page.set_viewport_size({"width": 1366, "height": 768})
    page.wait_for_timeout(500)
    page.screenshot(path=str(out / "ui_editor_1366.png"))
    btns = ["MP4 내보내기", "확정 미리보기", "변경 저장"]
    report["1366_buttons_visible"] = {t: page.locator(f"button:has-text('{t}')").first.is_visible() for t in btns}
    mid = page.locator(".pane").nth(1)
    report["mid_pane_scrollable"] = mid.evaluate("e => e.scrollHeight > e.clientHeight")
    for nav in ("templates", "outputs", "settings", "projects"):
        page.goto(base + f"/#/{nav}")
        page.wait_for_timeout(800)
        page.screenshot(path=str(out / f"ui_{nav}.png"))
    report["clip_url"] = clip_url
    b.close()

report["errors"] = errors
(out / "ui_e2e_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=1))
sys.exit(1 if errors else 0)
