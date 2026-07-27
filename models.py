from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ExtractedTender:
    tender_id: str | None = None
    platform: str | None = None
    customer_name: str | None = None
    customer_inn: str | None = None
    tender_subject: str | None = None
    product_type: str | None = None
    name_product: str | None = None
    alloy: str | None = None
    condition: str | None = None
    thickness_mm: float | None = None
    width_mm: float | None = None
    length_mm: float | None = None
    quantity_kg: float | None = None
    gost: str | None = None
    ost: str | None = None
    tu: str | None = None
    coating: str | None = None
    coating_type: str | None = None
    ral: str | None = None
    metalworking: str | None = None
    has_drawings: bool | None = None
    place_of_delivery: str | None = None
    delivery_time_days: float | None = None
    delivery_schedule: str | None = None
    payment_terms: str | None = None
    partial_delivery: str | None = None
    application_deadline: str | None = None
    link_to_tender: str | None = None
    nmck: float | None = None
    raw_text: str | None = None
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MatchResult:
    product_match: bool | str
    alloy_match: bool | str
    size_match: bool | str
    quantity_match: bool | str
    delivery_match: bool | str
    matched_rows_count: int = 0
    missing_fields: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)


@dataclass
class AnalysisResult:
    extracted: ExtractedTender
    found_keywords: list[str]
    stop_keywords: list[str]
    match: MatchResult
    score: int
    decision: str
    risk_level: str
    reason: str
    rag_context: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data
