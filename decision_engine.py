from __future__ import annotations
from .models import ExtractedTender, MatchResult
from .normalizers import normalize_text_for_search


def detect_critical_risks(extracted: ExtractedTender, stop_keywords: list[str], rules: dict) -> list[str]:
    risks: list[str] = []
    text = normalize_text_for_search((extracted.raw_text or "") + " " + (extracted.tender_subject or ""))

    if stop_keywords:
        risks.append("Найдены стоп-слова: " + ", ".join(stop_keywords[:10]))

    # Универсальные стоп-факторы независимо от структуры YAML
    hard_phrases = [
        "лом алюминия", "металлолом", "прием лома", "сбор алюминиевого лома",
        "утилизация", "демонтаж", "ремонт", "радиатор", "окна", "двери"
    ]
    for phrase in hard_phrases:
        if phrase in text:
            risks.append(f"Стоп-фактор: {phrase}")

    if extracted.delivery_time_days is not None and extracted.delivery_time_days < 5:
        risks.append("Срок поставки менее 5 дней")

    return sorted(set(risks))


def make_decision(score: int, extracted: ExtractedTender, match: MatchResult, critical_risks: list[str], rules: dict) -> tuple[str, str, str]:
    missing = set(extracted.missing_fields or []) | set(match.missing_fields or [])

    if critical_risks:
        return (
            "reject_or_low_priority",
            "critical",
            "Тендер имеет критические стоп-факторы: " + "; ".join(critical_risks[:5]),
        )

    if match.product_match is False:
        return "reject_or_low_priority", "high", "Продукция не найдена в продуктовой матрице компании"

    if match.alloy_match is False:
        return "manual_review", "medium", "Продукт найден, но сплав не подтвержден по product_matrix: нужна ручная проверка"

    if match.size_match is False:
        return "manual_review", "medium", "Размеры не подтверждены по product_matrix: нужна проверка специалиста"

    if missing:
        return (
            "manual_review",
            "medium",
            "Тендер потенциально подходит, но не хватает данных: " + ", ".join(sorted(missing)),
        )

    if score >= 75:
        return "participate_candidate", "low", "Продукция, сплав и базовые параметры соответствуют правилам; можно передавать на коммерческий расчет"
    if score >= 50:
        return "manual_review", "medium", "Тендер частично соответствует правилам, требуется ручная проверка"
    return "reject_or_low_priority", "high", "Низкий score по правилам отбора"
