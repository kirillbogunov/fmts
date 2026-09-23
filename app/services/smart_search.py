from __future__ import annotations
import re
from typing import Callable, Iterable, TypeVar

T = TypeVar('T')
_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
# Compact Russian suffix set for practical ServiceDesk search. It is deliberately
# conservative: exact substrings keep the highest weight, stems add word-form tolerance.
_SUFFIXES = tuple(sorted({
    'иями','ями','ами','его','ого','ему','ому','ими','ыми','ией','ией','ов','ев','ей','ам','ям','ах','ях','ом','ем','ами','ями',
    'ый','ий','ая','яя','ое','ее','ые','ие','ого','его','ому','ему','ых','их','ую','юю','ой','ей','ым','им',
    'а','я','ы','и','у','ю','е','о','ь','й','ов','ев','ей','ом','ем','ам','ям','ах','ях','ыи'
}, key=len, reverse=True))

def _norm(s: str) -> str:
    return ' '.join(_WORD_RE.findall((s or '').lower().replace('ё','е')))

def _stem(word: str) -> str:
    w = word.lower().replace('ё','е')
    if len(w) <= 4:
        return w
    for suffix in _SUFFIXES:
        if len(w) - len(suffix) >= 4 and w.endswith(suffix):
            return w[:-len(suffix)]
    return w

def _stems(s: str) -> list[str]:
    return [_stem(x) for x in _WORD_RE.findall((s or '').lower().replace('ё','е')) if len(x) > 1]

def relevance(query: str, text: str) -> int:
    qn = _norm(query)
    tn = _norm(text)
    if not qn or not tn:
        return 0
    score = 0
    if qn in tn:
        score += 120
    q_words = _WORD_RE.findall(qn)
    for word in q_words:
        if word in tn:
            score += 25
    q_stems = _stems(qn)
    t_stems = set(_stems(tn))
    matched = sum(1 for s in q_stems if s in t_stems)
    score += matched * 18
    if q_stems and matched == len(q_stems):
        score += 35
    return score

def rank_search(query: str, items: Iterable[T], text_getter: Callable[[T], str], limit: int = 50) -> list[T]:
    ranked = []
    for idx, item in enumerate(items):
        score = relevance(query, text_getter(item))
        if score:
            ranked.append((score, -idx, item))
    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [x[2] for x in ranked[:limit]]
