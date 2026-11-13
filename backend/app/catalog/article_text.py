"""Подготовка локального текста статей для поиска."""

from html.parser import HTMLParser

_INVISIBLE = {"script", "style", "template", "noscript", "svg", "iframe"}
_BLOCKS = {"p", "div", "li", "br", "section", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6"}


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ignored: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _INVISIBLE:
            self.ignored.append(tag)
        elif not self.ignored and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.ignored and tag == self.ignored[-1]:
            self.ignored.pop()
        elif not self.ignored and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCKS and not self.ignored:
            self.parts.append("\n")

    def handle_data(self, data):
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
