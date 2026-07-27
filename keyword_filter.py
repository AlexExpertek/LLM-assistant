from __future__ import annotations
from .normalizers import normalize_text_for_search


def find_keywords(text: str, include_keywords: list[str], stop_keywords: list[str]) -> tuple[list[str], list[str]]:
    normalized = normalize_text_for_search(text)
    found_include = [kw for kw in include_keywords if normalize_text_for_search(kw) in normalized]
    found_stop = [kw for kw in stop_keywords if normalize_text_for_search(kw) in normalized]
    return sorted(set(found_include)), sorted(set(found_stop))
