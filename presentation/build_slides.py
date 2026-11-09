"""Сборка presentation/slides.pdf из presentation/slides.md.

Запуск из корня проекта:
  python -X utf8 presentation/build_slides.py

Источник текста один: slides.md. Со слайда берутся заголовок, блок «На слайде» (список и таблица) и строки
«Схема», «Снимки» и «Подпись». Строки «Речь» и «Источник» в PDF не попадают. Снимки читаются из
evaluation/e2e/.results, шрифт — из frontend/public/fonts. Страницу печатает Chromium без интерфейса:
путь берётся из переменной SLIDES_BROWSER, иначе ищутся браузер Playwright, Edge и Chrome.
Флаг --html сохраняет рядом промежуточную страницу slides.html для просмотра в браузере.
"""

from __future__ import annotations

import base64
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "presentation" / "slides.md"
OUTPUT = ROOT / "presentation" / "slides.pdf"
SHOTS = ROOT / "evaluation" / "e2e" / ".results"
FONTS = ROOT / "frontend" / "public" / "fonts"
# Диапазоны из frontend/src/styles/fonts.css
FONT_RANGES = {
    "onest-cyrillic.woff2": "U+0301, U+0400-045F, U+0490-0491, U+04B0-04B1, U+2116",
    "onest-latin.woff2": (
        "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, "
        "U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, U+FEFF, U+FFFD"
    ),
}
LABEL_MAX = 45  # первое предложение пункта короче этого предела выделяется как подзаголовок
NBSP = "\u00a0"


@dataclass
class Slide:
    title: str
    number: int | None = None  # None — приложения
    bullets: list[str] = field(default_factory=list)
    table: list[list[str]] = field(default_factory=list)
    align: list[str] = field(default_factory=list)
    scheme: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    caption: str = ""


def parse(text: str) -> list[Slide]:
    slides: list[Slide] = []
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        head, _, body = block.partition("\n")
        numbered = re.fullmatch(r"Слайд (\d+)\. (.+)", head.strip())
        slide = Slide(title=numbered[2], number=int(numbered[1])) if numbered else Slide(title=head.strip())
        on_slide = numbered is None  # у приложений блок «На слайде» не размечается
        for raw in body.splitlines():
            line = raw.strip()
            if line.startswith("На слайде"):
                on_slide = True
            elif line.startswith(("Речь.", "Источник")):
                on_slide = False
            elif line.startswith("Схема:"):
                slide.scheme = [part.strip() for part in line.removeprefix("Схема:").split("→")]
            elif line.startswith("Снимки:"):
                slide.images = re.findall(r"[\w-]+\.png", line)
            elif line.startswith("Подпись:"):
                slide.caption = line.removeprefix("Подпись:").strip()
            elif on_slide and line.startswith("- "):
                slide.bullets.append(line[2:])
            elif on_slide and line.startswith("|"):
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                    slide.align = ["right" if cell.endswith(":") else "left" for cell in cells]
                else:
                    slide.table.append(cells)
        slides.append(slide)
    return slides


def inline(text: str) -> str:
    """Разметка строки: ссылки остаются текстом, код — моноширинным, числа не рвутся на границе разрядов."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"(\d) (?=\d{3}\b)", rf"\1{NBSP}", text)
    return re.sub(r"(\d) %", rf"\1{NBSP}%", text)


def bullet(text: str) -> str:
    if text.endswith(":"):  # поле без значения: на слайде остаётся линия, её заполняют перед сдачей
        return f'<li>{inline(text)}<span class="blank"></span></li>'
    label, dot, rest = text.partition(". ")
    if dot and len(label) < LABEL_MAX and "«" not in label and ":" not in label:
        return f"<li><strong>{inline(label)}.</strong> {inline(rest)}</li>"
    return f"<li>{inline(text)}</li>"


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def image_size(path: Path) -> tuple[int, int]:
    """Ширина и высота PNG из заголовка файла."""
    header = path.read_bytes()[:24]
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def render(slide: Slide) -> str:
    parts: list[str] = []
    if slide.scheme:
        steps = '<span class="arrow">→</span>'.join(f'<span class="step">{inline(s)}</span>' for s in slide.scheme)
        parts.append(f'<div class="scheme">{steps}</div>')
    if slide.table:
        align = slide.align or ["left"] * len(slide.table[0])
        head = "".join(f'<th class="{a}">{inline(c)}</th>' for c, a in zip(slide.table[0], align, strict=True))
        rows = "".join(
            "<tr>" + "".join(f'<td class="{a}">{inline(c)}</td>' for c, a in zip(row, align, strict=True)) + "</tr>"
            for row in slide.table[1:]
        )
        parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table>")
    if slide.bullets:
        parts.append("<ul>" + "".join(bullet(b) for b in slide.bullets) + "</ul>")
    shots, ratios, tall = [], [], False
    for name in slide.images:
        path = SHOTS / name
        if not path.is_file():
            raise SystemExit(f"Нет снимка {name}: запустите check:feed (evaluation/e2e)")
        width, height = image_size(path)
        ratios.append(width / height)
        tall = tall or height > 2 * width
        # В ряду ширина делится по пропорциям снимков: тогда высоты равны и ни один снимок не обрезается
        shots.append(f'<img style="flex: {width / height:.3f} 1 0" src="{data_uri(path, "image/png")}" alt="">')
    # Высокий узкий снимок не сжимается до нечитаемого: показывается его верх в ширину колонки
    layout = "text" if not shots else "crop" if tall else "side" if len(shots) == 1 else "row"
    size = sum(len(b) for b in slide.bullets) + sum(len(c) for row in slide.table for c in row)
    classes = [layout, "dense" if size > 620 or (slide.table and slide.bullets) else ""]
    classes.append("cover" if slide.number == 1 else "appendix" if slide.number is None else "")
    ratio = sum(ratios) if layout == "row" else 0
    style = f' style="aspect-ratio: {ratio:.3f}"' if ratio else ""
    figure = f'<div class="figure"><div class="shots"{style}>{"".join(shots)}</div></div>' if shots else ""
    text = slide.caption[:1].upper() + slide.caption[1:]
    caption = f'<p class="caption">{inline(text)}</p>' if text else ""
    number = "" if slide.number is None else f'<span class="number">{slide.number}</span>'
    return (
        f'<section class="{" ".join(c for c in classes if c)}"><h1>{inline(slide.title)}</h1>'
        f'<div class="body"><div class="content">{"".join(parts)}</div>{figure}</div>'
        f'<footer>{caption}{number}</footer></section>'
    )


CSS = """
@page { size: 1280px 720px; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { font-family: "Onest", "Segoe UI", Arial, sans-serif; color: #5d001d; background: #fffafa;
  -webkit-print-color-adjust: exact; print-color-adjust: exact; }
section { width: 1280px; height: 720px; padding: 44px 60px 34px; display: flex; flex-direction: column;
  page-break-after: always; break-after: page; overflow: hidden; background: #fffafa; position: relative; }
section::before { content: ""; position: absolute; left: 0; top: 44px; width: 8px; height: 76px; background: #c41230;
  border-radius: 0 6px 6px 0; }
h1 { margin: 0 0 22px; font-size: 31px; line-height: 1.22; font-weight: 600; max-width: 1080px; }
.body { flex: 1; min-height: 0; display: flex; gap: 36px; }
.content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 18px; }
ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 14px; font-size: 22px;
  line-height: 1.36; color: #3d2a30; }
li { padding-left: 22px; position: relative; }
li::before { content: ""; position: absolute; left: 0; top: 0.58em; width: 8px; height: 8px; border-radius: 2px;
  background: #c41230; }
strong { font-weight: 600; color: #5d001d; }
.blank { display: inline-block; width: 520px; margin-left: 14px; border-bottom: 1.5px solid #c9b8bc; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.9em; background: #f8f6f6; border: 1px solid #ebebeb;
  border-radius: 6px; padding: 1px 6px; color: #4a3b40; }
table { border-collapse: collapse; width: 100%; font-size: 17px; line-height: 1.3; color: #3d2a30; }
th { text-align: left; font-weight: 500; color: #6b5b60; border-bottom: 2px solid #8b7c80; padding: 7px 12px 7px 0; }
td { border-bottom: 1px solid #ebebeb; padding: 8px 12px 8px 0; vertical-align: top; }
.right { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td:first-child { font-weight: 500; color: #5d001d; }
.scheme { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 17px; }
.step { background: #fff; border: 1px solid #f0c4cb; border-radius: 12px; padding: 8px 14px; font-weight: 500; }
.arrow { color: #c41230; font-weight: 600; }
.figure { display: flex; justify-content: center; align-items: flex-start; min-width: 0; min-height: 0; }
.shots { display: flex; gap: 20px; align-items: flex-start; justify-content: center; max-width: 100%; max-height: 100%; }
img { display: block; min-width: 0; padding: 10px; border: 1px solid #ebebeb; border-radius: 12px; background: #fffafa;
  box-shadow: 0 6px 18px rgba(93, 0, 29, 0.08); }
.side .content { flex: 0 0 42%; }
.side .figure { flex: 1; }
.side .shots { width: 100%; height: 100%; }
.side img { flex: 0 1 auto !important; max-width: 100%; max-height: 100%; }
.crop .figure { flex: 0 0 300px; }
.crop .shots { height: 100%; overflow: hidden; border-radius: 12px;
  -webkit-mask-image: linear-gradient(#000 86%, transparent); mask-image: linear-gradient(#000 86%, transparent); }
.crop img { flex: 0 0 300px !important; width: 300px; }
.row .body { flex-direction: column; gap: 18px; }
.row .content { flex: 0 0 auto; }
.row .figure { flex: 1; }
.row .shots { height: 100%; }
.row img { width: 0; height: auto; }
.side ul, .row ul, .crop ul { font-size: 18px; gap: 10px; }
.dense ul { font-size: 16.5px; gap: 9px; line-height: 1.34; }
.dense table { font-size: 15px; }
.text.dense ul { font-size: 19px; gap: 12px; }
.text.dense table { font-size: 15.5px; }
.cover h1 { font-size: 44px; margin-top: 40px; margin-bottom: 34px; max-width: 900px; }
.cover ul { font-size: 23px; gap: 16px; max-width: 980px; }
.appendix ul { font-size: 16.5px; gap: 12px; }
footer { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; margin-top: 12px; min-height: 20px; }
.caption { margin: 0; font-size: 13.5px; line-height: 1.35; color: #6b5b60; max-width: 1040px; }
.number { margin-left: auto; font-size: 13.5px; color: #8b7c80; font-variant-numeric: tabular-nums; }
"""


def page(slides: list[Slide]) -> str:
    faces = "".join(
        f'@font-face {{ font-family: "Onest"; font-style: normal; font-weight: 100 900; '
        f'src: url("{data_uri(FONTS / name, "font/woff2")}") format("woff2"); unicode-range: {ranges}; }}'
        for name, ranges in FONT_RANGES.items()
        if (FONTS / name).is_file()
    )
    body = "".join(render(slide) for slide in slides)
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Лента рекомендаций под клиента</title>'
        f"<style>{faces}{CSS}</style></head><body>{body}</body></html>"
    )


def browser() -> str:
    candidates = [os.environ.get("SLIDES_BROWSER", "")]
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if local.is_dir():
        candidates += [str(p) for p in sorted(local.glob("chromium_headless_shell-*/*/chrome-headless-shell*"))][::-1]
    for folder in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        if folder:
            candidates.append(str(Path(folder) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
            candidates.append(str(Path(folder) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    candidates += [shutil.which(name) or "" for name in ("chromium", "chromium-browser", "google-chrome", "msedge")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise SystemExit("Не найден Chromium: задайте путь в переменной SLIDES_BROWSER")


def main(argv: list[str]) -> int:
    slides = parse(SOURCE.read_text(encoding="utf-8"))
    document = page(slides)
    if "--html" in argv:
        OUTPUT.with_suffix(".html").write_text(document, encoding="utf-8")
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "slides.html"
        source.write_text(document, encoding="utf-8")
        subprocess.run(
            [browser(), "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={OUTPUT}",
             source.as_uri()],
            check=True, capture_output=True, timeout=120,
        )
    print(f"Слайдов: {len(slides)}; файл: {OUTPUT.relative_to(ROOT)}; размер: {OUTPUT.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
