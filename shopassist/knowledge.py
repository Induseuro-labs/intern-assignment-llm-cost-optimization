"""Help-center index with deterministic lexical retrieval.

Retrieval runs in plain Python, so it costs zero points. Only the handful of
articles it selects are ever placed in a prompt, which keeps the input small
no matter how large the help center grows.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Iterable

from shared import kb
from shopassist.schema import Article

_WORD = re.compile(r"[a-z]+")
_BLOB_SECTION = re.compile(r"^--- (?P<id>[\w-]+) ---\n(?P<body>.*?)(?=^--- [\w-]+ ---$|^## |\Z)", re.M | re.S)
_SUFFIXES = ("ization", "izing", "ized", "able", "ible", "ment", "ing", "ed", "es", "s", "e")
_STOPWORDS = frozenset(
    "a an and any are after be been by can could do for from get had has have i if "
    "in is it may me my no not of on or our please so that the their them they this "
    "to was we were will with you your".split()
)


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    """Lower-case, drop stopwords, and reduce words to a crude stem."""
    return [_stem(w) for w in _WORD.findall(text.lower()) if w not in _STOPWORDS]


def _clean_body(article_id: str, raw: str) -> str:
    """Strip markdown decoration so an article costs as few tokens as possible."""
    lines = [line.strip() for line in raw.splitlines()]
    lines = [line for line in lines if line and line.lstrip("# ").strip() != article_id]
    return " ".join(lines).replace("**", "")


class KnowledgeBase:
    """Searchable collection of help-center articles."""

    def __init__(self, articles: Iterable[Article]):
        self._articles = {a.article_id: a for a in articles}
        self._terms = {
            a.article_id: Counter(tokenize(f"{a.article_id} {a.body}"))
            for a in self._articles.values()
        }
        doc_freq = Counter(term for terms in self._terms.values() for term in terms)
        total = max(len(self._articles), 1)
        self._idf = {term: math.log(1 + total / df) for term, df in doc_freq.items()}

    @classmethod
    def from_help_center(cls) -> "KnowledgeBase":
        """Index the citeable articles stored under ``data/kb``."""
        return cls(
            Article(aid, _clean_body(aid, kb.load_article(aid))) for aid in kb.article_ids()
        )

    @classmethod
    def from_blob(cls, blob: str) -> "KnowledgeBase":
        """Index a concatenated help-center dump, keeping only citeable sections.

        Sections without an article id (routing notes, macros, separators)
        cannot back a decision, so they are discarded at index time.
        """
        return cls(
            Article(m["id"], _clean_body(m["id"], m["body"])) for m in _BLOB_SECTION.finditer(blob)
        )

    @property
    def article_ids(self) -> list[str]:
        return sorted(self._articles)

    def __contains__(self, article_id: object) -> bool:
        return article_id in self._articles

    def __len__(self) -> int:
        return len(self._articles)

    def search(self, query: str, top_k: int = 2) -> list[Article]:
        """Return the ``top_k`` articles sharing the rarest terms with ``query``."""
        query_terms = set(tokenize(query))
        scored = [
            (sum(self._idf[t] for t in query_terms if t in terms), article_id)
            for article_id, terms in self._terms.items()
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self._articles[article_id] for _, article_id in scored[:top_k]]


@lru_cache(maxsize=1)
def default_knowledge_base() -> KnowledgeBase:
    """Process-wide index, built once."""
    return KnowledgeBase.from_help_center()
