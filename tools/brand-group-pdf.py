"""PDF of every per-class violator report: report/groups/NN-class.html → NN-class.pdf, printed by headless Chromium.

Run: uv run --with playwright python tools/brand-group-pdf.py brand-protection/2026-09-28/brand-scan
The light theme is forced; links stay clickable in the PDF.
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def main(d: Path):
    async with async_playwright() as p:
        # Use the headless shell already on disk: a newer playwright package asks for a build not downloaded yet.
        shells = sorted(Path.home().glob("Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))
        browser = await p.chromium.launch(headless=True, executable_path=str(shells[-1]) if shells else None)
        page = await browser.new_page(color_scheme="light")
        for f in sorted((d / "report" / "groups").glob("[0-9][0-9]-*.html")):
            await page.goto(f.resolve().as_uri(), wait_until="load", timeout=600_000)
            await page.emulate_media(media="print", color_scheme="light")
            await page.pdf(path=str(f.with_suffix(".pdf")), format="A4", print_background=True,
                           margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"},
                           display_header_footer=True, header_template="<span></span>",
                           footer_template='<div style="font-size:8px;width:100%;text-align:center;color:#64748b">'
                                           '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
            print(f.with_suffix(".pdf").name, flush=True)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
