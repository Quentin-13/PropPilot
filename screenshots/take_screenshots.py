"""Screenshots avant/après pour les chantiers landing mobile."""
import sys
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

HTML_PATH = Path(__file__).parent.parent / "index.html"
SHOTS_DIR = Path(__file__).parent

def take(label: str):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        url = f"file://{HTML_PATH.resolve()}"

        # Mobile 375px
        mobile = browser.new_page(viewport={"width": 375, "height": 812})
        mobile.goto(url, wait_until="networkidle")
        # Scroll to bottom → trigger all IntersectionObservers, then back to top
        mobile.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        mobile.wait_for_timeout(600)
        mobile.evaluate("window.scrollTo(0, 0)")
        mobile.wait_for_timeout(200)
        mobile.screenshot(path=str(SHOTS_DIR / f"{label}_mobile_375.png"), full_page=True)
        mobile.close()

        # Desktop 1440px
        desktop = browser.new_page(viewport={"width": 1440, "height": 900})
        desktop.goto(url, wait_until="networkidle")
        desktop.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        desktop.wait_for_timeout(600)
        desktop.evaluate("window.scrollTo(0, 0)")
        desktop.wait_for_timeout(200)
        desktop.screenshot(path=str(SHOTS_DIR / f"{label}_desktop_1440.png"), full_page=True)
        desktop.close()

        browser.close()
        print(f"[OK] {label}_mobile_375.png + {label}_desktop_1440.png")

if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "shot"
    take(label)
