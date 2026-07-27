from __future__ import annotations
import re
from typing import Any

CYR_TO_LAT = str.maketrans({"А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T", "Х": "X"})


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def normalize_product_type(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text_l = text.lower().replace("ё", "е")
    mapping = {
        "алюминиевая лента": "лента",
        "лента алюминиевая": "лента",
        "лента": "лента",
        "штрипс": "штрипсы",
        "штрипсы": "штрипсы",
        "рулон": "рулон",
        "лист": "лист",
        "плита": "плита",
        "фольга": "фольга",
        "тиснен": "лента тисненная",
        "тисненая": "лента тисненная",
        "тисненная": "лента тисненная",
        "шина": "шина",
        "профиль": "профиль",
        "труба": "труба",
        "пруток": "пруток",
        "катанка": "катанка",
        "проволока": "проволока",
    }
    for key, normalized in mapping.items():
        if key in text_l:
            return normalized
    return text_l


def normalize_alloy(value: Any) -> str | None:
    text = clean_text(value)
    if not text or text.lower() in {"nan", "none", "не указан", "отсутствует"}:
        return None
    text = text.upper().replace(" ", "")
    # Частые исправления регистра/кириллица-латиница в цифровых сплавах
    if re.match(r"^\d", text):
        text = text.translate(CYR_TO_LAT)
    text = text.replace("АД-", "АД").replace("АМГ", "АМг").replace("АМЦ", "АМц")
    text = text.replace("АД", "АД")
    # Возвращаем привычное написание для российских сплавов
    text = text.replace("АМГ", "АМг").replace("АМЦ", "АМц")
    return text


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            if value != value:
                return None
        except Exception:
            pass
        return float(value)
    text = clean_text(value)
    if not text:
        return None
    text = text.replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def normalize_text_for_search(text: str | None) -> str:
    if not text:
        return ""
    text = text.lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def extract_days(text: str | None) -> float | None:
    if not text:
        return None
    text_l = normalize_text_for_search(text)
    m = re.search(r"(\d+)\s*(?:календарн\w*|рабоч\w*)?\s*(?:дн|день|дней|дня)", text_l)
    return float(m.group(1)) if m else None
