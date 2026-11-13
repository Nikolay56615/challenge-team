"""Подготовка локального текста статей для поиска."""

from collections.abc import Iterator
from html.parser import HTMLParser

_INVISIBLE = {"script", "style", "template", "noscript", "svg", "iframe"}
_BLOCKS = {"p", "div", "li", "br", "section", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _VisibleText(HTMLParser):
    def __init__(self, headings: bool = False) -> None:
        super().__init__()
        self.ignored: list[str] = []
        self.parts: list[str] = []
        self.headings = headings

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _INVISIBLE:
            self.ignored.append(tag)
        elif not self.ignored and tag in _BLOCKS:
            self.parts.append("\n")
            if self.headings and tag in _HEADINGS:
                self.parts.append("\0")

    def handle_endtag(self, tag: str) -> None:
        if self.ignored and tag == self.ignored[-1]:
            self.ignored.pop()
        elif not self.ignored and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCKS and not self.ignored:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data.replace("\n", " ").replace("\r", " "))


def article_paragraphs(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    parser = _VisibleText()
    parser.feed(value)
    parser.close()
    return tuple(text for part in "".join(parser.parts).splitlines() if (text := " ".join(part.split())))


def article_description(value: object) -> str | None:
    return " ".join(article_paragraphs(value))[:1000].rstrip() or None


def article_sections(value: object, heading: str = "") -> Iterator[tuple[str, str]]:
    if not isinstance(value, str):
        return
    parser = _VisibleText(headings=True)
    parser.feed(value)
    parser.close()
    for line in "".join(parser.parts).splitlines():
        if line.startswith("\0"):
            heading = " ".join(line[1:].split()) or heading
            yield heading, ""
        elif text := " ".join(line.split()):
            yield heading, text
