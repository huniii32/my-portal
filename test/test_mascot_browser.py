"""Small optional browser check for the rendered mascot, not a new test harness."""
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).parent.parent


def _web_script(name: str) -> str:
    candidate = ROOT / "web" / "static" / name
    legacy = ROOT / name
    path = candidate if candidate.is_file() else legacy
    return path.read_text(encoding="utf-8")


@pytest.mark.skipif(not os.getenv("PORTAL_BROWSER_URL"), reason="set PORTAL_BROWSER_URL for the optional Playwright check")
def test_mascot_appearances_rotate_without_losing_motion_or_fallback():
    playwright = pytest.importorskip("playwright.sync_api")
    assistant = _web_script("assistant.js")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.add_init_script("""
          (() => {
            const original = window.setInterval;
            window.mascotIntervalCount = 0;
            window.setInterval = (...args) => { window.mascotIntervalCount += 1; return original(...args); };
          })();
        """)
        page.clock.install()
        page.route("**/assets/assistant.js", lambda route: route.fulfill(status=200, content_type="text/javascript", body=assistant + "\nwindow.mascotSpriteQA={mascot,walk,stopWalk,run(d){bubble.hidden=true;stopWalk();walk.x=650;walk.y=810;walk.targetX=650+d*220;walk.targetY=810;walk.last=performance.now();frame(performance.now())}};"))
        page.goto(os.environ["PORTAL_BROWSER_URL"], wait_until="networkidle")
        page.wait_for_function("window.mascotSpriteQA.mascot.ready")
        state = page.evaluate("({ready:mascotSpriteQA.mascot.ready,canvas:!!document.querySelector('#secretary-mascot canvas'),index:Number(localStorage.getItem('secretary-mascot-appearance')),href:document.querySelector('.mascot-sprite')?.getAttribute('src')})")
        assert state["ready"] and not state["canvas"] and 0 <= state["index"] < 6
        assert state["href"] in {f"/assets/mascot/pixel-{number}.png" for number in range(1, 7)}
        for number in range(1, 7):
            assert page.evaluate(f"fetch('/assets/mascot/pixel-{number}.png').then(r => r.blob()).then(createImageBitmap).then(image => [image.width, image.height])") == [1254, 1254]
        before = state["index"]
        page.clock.fast_forward(60000)
        page.wait_for_function("previous => Number(localStorage.getItem('secretary-mascot-appearance')) !== previous", arg=before)
        after = page.evaluate("Number(localStorage.getItem('secretary-mascot-appearance'))")
        assert 0 <= after < 6 and after != before
        intervals = page.evaluate("window.mascotIntervalCount")
        page.evaluate("mascotSpriteQA.mascot.start()")
        assert page.evaluate("window.mascotIntervalCount") == intervals
        page.evaluate("document.querySelector('#secretary-overlay').hidden = true")
        page.clock.fast_forward(60000)
        assert page.evaluate("Number(localStorage.getItem('secretary-mascot-appearance'))") == after
        page.evaluate("document.querySelector('#secretary-overlay').hidden = false")
        page.evaluate("d => mascotSpriteQA.run(d)", -1)
        page.wait_for_timeout(450)
        assert page.evaluate("mascotSpriteQA.walk.x") < 649
        assert "scaleX" not in page.locator(".mascot-sprite").get_attribute("style")
        page.locator("#task-title").focus()
        before = page.evaluate("mascotSpriteQA.walk.x")
        page.wait_for_timeout(250)
        assert page.evaluate("mascotSpriteQA.walk.x") == before
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_timeout(100)
        assert page.evaluate("mascotSpriteQA.mascot.reduced")
        assert page.locator(".mascot-sprite").get_attribute("style") in (None, "")
        failed = browser.new_page(viewport={"width": 375, "height": 812})
        failed.add_init_script("localStorage.setItem('secretary-mascot-appearance', '1'); Math.random = () => 0;")
        failed.clock.install()
        failed.route("**/assets/assistant.js", lambda route: route.fulfill(status=200, content_type="text/javascript", body=assistant + "\nwindow.mascotSpriteQA={mascot};"))
        failed.route("**/assets/mascot/pixel-1.png", lambda route: route.fulfill(status=404, body="missing"))
        failed.goto(os.environ["PORTAL_BROWSER_URL"], wait_until="networkidle")
        assert failed.locator(".mascot-fallback").is_visible()
        assert failed.locator(".mascot-sprite").count() == 0
        assert not failed.evaluate("mascotSpriteQA.mascot.ready")
        failed.clock.fast_forward(60000)
        failed.wait_for_function("window.mascotSpriteQA.mascot.ready")
        assert failed.locator(".mascot-fallback").count() == 0
        assert failed.locator(".mascot-sprite").get_attribute("src") == "/assets/mascot/pixel-2.png"
        bubble_overflow = failed.locator("#secretary-bubble").evaluate("node => ({overflowX: getComputedStyle(node).overflowX, overflowY: getComputedStyle(node).overflowY})")
        assert bubble_overflow == {"overflowX": "hidden", "overflowY": "auto"}
        failed.close()
        browser.close()


@pytest.mark.skipif(not os.getenv("PORTAL_BROWSER_URL"), reason="set PORTAL_BROWSER_URL for the optional Playwright check")
def test_invalid_saved_appearance_is_replaced_and_refresh_changes_it():
    playwright = pytest.importorskip("playwright.sync_api")
    assistant = _web_script("assistant.js")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script("if (!sessionStorage.invalidMascotAppearance) { localStorage.setItem('secretary-mascot-appearance', 'not-an-index'); sessionStorage.invalidMascotAppearance = '1'; }")
        page.route("**/assets/assistant.js", lambda route: route.fulfill(status=200, content_type="text/javascript", body=assistant + "\nwindow.mascotSpriteQA={mascot};"))
        page.goto(os.environ["PORTAL_BROWSER_URL"], wait_until="networkidle")
        page.wait_for_function("window.mascotSpriteQA.mascot.ready")
        first = page.evaluate("Number(localStorage.getItem('secretary-mascot-appearance'))")
        assert 0 <= first < 6
        page.reload(wait_until="networkidle")
        page.wait_for_function("window.mascotSpriteQA.mascot.ready")
        second = page.evaluate("Number(localStorage.getItem('secretary-mascot-appearance'))")
        assert 0 <= second < 6 and second != first
        browser.close()


@pytest.mark.skipif(not os.getenv("PORTAL_BROWSER_URL"), reason="set PORTAL_BROWSER_URL for the optional Playwright check")
def test_all_six_pixel_views_fit_the_mobile_mascot_slot():
    playwright = pytest.importorskip("playwright.sync_api")
    assistant = _web_script("assistant.js")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 812})
        page.route("**/assets/assistant.js", lambda route: route.fulfill(status=200, content_type="text/javascript", body=assistant + "\nwindow.mascotSpriteQA={mascot};"))
        page.goto(os.environ["PORTAL_BROWSER_URL"], wait_until="networkidle")
        for index in range(6):
            page.evaluate("index => mascotSpriteQA.mascot.selectAppearance(index)", index)
            page.wait_for_function("index => mascotSpriteQA.mascot.appearance === index && mascotSpriteQA.mascot.loading === null", arg=index)
            box = page.locator(".mascot-sprite").bounding_box()
            assert box and box["width"] == 112 and box["height"] == 130
            href = page.locator(".mascot-sprite").get_attribute("src")
            assert href == f"/assets/mascot/pixel-{index + 1}.png"
        browser.close()


@pytest.mark.skipif(not os.getenv("PORTAL_BROWSER_URL"), reason="set PORTAL_BROWSER_URL for the optional Playwright check")
def test_mascot_dock_uses_the_existing_chat_pause_and_hide_actions():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 812})
        page.add_init_script("localStorage.setItem('secretary-paused', 'true')")
        page.goto(os.environ["PORTAL_BROWSER_URL"], wait_until="networkidle")
        controls = page.locator(".mascot-control")
        assert controls.all_text_contents() == ["대화", "▶이동 시작", "숨기기"]
        for index in range(3):
            box = controls.nth(index).bounding_box()
            assert box and box["height"] >= 44
        pause = page.locator("#secretary-pause")
        assert pause.get_attribute("aria-pressed") == "true"
        assert "이동 시작" in pause.text_content()
        pause.click()
        assert pause.get_attribute("aria-pressed") == "false"
        page.locator("#secretary-chat").click()
        assert page.locator("#assistant-dialog").evaluate("node => node.open")
        page.locator("#assistant-close").click()
        page.locator("#secretary-hide").click()
        assert page.locator("#secretary-overlay").is_hidden()
        assert page.evaluate("document.activeElement.id") == "assistant-opener"
        browser.close()
