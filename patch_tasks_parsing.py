from pathlib import Path

path = Path("app/workers/tasks_parsing.py")
text = path.read_text(encoding="utf-8")

old = '''    tender_hash = compute_tender_hash(
        source=tender_data["source"],
        external_id=tender_data["external_id"],
        customer_name=tender_data.get("customer_name", ""),
        title=tender_data.get("title", ""),
    )

    # TODO: проверка дубликата по hash в БД перед сохранением (FR-SRC-005)
    logger.info("processing_new_tender", external_id=tender_data["external_id"], hash=tender_hash)

    # Следующий шаг цепочки — скачивание документов
    from app.workers.tasks_ocr import download_and_process_documents
    download_and_process_documents.delay(tender_data["external_id"], tender_data.get("document_urls", []))

    return {"status": "queued_for_documents", "hash": tender_hash}'''

new = '''    from app.services.tender_dedup import (
        mark_pipeline_failed,
        mark_pipeline_queued,
        register_and_claim_tender,
    )

    dedup = register_and_claim_tender(tender_data)

    logger.info(
        "tender_deduplication_checked",
        source=tender_data["source"],
        external_id=tender_data["external_id"],
        action=dedup.action,
        claimed=dedup.claimed,
        revision=dedup.revision,
        identity_hash=dedup.identity_hash,
        content_hash=dedup.content_hash,
    )

    if not dedup.claimed:
        return {
            "status": "skipped",
            "reason": "duplicate_unchanged_or_already_queued",
            "action": dedup.action,
            "revision": dedup.revision,
            "identity_hash": dedup.identity_hash,
            "content_hash": dedup.content_hash,
        }

    try:
        from app.workers.tasks_ocr import download_and_process_documents

        downstream = download_and_process_documents.delay(
            tender_data["external_id"],
            tender_data.get("document_urls", []),
        )

        if not mark_pipeline_queued(
            dedup.registry_id,
            dedup.claim_token,
            downstream.id,
        ):
            raise RuntimeError("Не удалось зафиксировать queued")

    except Exception as exc:
        mark_pipeline_failed(dedup.registry_id, dedup.claim_token, str(exc))
        logger.exception(
            "tender_pipeline_queue_failed",
            source=tender_data["source"],
            external_id=tender_data["external_id"],
            error=str(exc),
        )
        raise self.retry(exc=exc)

    return {
        "status": "queued_for_documents",
        "action": dedup.action,
        "revision": dedup.revision,
        "identity_hash": dedup.identity_hash,
        "content_hash": dedup.content_hash,
        "downstream_task_id": downstream.id,
    }'''

if old not in text:
    raise SystemExit("Целевой TODO-блок не найден; файл не изменён")

path.write_text(text.replace(old, new), encoding="utf-8")
print("patched:", path)
