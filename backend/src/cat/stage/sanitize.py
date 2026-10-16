"""Vorfilter für KI-erzeugte Stage-Inhalte.

Die eigentliche Sicherheitsgrenze ist die Sandbox-iframe im Browser (sandbox="allow-scripts"
ohne allow-same-origin, strikte CSP). Dieser Filter begrenzt Größe und entfernt Konstrukte,
die dort ohnehin nichts verloren haben, damit das Modell früh eine klare Rückmeldung bekommt.
"""

import re

MAX_HTML_CHARS = 200_000
MAX_MARKDOWN_CHARS = 100_000
MAX_TITLE_CHARS = 80


class ContentError(ValueError):
    """Inhalt abgelehnt; die Meldung geht als Werkzeugergebnis an das Modell."""


_FLAGS = re.IGNORECASE | re.DOTALL
# Elemente, die Navigation, fremde Inhalte oder Seitenverhalten verändern könnten.
_BLOCK_TAGS = re.compile(r"</?\s*(iframe|frame|frameset|object|embed|applet)\b[^>]*>", _FLAGS)
_VOID_TAGS = re.compile(r"<\s*(base|link)\b[^>]*>", _FLAGS)
_META_HTTP = re.compile(r"<\s*meta\b[^>]*http-equiv[^>]*>", _FLAGS)
_EXTERNAL_SCRIPT = re.compile(r"<\s*script\b[^>]*\bsrc\s*=[^>]*>\s*(</\s*script\s*>)?", _FLAGS)


def clean_title(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise ContentError("Der Titel darf nicht leer sein.")
    return title[:MAX_TITLE_CHARS]


def sanitize_html(html: str) -> str:
    html = html.strip()
    if not html:
        raise ContentError("Das HTML ist leer.")
    if len(html) > MAX_HTML_CHARS:
        raise ContentError(
            f"Das HTML ist zu groß ({len(html)} Zeichen, erlaubt {MAX_HTML_CHARS}). Bitte kürzen."
        )
    html = _BLOCK_TAGS.sub("", html)
    html = _VOID_TAGS.sub("", html)
    html = _META_HTTP.sub("", html)
    html = _EXTERNAL_SCRIPT.sub("", html)
    return html


def sanitize_markdown(text: str) -> str:
    text = text.strip()
    if not text:
        raise ContentError("Der Text ist leer.")
    if len(text) > MAX_MARKDOWN_CHARS:
        raise ContentError(f"Der Text ist zu lang (erlaubt {MAX_MARKDOWN_CHARS} Zeichen).")
    return text
