"""Render the pitch deck (docs/deck/slides/*.html, 1920x1080 slides) to docs/FundTrace-deck.pdf.

    python docs/deck/render_pdf.py

The slides are the source of the Claude Slides artifact; uploaded images are mapped to docs/screenshots/.
Needs Python Playwright with Chromium (pip install playwright && playwright install chromium).
"""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SHOTS = (HERE.parent / "screenshots").resolve()
BLOBS = {  # artifact asset id -> local screenshot
    "4a75f940986bdaa891aa67a26119f6b4": "graph_cropped.png",
    "c23a947dcb3ffa3f09ee49d4d1158448": "risk.png",
    "d6357953294c53d8c27f470c8e4f7644": "report.png",
    "6cc87d200f32bcb835f1f60d47a956e7": "dimensions.png",
    "59852cc38524f0ae3f2311a023ccc7c8": "queue.png",
}
CSS = """
*{margin:0;box-sizing:border-box}
@page{size:1920px 1080px;margin:0}
body{background:#14183A}
section{width:1920px;height:1080px;position:relative;overflow:hidden;page-break-after:always;break-after:page}
aside{display:none}
h1{font-size:96px;font-weight:600;line-height:1.1} h2{font-size:64px;font-weight:600;line-height:1.15}
h3{font-size:44px;font-weight:600;line-height:1.2} p{font-size:32px;line-height:1.4}
ul{padding-left:1.1em} li{margin:0 0 6px 0}
table{border-collapse:collapse;width:100%}
th,td{padding:0.35em 0.6em;border-bottom:1px solid #DDDFEA;text-align:left}
th{font-weight:600}
img{display:block}
"""


def build() -> str:
    deck = json.loads((HERE / "deck.json").read_text(encoding="utf-8"))
    fonts = "".join(f'<link rel="stylesheet" href="{f["href"]}">' for f in deck["faces"].values() if "href" in f)
    slides = []
    for sid in deck["order"]:
        html = (HERE / "slides" / f"{sid}.html").read_text(encoding="utf-8")
        for blob, name in BLOBS.items():
            html = html.replace(f"/_blob/{blob}", (SHOTS / name).as_uri())
        slides.append(html)
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{deck["title"]}</title>{fonts}'
            f"<style>{CSS}</style></head><body>{''.join(slides)}</body></html>")


def main() -> None:
    out_html = HERE / "deck.html"
    out_html.write_text(build(), encoding="utf-8")
    pdf = HERE.parent / "FundTrace-deck.pdf"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.goto(out_html.as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(1500)
        pg.pdf(path=str(pdf), width="1920px", height="1080px", print_background=True, prefer_css_page_size=True)
        for i, sec in enumerate(pg.locator("section").all()[:3] + pg.locator("section").all()[-2:]):
            sec.screenshot(path=str(HERE / f"_check_{i}.png"))
        b.close()
    print(f"wrote {pdf}")


if __name__ == "__main__":
    main()
