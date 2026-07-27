from __future__ import annotations
import pandas as pd
from .models import ExtractedTender, MatchResult
from .normalizers import normalize_product_type, normalize_alloy


def _in_range(value: float | None, min_value: float | None, max_value: float | None) -> bool | str:
    if value is None:
        return "unknown"
    if min_value is not None and value < min_value:
        return False
    if max_value is not None and value > max_value:
        return False
    return True


def match_product(extracted: ExtractedTender, product_matrix: pd.DataFrame) -> MatchResult:
    missing = []
    comments = []

    product_type = normalize_product_type(extracted.product_type)
    alloy = normalize_alloy(extracted.alloy)

    if not product_type:
        missing.append("product_type")
        return MatchResult("unknown", "unknown", "unknown", "unknown", "unknown", 0, missing, ["Не удалось определить тип продукции"])

    candidates = product_matrix[product_matrix["product_type_norm"] == product_type].copy()
    product_match: bool | str = len(candidates) > 0
    if not product_match:
        return MatchResult(False, "unknown", "unknown", "unknown", "unknown", 0, missing, [f"Продукт '{product_type}' не найден в product_matrix"])

    alloy_match: bool | str = "unknown"
    if not alloy:
        missing.append("alloy")
        comments.append("Сплав не указан: нужна ручная проверка")
    else:
        by_alloy = candidates[candidates["alloy_norm"] == alloy].copy()
        alloy_match = len(by_alloy) > 0
        if alloy_match:
            candidates = by_alloy
        else:
            comments.append(f"Сплав {alloy} не найден для продукта {product_type}")

    # Размеры: если не указаны — unknown и ручная проверка.
    if extracted.thickness_mm is None:
        missing.append("thickness_mm")
        thickness_ok: bool | str = "unknown"
    else:
        thickness_mask = candidates.apply(
            lambda r: _in_range(extracted.thickness_mm, r.get("thickness_min_mm"), r.get("thickness_max_mm")) is True,
            axis=1,
        )
        thickness_ok = bool(thickness_mask.any())
        candidates = candidates[thickness_mask] if thickness_ok else candidates

    if extracted.width_mm is None:
        missing.append("width_mm")
        width_ok: bool | str = "unknown"
    else:
        width_mask = candidates.apply(
            lambda r: _in_range(extracted.width_mm, r.get("width_min_mm"), r.get("width_max_mm")) is True,
            axis=1,
        )
        width_ok = bool(width_mask.any())
        candidates = candidates[width_mask] if width_ok else candidates

    if thickness_ok == "unknown" or width_ok == "unknown":
        size_match: bool | str = "unknown"
    else:
        size_match = bool(thickness_ok and width_ok)

    quantity_match: bool | str = "unknown"
    if extracted.quantity_kg is None:
        missing.append("quantity_kg")
        comments.append("Количество не указано: невозможно проверить минимальную партию")
    elif "min_batch" in candidates.columns and not candidates.empty:
        min_batch = candidates["min_batch"].dropna().min()
        quantity_match = True if pd.isna(min_batch) else extracted.quantity_kg >= float(min_batch)
        if quantity_match is False:
            comments.append(f"Количество {extracted.quantity_kg} кг ниже минимальной партии {min_batch} кг")

    delivery_match: bool | str = "unknown"
    if extracted.delivery_time_days is None:
        comments.append("Срок поставки не указан или не распознан")
    elif "delivery_time_max" in candidates.columns and not candidates.empty:
        max_delivery = candidates["delivery_time_max"].dropna().max()
        delivery_match = True if pd.isna(max_delivery) else extracted.delivery_time_days >= 0
        # На этом этапе не отклоняем за больший срок: часто это плюс. Короткий срок проверяется в tender_rules.

    return MatchResult(
        product_match=product_match,
        alloy_match=alloy_match,
        size_match=size_match,
        quantity_match=quantity_match,
        delivery_match=delivery_match,
        matched_rows_count=len(candidates),
        missing_fields=sorted(set(missing)),
        comments=comments,
    )
