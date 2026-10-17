"""Zerlegt einen Textstrom (LLM-Deltas) in sprechbare Sätze für eine frühe Sprachausgabe."""

import re

# Satzende: . ! ? oder Zeilenumbruch, danach Leerzeichen/Ende. Abkürzungen wie "z. B." und
# Dezimalzahlen ("21,5") sollen nicht trennen.
_ABBREVIATIONS = r"(?<!\bz\.)(?<!\bB\.)(?<!\bbzw\.)(?<!\bca\.)(?<!\bu\.)(?<!\bd\.)(?<!\bNr\.)"
_END = re.compile(_ABBREVIATIONS + r"(?<=[.!?])\s+|\n+")
MIN_SENTENCE = 12  # sehr kurze Stücke ("Ja.") werden mit dem nächsten Satz verbunden


class SentenceChunker:
    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        sentences: list[str] = []
        start = 0
        for match in _END.finditer(self._buffer):
            candidate = self._buffer[start : match.start()].strip()
            if not candidate:
                start = match.end()
                continue
            # Ende muss ein Satzzeichen sein oder ein Zeilenumbruch; kurze Stücke zusammenhalten.
            if len(candidate) < MIN_SENTENCE and not candidate.endswith(("!", "?")):
                continue
            sentences.append(candidate)
            start = match.end()
        self._buffer = self._buffer[start:]
        return sentences

    def flush(self) -> str | None:
        rest = self._buffer.strip()
        self._buffer = ""
        return rest or None
