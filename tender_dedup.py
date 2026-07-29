"""Идемпотентная регистрация тендеров и защита от повторной обработки."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text

from app.core.config import settings


def _database_url() -> str:
    value = getattr(settings, "database_url", None)
    if value is None:
        raise RuntimeError("В settings отсутствует database_url")
    return str(value)


engine = create_engine(_database_url(), pool_pre_ping=True, future=True)


@dataclass(frozen=True)
class DeduplicationResult:
    registry_id: int
    action: str
    claimed: bool
    revision: int
    identity_hash: str
    content_hash: str
    claim_token: str


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def normalize_url(value: Any) -> str:
    if not value:
        return ""
    parts = urlsplit(str(value).strip())
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", "")
    )


def build_identity_hash(source: str, external_id: str) -> str:
    source = normalize_text(source)
    external_id = normalize_text(external_id)
    if not source or not external_id:
        raise ValueError("source и external_id обязательны")
    return hashlib.sha256(f"{source}|{external_id}".encode()).hexdigest()


def build_content_hash(tender_data: dict[str, Any]) -> str:
    payload = {
        "title": normalize_text(tender_data.get("title")),
        "customer_name": normalize_text(tender_data.get("customer_name")),
        "customer_inn": normalize_text(tender_data.get("customer_inn")),
        "law_type": normalize_text(tender_data.get("law_type")),
        "amount": tender_data.get("amount"),
        "currency": normalize_text(tender_data.get("currency")),
        "region": normalize_text(tender_data.get("region")),
        "status": normalize_text(tender_data.get("status")),
        "published_at": tender_data.get("published_at"),
        "submission_deadline": tender_data.get("submission_deadline"),
        "source_url": normalize_url(tender_data.get("source_url")),
        "document_urls": sorted(
            normalize_url(url)
            for url in (tender_data.get("document_urls") or [])
            if url
        ),
        "lots": tender_data.get("lots") or [],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def register_and_claim_tender(
    tender_data: dict[str, Any],
    stale_after_minutes: int = 30,
) -> DeduplicationResult:
    source = normalize_text(tender_data.get("source"))
    external_id = normalize_text(tender_data.get("external_id"))
    identity_hash = build_identity_hash(source, external_id)
    content_hash = build_content_hash(tender_data)
    token = str(uuid.uuid4())

    sql = text("""
    INSERT INTO tender_ingestion_registry (
        source, external_id, identity_hash, content_hash, revision,
        source_url, title, customer_name, raw_payload,
        processing_status, last_event, claim_token, locked_at,
        first_seen_at, last_seen_at, last_changed_at
    )
    VALUES (
        :source, :external_id, :identity_hash, :content_hash, 1,
        :source_url, :title, :customer_name, CAST(:raw_payload AS jsonb),
        'processing', 'new', :token, NOW(), NOW(), NOW(), NOW()
    )
    ON CONFLICT (source, external_id)
    DO UPDATE SET
        source_url = EXCLUDED.source_url,
        title = EXCLUDED.title,
        customer_name = EXCLUDED.customer_name,
        raw_payload = EXCLUDED.raw_payload,
        last_seen_at = NOW(),
        last_event = CASE
            WHEN tender_ingestion_registry.content_hash IS DISTINCT FROM EXCLUDED.content_hash
            THEN 'updated' ELSE 'unchanged' END,
        revision = CASE
            WHEN tender_ingestion_registry.content_hash IS DISTINCT FROM EXCLUDED.content_hash
            THEN tender_ingestion_registry.revision + 1
            ELSE tender_ingestion_registry.revision END,
        last_changed_at = CASE
            WHEN tender_ingestion_registry.content_hash IS DISTINCT FROM EXCLUDED.content_hash
            THEN NOW() ELSE tender_ingestion_registry.last_changed_at END,
        processing_status = CASE
            WHEN tender_ingestion_registry.content_hash IS DISTINCT FROM EXCLUDED.content_hash
              OR tender_ingestion_registry.processing_status IN ('pending', 'failed')
              OR (
                  tender_ingestion_registry.processing_status = 'processing'
                  AND tender_ingestion_registry.locked_at
                      < NOW() - (:stale_minutes * INTERVAL '1 minute')
              )
            THEN 'processing'
            ELSE tender_ingestion_registry.processing_status END,
        claim_token = CASE
            WHEN tender_ingestion_registry.content_hash IS DISTINCT FROM EXCLUDED.content_hash
              OR tender_ingestion_registry.processing_status IN ('pending', 'failed')
              OR (
                  tender_ingestion_registry.processing_status = 'processing'
                  AND tender_ingestion_registry.locked_at
                      < NOW() - (:stale_minutes * INTERVAL '1 minute')
              )
            THEN EXCLUDED.claim_token
            ELSE tender_ingestion_registry.claim_token END,
        locked_at = CASE
            WHEN tender_ingestion_registry.content_hash IS DISTINCT FROM EXCLUDED.content_hash
              OR tender_ingestion_registry.processing_status IN ('pending', 'failed')
              OR (
                  tender_ingestion_registry.processing_status = 'processing'
                  AND tender_ingestion_registry.locked_at
                      < NOW() - (:stale_minutes * INTERVAL '1 minute')
              )
            THEN NOW() ELSE tender_ingestion_registry.locked_at END,
        content_hash = EXCLUDED.content_hash
    RETURNING id, last_event, revision, identity_hash, content_hash,
              claim_token, (claim_token = :token) AS claimed
    """)

    params = {
        "source": source,
        "external_id": external_id,
        "identity_hash": identity_hash,
        "content_hash": content_hash,
        "source_url": normalize_url(tender_data.get("source_url")),
        "title": str(tender_data.get("title") or ""),
        "customer_name": str(tender_data.get("customer_name") or ""),
        "raw_payload": json.dumps(tender_data, ensure_ascii=False, default=str),
        "token": token,
        "stale_minutes": stale_after_minutes,
    }

    with engine.begin() as conn:
        row = conn.execute(sql, params).mappings().one()

    return DeduplicationResult(
        registry_id=row["id"],
        action=row["last_event"],
        claimed=bool(row["claimed"]),
        revision=row["revision"],
        identity_hash=row["identity_hash"],
        content_hash=row["content_hash"],
        claim_token=row["claim_token"],
    )


def mark_pipeline_queued(
    registry_id: int,
    claim_token: str,
    celery_task_id: str | None,
) -> bool:
    sql = text("""
    UPDATE tender_ingestion_registry
    SET processing_status='queued',
        downstream_task_id=:task_id,
        queued_at=NOW(),
        last_error=NULL
    WHERE id=:registry_id
      AND claim_token=:claim_token
      AND processing_status='processing'
    """)
    with engine.begin() as conn:
        result = conn.execute(sql, {
            "registry_id": registry_id,
            "claim_token": claim_token,
            "task_id": celery_task_id,
        })
    return result.rowcount == 1


def mark_pipeline_failed(registry_id: int, claim_token: str, error: str) -> None:
    sql = text("""
    UPDATE tender_ingestion_registry
    SET processing_status='failed',
        last_error=LEFT(:error, 4000),
        failed_at=NOW()
    WHERE id=:registry_id AND claim_token=:claim_token
    """)
    with engine.begin() as conn:
        conn.execute(sql, {
            "registry_id": registry_id,
            "claim_token": claim_token,
            "error": error,
        })
