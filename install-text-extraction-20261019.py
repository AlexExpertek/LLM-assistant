#!/usr/bin/env python3
"""Plain text extraction and optional one-tender GPB recovery."""
FUNCTION = 'def _extract_plain_text_v20261019(file_path):\n    """Strict decoding, bounded read, no OCR and no lossy replacement."""\n    path = Path(file_path)\n    with path.open(\'rb\') as stream:\n        data = stream.read(10 * 1024 * 1024 + 1)\n    if len(data) > 10 * 1024 * 1024:\n        raise ValueError(\'TEXT_FILE_SIZE_LIMIT\')\n    if data.startswith((b\'\\xff\\xfe\', b\'\\xfe\\xff\')):\n        text = data.decode(\'utf-16\')\n    else:\n        text = data.decode(\'utf-8-sig\')\n    if not text.strip():\n        raise ValueError(\'TEXT_FILE_EMPTY\')\n    if any(ord(ch) < 32 and ch not in \'\\n\\r\\t\\f\' for ch in text):\n        raise ValueError(\'TEXT_FILE_BINARY_CONTENT\')\n    return ExtractionResult(\n        full_text=text,\n        pages=[PageExtraction(page_number=1, text=text, confidence=100.0, is_scanned=False)],\n        status=OCRStatus.NOT_REQUIRED,\n        pages_count=1,\n    )\n'
TESTS = 'from pathlib import Path\nfrom tempfile import TemporaryDirectory\nfrom app.ocr.pipeline import extract_document, OCRStatus\nwith TemporaryDirectory() as tmp:\n    for name, data, expected in [\n        (\'positions.txt\', \'{"positions": [{"name": "Профиль АД31"}]}\'.encode(), \'{"positions": [{"name": "Профиль АД31"}]}\'),\n        (\'note.md\', \'Текст\\nтаблица\'.encode(\'utf-8-sig\'), \'Текст\\nтаблица\'),\n        (\'wide.TXT\', \'Труба АМг2\'.encode(\'utf-16\'), \'Труба АМг2\'),\n    ]:\n        p=Path(tmp)/name;p.write_bytes(data);r=extract_document(str(p))\n        assert r.full_text == expected and r.status == OCRStatus.NOT_REQUIRED\n        assert r.pages_count == 1 and not r.pages[0].is_scanned\n    for data in [b\'\', b\' \\n\', b\'PK\\x00\\x03\', b\'\\xffwrong\', b\'x\'*(10*1024*1024+1)]:\n        p=Path(tmp)/\'bad.txt\';p.write_bytes(data)\n        try:extract_document(str(p))\n        except (ValueError,UnicodeError):pass\n        else:raise AssertionError(\'Invalid input accepted\')\nprint(\'PLAIN_TEXT_EXTRACTION_TESTS_OK\')\n'
RESUME = "import json, shutil, tempfile, hashlib\nfrom pathlib import Path\nfrom sqlalchemy import select\nfrom app.core.config import settings\nfrom app.db.session import SyncSessionLocal\nfrom app.models.database import Tender, Document, ProcessingStatus\nfrom app.sources.eis_freshness import gate_saved_tender\nfrom app.workers.completed_analysis import has_completed_analysis\nfrom app.workers.tasks_ocr import process_tender_documents\nfrom app.workers.celery_app import celery_app\nfrom app.sources.schemas import SourceDocument\nfrom app.ocr.pipeline import extract_document\nTID='2742c177-b7d7-4e4e-996a-15ab3ea07ca6'\nwith SyncSessionLocal() as db:\n    tender=db.get(Tender,TID)\n    if not tender or tender.source != 'gpb' or str(tender.external_id) != '2077557':\n        raise SystemExit('RESUME_IDENTITY_MISMATCH')\n    if has_completed_analysis(db,tender):\n        print('RESUME_SKIPPED_ALREADY_ANALYZED');raise SystemExit(0)\n    blocked=gate_saved_tender(db,TID)\n    if blocked:\n        print('RESUME_SKIPPED:',json.dumps(blocked,ensure_ascii=False,default=str));raise SystemExit(0)\n    if tender.processing_status != ProcessingStatus.FAILED:\n        print('RESUME_SKIPPED_NOT_FAILED');raise SystemExit(0)\n    rows=db.execute(select(Document).where(Document.tender_id==TID)).scalars().all()\n    failures=[d for d in rows if str(getattr(d.ocr_status,'value',d.ocr_status))=='failed']\n    if len(rows)!=4 or len(failures)!=1 or failures[0].filename!='00_Позиции_ГПБ.txt':\n        raise SystemExit('RESUME_SNAPSHOT_CHANGED; no task submitted')\n    base=Path(settings.storage_path)/'tenders'/TID\n    files=[]\n    for row in rows:\n        name=row.filename\n        if not name or Path(name).name!=name:raise SystemExit('RESUME_UNSAFE_FILENAME')\n        p=base/name\n        if not p.is_file():raise SystemExit('RESUME_FILE_MISSING: '+name)\n        files.append(p)\n    result=extract_document(str(base/'00_Позиции_ГПБ.txt'))\n    payload=json.loads(result.full_text)\n    if not isinstance(payload,dict) or not isinstance(payload.get('positions'),list) or not payload['positions']:\n        raise SystemExit('RESUME_POSITIONS_MISSING')\n    print('SAVED_GPB_POSITIONS_OK; TEXT_CHARACTERS:',len(result.full_text),flush=True)\n# A dedicated reservation avoids repeating this one-off recovery on installer reruns.\nclient=celery_app.backend.client\nkey='recovery:txt20261019:'+TID\nif not client.set(key,'reserved',nx=True,ex=86400):\n    print('RESUME_ALREADY_RESERVED; no duplicate task');raise SystemExit(0)\npublished=False\ntry:\n    root=Path(settings.storage_path)/'txt_recovery_prepared';root.mkdir(parents=True,exist_ok=True)\n    folder=Path(tempfile.mkdtemp(prefix=TID+'-',dir=root))\n    docs=[]\n    for p in files:\n        target=folder/p.name;shutil.copy2(p,target)\n        docs.append(SourceDocument(name=p.name,download_type='local_file',local_path=str(target)).model_dump(mode='json'))\n    published=True\n    task=process_tender_documents.delay(TID,docs)\n    client.set(key,task.id,xx=True,ex=86400)\n    print('GPB_RECOVERY_QUEUED:',task.id,flush=True)\n    print('One tender only; saved files, normal eligibility/OCR/LLM gates; GPB notifications suppressed.')\nexcept Exception:\n    if not published:client.delete(key)\n    raise\n"
BRANCH = "    if Path(file_path).suffix.lower() in {'.txt', '.md'}:\n        return _extract_plain_text_v20261019(file_path)\n"
import ast, argparse, os, shutil, subprocess, tempfile
from pathlib import Path

def transform(text):
    if 'def _extract_plain_text_v20261019(' in text:
        if FUNCTION.strip() not in text or BRANCH.strip() not in text:
            raise SystemExit('PLAIN_TEXT_VERSION_CONFLICT')
        return text
    tree=ast.parse(text)
    node=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='extract_document'),None)
    if node is None:raise SystemExit('EXTRACT_DOCUMENT_NOT_FOUND')
    source=ast.get_source_segment(text,node)
    if any(isinstance(n,ast.Constant) and n.value in ('.txt','.md') for n in ast.walk(node)):
        raise SystemExit('TEXT_HANDLER_ALREADY_EXISTS; inspect current implementation')
    if 'handlers' not in source or 'suffix' not in source:
        raise SystemExit('EXTRACT_DOCUMENT_VERSION_CONFLICT')
    start=node.body[0]
    if isinstance(start,ast.Expr) and isinstance(start.value,ast.Constant) and isinstance(start.value.value,str):
        line=start.end_lineno
    else:line=node.lineno
    lines=text.splitlines(keepends=True);lines.insert(line,BRANCH)
    result=''.join(lines)+'\n\n'+FUNCTION
    compile(result,'pipeline.py','exec');return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--resume-gpb',action='store_true',help='Resume only GPB 2077557 from saved files after checks')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    p=Path('app/ocr/pipeline.py')
    if not p.is_file():raise SystemExit('Run from tender-ai-platform-v6.2 root')
    old=p.read_text();new=transform(old)
    print('PLAIN_TEXT_COMPATIBLE',flush=True)
    if args.check:return
    if new!=old:
        backup=Path(tempfile.mkdtemp(prefix='txt-handler-backup-',dir=Path.cwd().parent))/'pipeline.py'
        shutil.copy2(p,backup);print('BACKUP:',backup,flush=True)
        fd,tmp=tempfile.mkstemp(dir=p.parent)
        with os.fdopen(fd,'w') as f:f.write(new)
        os.chmod(tmp,p.stat().st_mode & 0o777);os.replace(tmp,p)
    subprocess.run(['docker','compose','build','app','celery_worker','celery_discovery'],check=True)
    subprocess.run(['docker','compose','run','--rm','--no-deps','-T','celery_discovery','python','-'],input=TESTS,text=True,check=True)
    ids=subprocess.check_output(['docker','compose','ps','-q','celery_worker','celery_discovery'],text=True).split()
    if ids:
        print('Waiting for running tasks to finish (warm shutdown).',flush=True)
        subprocess.run(['docker','kill','--signal=SIGTERM',*ids],check=True)
        subprocess.run(['docker','wait',*ids],check=True)
    subprocess.run(['docker','compose','up','-d','--no-deps','app','celery_worker','celery_discovery'],check=True)
    print('PLAIN_TEXT_EXTRACTION_INSTALLED',flush=True)
    if args.resume_gpb:
        subprocess.run(['docker','compose','exec','-T','celery_discovery','python','-'],input=RESUME,text=True,check=True)
    print('Existing schedules and completed analyses retained.',flush=True)

if __name__=='__main__':main()
