"""Lexical search over the help center, in plain Python.

Searching costs zero points: only the couple of policies the ranking selects
ever reach a prompt, so the bill stays flat no matter how large the help
center grows. Ranking uses term-frequency-free IDF scoring over lightly
stemmed words, which is enough for a catalogue of short, distinctly worded policies.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Iterable

from shared import kb
from copilot.model import Policy

_TOKEN_SPLIT = re.compile(r"[a-z]+")
_DUMP_SECTION = re.compile(
    r"^--- (?P<id>[\w-]+) ---\n(?P<body>.*?)(?=^--- [\w-]+ ---$|^## |\Z)", re.M | re.S
)
_ENDINGS = ("ization", "izing", "ized", "able", "ible", "ment", "ing", "ed", "es", "s", "e")
_IGNORED_WORDS = frozenset(
    "a an and any are after be been by can could do for from get had has have i if "
    "in is it may me my no not of on or our please so that the their them they this "
    "to was we were will with you your".split()
)


def _chop_ending(word: str) -> str:
    """Crude stemmer: strip the longest known suffix, keep at least 3 letters."""
    for ending in _ENDINGS:
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def words_of(text: str) -> list[str]:
    """Lower-case the text, drop filler words, reduce each word to its stem."""
    return [
        _chop_ending(w) for w in _TOKEN_SPLIT.findall(text.lower()) if w not in _IGNORED_WORDS
    ]


def _strip_markdown(article_id: str, raw: str) -> str:
    """Remove markdown decoration so a policy costs as few tokens as possible."""
    kept = []
    for line in raw.splitlines():
        line = line.strip()
        if line and line.lstrip("# ").strip() != article_id:
            kept.append(line)
    return " ".join(kept).replace("**", "")


class PolicyIndex:
    """Searchable collection of help-center policies."""

    def __init__(self, policies: Iterable[Policy]):
        self._policies = {p.article_id: p for p in policies}
        self._bag_of_words = {
            article_id: Counter(words_of(f"{article_id} {p.text}"))
            for article_id, p in self._policies.items()
        }
        occurrences = Counter(
            term for bag in self._bag_of_words.values() for term in bag
        )
        count = max(len(self._policies), 1)
        self._weight = {
            term: math.log(1 + count / docs) for term, docs in occurrences.items()
        }

    @classmethod
    def from_help_center(cls) -> "PolicyIndex":
        """Index the citeable policies stored under ``data/kb``."""
        return cls(
            Policy(aid, _strip_markdown(aid, kb.load_article(aid)))
            for aid in kb.article_ids()
        )

    @classmethod
    def from_dump(cls, dump: str) -> "PolicyIndex":
        """Build from a concatenated help-center dump (the Question 2 blob).

        Filler sections without an article id (routing notes, carrier macros,
        separator runs) can never back a decision, so they are dropped here
        rather than paid for later.
        """
        return cls(
            Policy(m["id"], _strip_markdown(m["id"], m["body"]))
            for m in _DUMP_SECTION.finditer(dump)
        )

    @property
    def article_ids(self) -> list[str]:
        return sorted(self._policies)

    def __contains__(self, article_id: object) -> bool:
        return article_id in self._policies

    def __len__(self) -> int:
        return len(self._policies)

    def rank(self, query: str, limit: int = 2) -> list[Policy]:
        """Return the ``limit`` policies sharing the rarest terms with ``query``."""
        wanted = set(words_of(query))
        ranked = [
            (sum(self._weight[t] for t in wanted if t in bag), article_id)
            for article_id, bag in self._bag_of_words.items()
        ]
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return [self._policies[article_id] for _, article_id in ranked[:limit]]


@lru_cache(maxsize=1)
def load_index() -> PolicyIndex:
    """One process-wide index over ``data/kb``."""
    return PolicyIndex.from_help_center()
