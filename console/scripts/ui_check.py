"""Headless UI check for the console: the guided tour and the queue tabs, in both themes and at phone width.

    cd console && npm run build && npm run preview          # serves http://localhost:4173
    python console/scripts/ui_check.py [--shots DIR] [--chrome PATH]

Needs `pip install playwright` (and `playwright install chromium`, or pass --chrome to use an installed Chrome).
Exits 1 if any check fails.
"""
import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4173/"
sys.stdout.reconfigure(encoding="utf-8")
STEPS = ["queue", "tabs", "headline", "sure", "changes", "actions", "audit"]
fails: list[str] = []


def check(ok: bool, what: str) -> None:
    print(("ok   " if ok else "FAIL ") + what)
    if not ok:
        fails.append(what)


def overlap(a, b) -> bool:
    return a["x"] < b["x"] + b["width"] and a["x"] + a["width"] > b["x"] and a["y"] < b["y"] + b["height"] and a["y"] + a["height"] > b["y"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", type=Path)
    ap.add_argument("--chrome")
    a = ap.parse_args()
    if a.shots:
        a.shots.mkdir(parents=True, exist_ok=True)
    shot = lambda p, name: a.shots and p.screenshot(path=str(a.shots / f"{name}.png"))
    errs: list[str] = []

    with sync_playwright() as pw:
        # Playwright hides scrollbars in headless mode by default; show them so the queue scrollbar can be checked.
        opts = {"headless": True, "ignore_default_args": ["--hide-scrollbars"]}
        b = pw.chromium.launch(executable_path=a.chrome, **opts) if a.chrome else pw.chromium.launch(**opts)

        def page(w=1440, h=900):
            c = b.new_context(viewport={"width": w, "height": h})
            p = c.new_page()
            p.on("console", lambda m: errs.append(m.text) if m.type in ("error", "warning") else None)
            p.on("pageerror", lambda e: errs.append(str(e)))
            return c, p

        # ------------------------------------------------------------ tour (both themes)
        for theme in ("dark", "light"):
            c, p = page()
            p.goto(BASE + f"?theme={theme}")
            p.wait_for_selector(".tour-pop", timeout=8000)
            p.wait_for_timeout(400)
            title = lambda: p.locator(".tour-count").inner_text()
            check(title() == "1 of 7", f"{theme}: tour opens by itself at 1 of 7")
            check(p.evaluate("document.activeElement.textContent") == "Next", f"{theme}: focus starts on Next")
            for k, target in enumerate(STEPS):
                p.wait_for_timeout(300)
                check(title() == f"{k + 1} of 7", f"{theme}: step {k + 1} is numbered {k + 1} of 7")
                pop = p.locator(".tour-pop").bounding_box()
                for t in STEPS[k:k + 2]:
                    box = p.locator(f'[data-tour="{t}"]').first.bounding_box()
                    check(not overlap(pop, box), f"{theme}: step {k + 1} popover leaves '{t}' uncovered")
                if k in (0, 1, 3):
                    shot(p, f"{theme}_tour{k + 1}")
                if k == 1:
                    lines = p.locator("#tour-text").inner_text().split("\n")
                    check(len(lines) == 2 and lines[0].startswith("Done:") and lines[1].startswith("Other:"),
                          f"{theme}: step 2 is two lines, Done then Other")
                p.keyboard.press("ArrowRight" if k % 2 else "Enter")
            check(p.locator(".tour-pop").count() == 0, f"{theme}: tour closes after the last step")
            p.reload()
            p.wait_for_selector(".case")
            p.wait_for_timeout(400)
            check(p.locator(".tour-pop").count() == 0, f"{theme}: tour stays closed after reload")
            p.get_by_role("button", name="Tour", exact=True).click()
            p.wait_for_timeout(300)
            p.keyboard.press("ArrowRight"); p.keyboard.press("ArrowLeft")
            p.wait_for_timeout(200)
            check(title() == "1 of 7", f"{theme}: Tour button reopens it; → then ← returns to step 1")
            p.keyboard.press("a")
            check(p.locator("#name-title").count() == 0, f"{theme}: A is ignored while the tour is open")
            p.keyboard.press("Escape")
            p.wait_for_timeout(200)
            check(p.locator(".tour-pop").count() == 0, f"{theme}: Esc skips")

            # -------------------------------------------------------- queue tabs and Other menu
            q = p.locator(".queue").bounding_box()
            tab = p.get_by_role("tab", name="Other")
            check(tab.inner_text().replace(" ", " ").strip() == "Other ▾", f"{theme}: the tab reads 'Other ▾'")
            tab.click()
            p.wait_for_timeout(150)
            items = p.get_by_role("menuitemradio")
            check(items.count() == 3, f"{theme}: menu lists Auto-applied, No change, Bonus findings")
            p.keyboard.press("ArrowDown"); p.keyboard.press("Enter")
            p.wait_for_timeout(250)
            head = p.locator(".qhead").inner_text()
            check(head.startswith("No change ·"), f"{theme}: ↓ Enter opens No change; heading shows '{head}'")
            check(tab.inner_text().strip().startswith("Other"), f"{theme}: tab still reads 'Other' with a list open")
            row = p.locator(".qtabs").bounding_box()
            sw = p.evaluate("(() => { const t = document.querySelector('.qtabs'); return t.scrollWidth - t.clientWidth; })()")
            check(row["x"] + row["width"] <= q["x"] + q["width"] + 0.5 and sw <= 0, f"{theme}: tab row fits the sidebar")
            tab_style = p.evaluate("""(() => { const a = getComputedStyle(document.querySelector('.qtab.on'));
                const n = getComputedStyle([...document.querySelectorAll('.qtab')][0]);
                return [a.fontSize === n.fontSize && a.paddingLeft === n.paddingLeft, a.backgroundColor, a.borderTopWidth]; })()""")
            check(tab_style[0] and tab_style[1] in ("rgba(0, 0, 0, 0)", "transparent") and tab_style[2] == "0px",
                  f"{theme}: active Other tab looks like Needs you / Done (no box)")
            shot(p, f"{theme}_other_nochange")
            tab.click()
            p.wait_for_timeout(150)
            check(p.evaluate("document.activeElement.getAttribute('aria-checked')") == "true",
                  f"{theme}: menu opens on the current list")
            shot(p, f"{theme}_other_menu")
            p.keyboard.press("Escape")
            p.wait_for_timeout(150)
            check(p.get_by_role("menu").count() == 0 and p.evaluate("document.activeElement.getAttribute('role')") == "tab",
                  f"{theme}: Esc closes the menu and returns focus to the tab")
            tab.click(); p.keyboard.press("ArrowUp"); p.keyboard.press("Enter")
            p.wait_for_timeout(250)
            check(p.locator(".qhead").inner_text().startswith("Auto-applied ·"), f"{theme}: ↑ Enter opens Auto-applied")
            sb = p.evaluate("(() => { const r = document.querySelector('.rows'); return r.offsetWidth - r.clientWidth; })()")
            check(0 < sb <= 8, f"{theme}: queue scrollbar is thin ({sb}px)")
            shot(p, f"{theme}_auto_list")
            c.close()

        # ------------------------------------------------------------ phone
        c, p = page(390, 844)
        p.goto(BASE + "#auto/60f744b3")
        p.wait_for_selector(".case")
        p.wait_for_timeout(300)
        if not p.locator(".queue").is_visible():
            p.get_by_role("button", name="Toggle queue").click()
            p.wait_for_timeout(300)
        if p.locator(".queue").is_visible():
            q = p.locator(".queue").bounding_box()
            row = p.locator(".qtabs").bounding_box()
            check(row["x"] + row["width"] <= q["x"] + q["width"] + 0.5, "phone: tab row fits the queue panel")
            p.get_by_role("tab", name="Other").click()
            p.wait_for_timeout(150)
            m = p.get_by_role("menu").bounding_box()
            check(m["x"] >= 0 and m["x"] + m["width"] <= 390, "phone: Other menu stays on screen")
            shot(p, "phone_other_menu")
        else:
            check(False, "phone: queue panel could not be opened")
        check(p.evaluate("document.documentElement.scrollWidth") <= 390, "phone: no sideways scroll")
        c.close()
        b.close()

    check(not errs, "no console errors" + (f": {errs}" if errs else ""))
    print(f"\n{len(fails)} failed" if fails else "\nall checks passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
