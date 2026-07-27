from __future__ import annotations
from pathlib import Path
import pandas as pd
from .models import AnalysisResult


def export_report(result: AnalysisResult, template_path: str | Path, output_path: str | Path) -> Path:
    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        df = pd.read_excel(template_path)
        # Если шаблон содержит строку с описанием полей, оставляем ее и добавляем строку результата ниже.
    except Exception:
        df = pd.DataFrame()

    e = result.extracted
    row = {
        "tender_id": e.tender_id,
        "name_product": e.name_product or e.tender_subject,
        "product_type": e.product_type,
        "alloy": e.alloy,
        "thickness": e.thickness_mm,
        "width": e.width_mm,
        "length": e.length_mm,
        "quantity": e.quantity_kg,
        "batch": None,
        "gost": e.gost,
        "ost": e.ost,
        "tu": e.tu,
        "coating": e.coating,
        "coating_type": e.coating_type,
        "RAL": e.ral,
        "metalworking": e.metalworking,
        "drawings": "да" if e.has_drawings else "нет" if e.has_drawings is False else None,
        "place_of_delivery": e.place_of_delivery,
        "delivery_time": e.delivery_time_days,
        "delivery_schedule": e.delivery_schedule,
        "payment_terms": e.payment_terms,
        "partial_delivery": e.partial_delivery,
        "application_deadline": e.application_deadline,
        "customer_name": e.customer_name,
        "customer_inn": e.customer_inn,
        "nmck": e.nmck,
        "missing_data": ", ".join(sorted(set(e.missing_fields + result.match.missing_fields))),
        "reason": result.reason,
        "link_to_tender": e.link_to_tender,
        "decision": result.decision,
        "score": result.score,
        "risk_level": result.risk_level,
        "found_keywords": ", ".join(result.found_keywords[:20]),
        "stop_keywords": ", ".join(result.stop_keywords[:20]),
    }

    # Нормализуем имена колонок шаблона с переносами строк.
    df.columns = [str(c).strip() for c in df.columns]
    for col in row:
        if col not in df.columns:
            df[col] = None
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_excel(output_path, index=False)
    return output_path
