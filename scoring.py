from __future__ import annotations
from .models import ExtractedTender, MatchResult


def _get_weight(rules: dict, key: str, default: int) -> int:
    # Поддерживает разные варианты структуры tender_rules.yaml.
    scoring = rules.get("scoring", {}) if isinstance(rules, dict) else {}
    weights = scoring.get("weights", scoring.get("criteria", {})) if isinstance(scoring, dict) else {}
    if isinstance(weights, dict):
        value = weights.get(key)
        if isinstance(value, dict):
            return int(value.get("weight", default))
        if isinstance(value, (int, float)):
            return int(value)
    return default


def calculate_score(extracted: ExtractedTender, match: MatchResult, found_keywords: list[str], stop_keywords: list[str], rules: dict) -> tuple[int, list[str]]:
    warnings: list[str] = []
    score = 0

    weights = {
        "product_match": _get_weight(rules, "product_match", 30),
        "alloy_match": _get_weight(rules, "alloy_match", 15),
        "size_match": _get_weight(rules, "size_match", 15),
        "quantity_match": _get_weight(rules, "quantity_match", 10),
        "delivery_match": _get_weight(rules, "delivery_match", 10),
        "documentation_quality": _get_weight(rules, "documentation_quality", 10),
        "risk_check": _get_weight(rules, "risk_check", 10),
    }

    if match.product_match is True:
        score += weights["product_match"]
    elif match.product_match == "unknown":
        score += weights["product_match"] // 3
        warnings.append("Тип продукции не подтвержден полностью")

    if match.alloy_match is True:
        score += weights["alloy_match"]
    elif match.alloy_match == "unknown":
        score += weights["alloy_match"] // 3
        warnings.append("Сплав не распознан или отсутствует")

    if match.size_match is True:
        score += weights["size_match"]
    elif match.size_match == "unknown":
        score += weights["size_match"] // 3
        warnings.append("Размеры распознаны не полностью")

    if match.quantity_match is True:
        score += weights["quantity_match"]
    elif match.quantity_match == "unknown":
        score += weights["quantity_match"] // 3
        warnings.append("Количество/партия не распознаны")

    if match.delivery_match is True or extracted.delivery_time_days is not None:
        score += weights["delivery_match"]
    else:
        score += weights["delivery_match"] // 3
        warnings.append("Срок поставки требует ручной проверки")

    doc_points = 0
    if extracted.gost or extracted.tu or extracted.ost:
        doc_points += weights["documentation_quality"] // 2
    if extracted.tender_subject and len(extracted.tender_subject) > 20:
        doc_points += weights["documentation_quality"] // 2
    score += min(doc_points, weights["documentation_quality"])

    if not stop_keywords:
        score += weights["risk_check"]
    else:
        score -= min(30, 10 * len(stop_keywords))
        warnings.append("Найдены стоп-слова: " + ", ".join(stop_keywords[:5]))

    if found_keywords:
        score += 5

    return max(0, min(100, int(score))), warnings
