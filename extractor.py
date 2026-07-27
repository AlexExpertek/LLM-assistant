from __future__ import annotations
import json
import os
import re
import requests
from .models import ExtractedTender
from .normalizers import normalize_product_type, normalize_alloy, to_float, extract_days, clean_text

PRODUCT_PATTERNS = [
    (r"лента", "лента"),
    (r"штрипс", "штрипсы"),
    (r"рулон", "рулон"),
    (r"лист", "лист"),
    (r"плит", "плита"),
    (r"фольг", "фольга"),
    (r"шин", "шина"),
    (r"профил", "профиль"),
    (r"труб", "труба"),
    (r"прут", "пруток"),
    (r"катанк", "катанка"),
    (r"провол", "проволока"),
]

ALLOY_RE = re.compile(r"\b(АД\d{1,2}[А-ЯA-Z]?|АД00|АМг\d|АМц|Д16Т?|А\dЕ?|\d{4}[AА]?|\d{4})\b", re.IGNORECASE)
SIZE_RE = re.compile(r"(?P<t>\d+[,.]?\d*)\s*[xх×*]\s*(?P<w>\d+[,.]?\d*)(?:\s*[xх×*]\s*(?P<l>\d+[,.]?\d*))?", re.IGNORECASE)
GOST_RE = re.compile(r"ГОСТ\s*[Р ]?\s*\d+[\d\-–—]*", re.IGNORECASE)
INN_RE = re.compile(r"\bИНН\s*[:№-]?\s*(\d{10}|\d{12})\b", re.IGNORECASE)
NMCK_RE = re.compile(r"(?:НМЦК|начальн\w*\s+максимальн\w*\s+цен\w*)[^\d]{0,40}([\d\s]+(?:[,.]\d{1,2})?)", re.IGNORECASE)
QTY_RE = re.compile(r"(?:количество|объем|масса)[^\d]{0,30}([\d\s]+(?:[,.]\d+)?)\s*(кг|килограмм|т|тонн|тонна|тонны)", re.IGNORECASE)


def regex_extract(text: str) -> ExtractedTender:
    text_compact = re.sub(r"\s+", " ", text)
    subject = text_compact[:500]

    product_type = None
    for pattern, product in PRODUCT_PATTERNS:
        if re.search(pattern, text_compact, re.IGNORECASE):
            product_type = product
            break

    alloy = None
    m = ALLOY_RE.search(text_compact)
    if m:
        alloy = normalize_alloy(m.group(1))

    thickness = width = length = None
    m = SIZE_RE.search(text_compact)
    if m:
        thickness = to_float(m.group("t"))
        width = to_float(m.group("w"))
        length = to_float(m.group("l"))

    gost = None
    m = GOST_RE.search(text_compact)
    if m:
        gost = clean_text(m.group(0))

    customer_inn = None
    m = INN_RE.search(text_compact)
    if m:
        customer_inn = m.group(1)

    nmck = None
    m = NMCK_RE.search(text_compact)
    if m:
        nmck = to_float(m.group(1).replace(" ", ""))

    quantity_kg = None
    m = QTY_RE.search(text_compact)
    if m:
        qty = to_float(m.group(1).replace(" ", ""))
        unit = (m.group(2) or "").lower()
        if qty is not None:
            quantity_kg = qty * 1000 if unit.startswith("т") or "тон" in unit else qty

    delivery_time_days = extract_days(text_compact)
    has_drawings = bool(re.search(r"чертеж|эскиз|черт\." , text_compact, re.IGNORECASE))

    missing = []
    for field, value in {
        "product_type": product_type,
        "alloy": alloy,
        "thickness_mm": thickness,
        "width_mm": width,
        "quantity_kg": quantity_kg,
        "payment_terms": None,
    }.items():
        if value in (None, ""):
            missing.append(field)

    return ExtractedTender(
        tender_subject=subject,
        product_type=product_type,
        name_product=subject,
        alloy=alloy,
        thickness_mm=thickness,
        width_mm=width,
        length_mm=length,
        gost=gost,
        customer_inn=customer_inn,
        nmck=nmck,
        quantity_kg=quantity_kg,
        delivery_time_days=delivery_time_days,
        has_drawings=has_drawings,
        raw_text=text[:12000],
        missing_fields=missing,
    )


def llm_extract(text: str, model: str | None = None) -> ExtractedTender:
    """LLM extraction через OpenAI-compatible Chat Completions API.
    Если переменные окружения не заданы, используйте regex_extract().
    """
    api_base = os.getenv("LLM_API_BASE", "").rstrip("/")
    api_key = os.getenv("LLM_API_KEY")
    model = model or os.getenv("LLM_MODEL", "gpt-4.1-mini")
    if not api_base or not api_key:
        raise RuntimeError("LLM_API_BASE/LLM_API_KEY are not configured")

    prompt = f"""
Ты извлекаешь параметры тендерной документации по алюминиевому прокату.
Верни только валидный JSON без markdown.

Поля JSON:
tender_id, platform, customer_name, customer_inn, tender_subject, product_type,
name_product, alloy, condition, thickness_mm, width_mm, length_mm, quantity_kg,
gost, ost, tu, coating, coating_type, ral, metalworking, has_drawings,
place_of_delivery, delivery_time_days, delivery_schedule, payment_terms,
partial_delivery, application_deadline, link_to_tender, nmck, missing_fields.

Если значения нет — null. missing_fields — список критически недостающих полей.

Текст тендера:
{text[:25000]}
"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Ты точный extractor. Возвращай только JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    r = requests.post(
        f"{api_base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    data["product_type"] = normalize_product_type(data.get("product_type"))
    data["alloy"] = normalize_alloy(data.get("alloy"))
    data["raw_text"] = text[:12000]
    return ExtractedTender(**{k: v for k, v in data.items() if k in ExtractedTender.__dataclass_fields__})
