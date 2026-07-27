from __future__ import annotations
from pathlib import Path
from .loaders import load_settings, load_yaml, load_keywords, load_product_matrix
from .parsers import parse_tender_file
from .extractor import regex_extract, llm_extract
from .keyword_filter import find_keywords
from .product_matcher import match_product
from .rag_retriever import LocalTfidfRagRetriever
from .scoring import calculate_score
from .decision_engine import detect_critical_risks, make_decision
from .report_export import export_report
from .models import AnalysisResult


def analyze_tender(tender_file: str | Path, settings_path: str | Path = "config/settings.json", use_llm: bool | None = None) -> AnalysisResult:
    settings = load_settings(settings_path)
    paths = settings["paths"]
    rules = load_yaml(paths["tender_rules"])
    product_matrix = load_product_matrix(paths["product_matrix"])
    include_keywords, stop_keywords = load_keywords(paths["keywords"])

    tender_text = parse_tender_file(tender_file)
    llm_enabled = settings.get("llm", {}).get("enabled", False) if use_llm is None else use_llm
    if llm_enabled:
        try:
            extracted = llm_extract(tender_text)
        except Exception as exc:
            extracted = regex_extract(tender_text)
            extracted.missing_fields.append(f"llm_extract_failed: {exc}")
    else:
        extracted = regex_extract(tender_text)

    found_include, found_stop = find_keywords(tender_text, include_keywords, stop_keywords)
    match = match_product(extracted, product_matrix)

    retriever = LocalTfidfRagRetriever(
        chunk_size_chars=settings.get("rag", {}).get("chunk_size_chars", 1800),
        chunk_overlap_chars=settings.get("rag", {}).get("chunk_overlap_chars", 250),
    )
    retriever.build_from_dir(paths["rag_docs_dir"])
    rag_query = "\n".join([
        f"Предмет: {extracted.tender_subject}",
        f"Продукт: {extracted.product_type}",
        f"Сплав: {extracted.alloy}",
        f"Толщина: {extracted.thickness_mm}",
        f"Ширина: {extracted.width_mm}",
        f"Количество: {extracted.quantity_kg}",
        f"Срок поставки: {extracted.delivery_time_days}",
        f"Найденные ключевые слова: {', '.join(found_include[:10])}",
    ])
    rag_context = retriever.retrieve(rag_query, top_k=settings.get("rag", {}).get("top_k", 6))

    score, score_warnings = calculate_score(extracted, match, found_include, found_stop, rules)
    critical_risks = detect_critical_risks(extracted, found_stop, rules)
    decision, risk_level, reason = make_decision(score, extracted, match, critical_risks, rules)

    return AnalysisResult(
        extracted=extracted,
        found_keywords=found_include,
        stop_keywords=found_stop,
        match=match,
        score=score,
        decision=decision,
        risk_level=risk_level,
        reason=reason,
        rag_context=rag_context,
        warnings=score_warnings + match.comments + critical_risks,
    )


def analyze_and_export(tender_file: str | Path, output_file: str | Path | None = None, settings_path: str | Path = "config/settings.json") -> tuple[AnalysisResult, Path]:
    settings = load_settings(settings_path)
    result = analyze_tender(tender_file, settings_path=settings_path)
    if output_file is None:
        output_file = Path(settings["paths"]["outputs_dir"]) / "tender_report.xlsx"
    output_path = export_report(result, settings["paths"]["report_template"], output_file)
    return result, output_path
