#!/usr/bin/env python3
"""One read-only audit for the STD tender assistant, 2026-10-21.

Run from the project root: python3 audit-tender-sources.py --probe-public
No installation, collection jobs, database writes, OCR, LLM or notifications.
Public GET probes inspect landing pages only; they do not prove export works.
The same file is streamed into running containers, never installed in app code.
"""
import argparse
import ast
import concurrent.futures
import hashlib
import ipaddress
import json
import re
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urljoin
sys.dont_write_bytecode = True

# Public entry points, not invented API routes. Closed sources remain in inventory.
# Alias matches are explicit and are reported rather than silently creating sources.
CATALOG = [
    ('sberbank_ast','Сбербанк-АСТ','federal','https://www.sberbank-ast.ru/',('sberbank_ast','sber_ast','sberbank'),'public_check','Новый маршрут; сначала открытые секции, без платной выгрузки'),
    ('tektorg','ТЭК-Торг','federal','https://www.tektorg.ru/',('tektorg',),'public_check','Проверить полноту страниц и переход к анализу'),
    ('rts_tender','РТС-тендер','federal','https://www.rts-tender.ru/',('rts_tender','rts'),'public_check','Новый маршрут; разделить 44-ФЗ и коммерческие секции'),
    ('roseltorg','Росэлторг','federal','https://www.roseltorg.ru/procedures/search',('roseltorg','eetp'),'public_check','Проверить доступ и документы; расписание не доказывает сбор'),
    ('gpb','ЭТП ГПБ','federal','https://etpgpb.ru/procedures/',('gpb',),'public_check','Контроль существующей цепочки без повторного анализа'),
    ('fabrikant','Фабрикант','federal','https://www.fabrikant.ru/',('fabrikant',),'public_check','Проверить фильтры, сроки и передачу документов'),
    ('ast_goz','АСТ ГОЗ','restricted',None,('ast_goz','astgoz'),'closed_no_probe','Закрытый доступ по указанию владельца; автоматические запросы отключены'),
    ('etprf','ЭТП РФ','restricted',None,('etprf','etp_rf'),'closed_no_probe','Закрытый доступ по указанию владельца; только аудит прежней настройки'),
    ('b2b_center','B2B-Center','commercial','https://www.b2b-center.ru/',('b2b_center','b2b'),'public_check','Поиск и карточки проверять раздельно; CAPTCHA не обходить'),
    ('tender_pro','Tender.Pro','commercial','https://www.tender.pro/',('tender_pro','tenderpro'),'public_check','Доступ главной страницы не доказывает доступ API tenderlist'),
    ('metal_it','METAL-IT','commercial','https://etp.metal-it.ru/frame/index.html',('metal_it','metalit'),'public_check','Есть опыт адаптера; проверить завершение анализа и backlog'),
    ('bidzaar','Bidzaar','commercial','https://bidzaar.com/app/requests/public/buy',('bidzaar',),'public_check','Базовый доступ бесплатен; Connector API для заказчика не считать API поиска'),
    ('acron','Акрон','commercial', 'https://etp.acron.ru/app',('acron',),'previous_challenge_no_probe','Ранее Anti-bot; без повторной серии запросов'),
    ('tatneft','Татнефть','commercial','https://etp.tatneft.ru/',('tatneft',),'public_check','Открытые объявления; отдельно проверить сессии и документы'),
    ('rosatom','БРИФ Росатом','commercial','https://zakupki.rosatom.ru/?link=brif',('rosatom','brif'),'previous_challenge_no_probe','Ранее WAF; public HTML не заменяет Atom.Form'),
    ('surgutneftegas','Сургутнефтегаз','srm','https://www.surgutneftegas.ru/procurement/',('surgutneftegas','surgut'),'public_info_only','Анонсы отдельно; SAP SRM требует учётной записи'),
    ('nornickel','Норникель','srm','https://nornickel.ru/suppliers/',('nornickel','norilsk_nickel'),'public_info_only','Публичные анонсы отдельно от SRM и кабинета исполнения договоров'),
    ('gazprom_neft','Газпром нефть','srm','https://zakupki.gazprom-neft.ru/tenderix/',('gazprom_neft','gazpromneft','gpn'),'public_info_only','Проверить дубли с ГПБ; закрытый кабинет не проверяется'),
    ('lukoil','ЛУКОЙЛ','srm','https://lukoil.ru/Company/Tendersandauctions/Tenders',('lukoil',),'public_info_only','Официально указан ИСУ Снабжение; не предполагать общий SAP API'),
    ('pik','ПИК','developer','https://etp.pik.ru/',('pik',),'public_check','Есть также tender.pik.ru; разделять материалы и СМР, сопоставлять IDs'),
    ('samolet','Самолёт','developer','https://partner.samolet.ru/tenders?limit=15&page=1',('samolet',),'public_check','Открытый список S.Tender; проверить вложения и номера лотов'),
    ('glavstroy','Главстрой','developer','https://tender.glavstroy.ru/trades',('glavstroy',),'public_check','Главстрой СПб может использовать отдельный маршрут'),
    ('akvilon','Аквилон','developer','https://etp.group-akvilon.ru/frame',('akvilon','group_akvilon'),'public_check','JS-интерфейс; схожесть с METAL-IT не доказывает совместимость API'),
    ('sminex','Sminex','developer','https://tender.sminex.com/',('sminex',),'public_check','Участие бесплатно по официальному сайту; нужна аккредитация'),
    ('level','Level Group','developer','https://etp.level.ru/frame/info.html',('level','level_group'),'public_check','JS-интерфейс; подтвердить маршрут списка закупок'),
    ('brusnika','Брусника','developer','https://srm.brusnika.ru/',('brusnika',),'public_check','SRM; публичный список и документы проверяются отдельно'),
    ('mos_suppliers','Портал поставщиков','small','https://zakupki.mos.ru/',('mos_suppliers','zakupki_mos','mos_ru'),'public_check','Малые объёмы: исключение по постоянному клиенту только вручную'),
    ('eat','ЕАТ','small','https://agregatoreat.ru/',('eat','berezka','agregatoreat'),'public_check','При CAPTCHA остановка; кабинет с ЭП не открывается'),
    ('zakupki_gov_ru','ЕИС контрольный источник','reference','https://zakupki.gov.ru/epz/main/public/home.html',('zakupki_gov_ru','eis'),'public_check','Сопоставление федеральных закупок по номеру ЕИС'),
]
MARKER = 'AUDIT_JSON:'

def emit(value):
    print(MARKER+json.dumps(value,ensure_ascii=False,default=str),flush=True)

def clean(value):
    s=str(value or '')
    s=re.sub(r'https?://[^\s\'"<>]+','[URL]',s)
    s=re.sub(r'(?i)(token|password|authorization|cookie|secret|api_key)\s*[:=]\s*[^\s,;]+',r'\1=[hidden]',s)
    return s[:400]

def val(x): return getattr(x,'value',x)

def age(x):
    if not x: return None
    try:
        dt=datetime.fromisoformat(str(x).replace('Z','+00:00'))
        if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc)-dt).total_seconds()/3600,2)
    except (ValueError,TypeError): return None

def json_file(path):
    if not path.is_file(): return {}
    if path.stat().st_size>20_000_000: raise ValueError('report_too_large')
    result=json.loads(path.read_text())
    if not isinstance(result,dict): raise ValueError('report_not_object')
    return result

def registration_keys(path, name):
    """Static inspection: never instantiate adapters or run collection methods."""
    if not path.is_file(): return []
    tree=ast.parse(path.read_text())
    keys=[]
    for node in ast.walk(tree):
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            if any(isinstance(t,ast.Name) and t.id==name for t in targets) and isinstance(node.value,ast.Dict):
                keys += [k.value for k in node.value.keys if isinstance(k,ast.Constant) and isinstance(k.value,str)]
    return sorted(set(keys))

def route_evidence(path, aliases):
    if not path.is_file(): return []
    tree=ast.parse(path.read_text()); evidence=[]
    for fn in tree.body:
        if not isinstance(fn,ast.FunctionDef) or fn.name!='collect': continue
        for node in fn.body:
            if not isinstance(node,ast.If):continue
            strings={n.value for n in ast.walk(node.test) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
            if strings.intersection(aliases):
                evidence.append({'condition':ast.unparse(node.test),'line':node.lineno})
    return evidence

def summarize_saved(data):
    if not data:return None
    out={k:data.get(k) for k in ('checked_at','recorded_at','status','pipeline_status','backlog_pending','coverage','requests','error_count','queued_count','queued','found_count') if k in data}
    out['age_hours']=age(data.get('checked_at') or data.get('recorded_at'))
    out['errors']=[{'type':e.get('error_type'),'reason':clean(e.get('reason'))} if isinstance(e,dict) else clean(e) for e in (data.get('errors') or [])[:5]]
    out['pipeline_outcomes']=dict(Counter(str(x.get('status')) for x in (data.get('pipeline') or []) if isinstance(x,dict)))
    if 'error_type' in data:out['error_type']=data['error_type']
    if 'reason' in data:out['reason']=clean(data['reason'])
    return out

def runtime(surface):
    from app.core.config import settings
    from app.workers.celery_app import celery_app
    import app
    root=Path(app.__file__).resolve().parent
    storage=Path(settings.storage_path)
    registry=registration_keys(root/'sources/registry.py','SOURCE_REGISTRY')
    primary=registration_keys(root/'marketplace_discovery/primary/collector.py','SITES')
    marketplace=[]
    try:
        from app.marketplace_discovery.registry import MARKETPLACE_REGISTRY
        marketplace=list(MARKETPLACE_REGISTRY)
    except Exception as exc:emit({'section':'registry_error','surface':surface,'type':type(exc).__name__})
    schedules=[]
    for name,cfg in celery_app.conf.beat_schedule.items():
        args=cfg.get('args') or ()
        schedules.append({'entry':name,'task':cfg.get('task'),'schedule':str(cfg.get('schedule')),
            'source_args':[x for x in args if isinstance(x,str) and re.fullmatch(r'[a-z0-9_]+',x)],
            'queue':(cfg.get('options') or {}).get('queue')})
    module_paths=('reports/dashboard_eligibility.py','reports/active_tenders.py','reports/review_dashboard.py','static/index.html','workers/celery_app.py','sources/registry.py','marketplace_discovery/primary/collector.py','workers/tasks_scoring.py','ocr/pipeline.py')
    fingerprints={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in module_paths if (root/p).is_file()}
    emit({'section':'runtime','surface':surface,'registry':registry,'primary_sites':primary,'marketplace_registry':marketplace,'schedules':schedules,'fingerprints':fingerprints,
          'note':'Configured schedule is not proof of Beat execution; registry entry is not proof of working export.'})
    if surface!='celery_discovery': return
    task_checks_left=20
    for code,name,group,url,aliases,access,note in CATALOG:
        matched=sorted(set(aliases).intersection(set(primary+registry+marketplace)))
        schedule_hits=[s for s in schedules if set(s['source_args']).intersection(aliases) or (set(aliases).intersection(marketplace) and str(s['task']).endswith('.run_connected_marketplaces'))]
        reports=[];handoffs=[]
        for a in aliases:
            for kind,path in [('primary',storage/'marketplace_primary'/(a+'.json')),('run',storage/'source_runs'/(a+'.json')),('primary_run',storage/'source_runs'/('primary_'+a+'.json'))]:
                try:
                    data=json_file(path)
                    if data:
                        reports.append({'kind':kind,'source':a,**summarize_saved(data)})
                        for item in (data.get('pipeline') or [])[-100:]:
                            if not isinstance(item,dict) or not item.get('task_id') or task_checks_left<=0:continue
                            task_id=str(item['task_id'])
                            if not re.fullmatch(r'[0-9a-fA-F-]{36}',task_id):continue
                            task_checks_left-=1
                            try:
                                # Reading metadata does not submit a task or recreate missing results.
                                meta=celery_app.backend.get_task_meta(task_id)
                                result=meta.get('result')
                                detail={k:result.get(k) for k in ('status','tender_id','documents_ok','documents_failed','positions','score','decision') if k in result} if isinstance(result,dict) else None
                                handoffs.append({'number':item.get('number'),'task_id':task_id,'state':meta.get('status'),'result':detail,
                                    'note':'PENDING can mean result expired or unknown. SUCCESS may only be an intermediate document handoff.'})
                            except Exception as exc:handoffs.append({'task_id':task_id,'error_type':type(exc).__name__})
                except Exception as exc:reports.append({'kind':kind,'error_type':type(exc).__name__})
        evidence=route_evidence(root/'marketplace_discovery/primary/collector.py',aliases)
        recent_age=[r['age_hours'] for r in reports if r.get('age_hours') is not None]
        threshold=26 if code=='zakupki_gov_ru' else 5
        row={'section':'source','source':code,'name':name,'group':group,'public_entry_point':url,'access_policy':access,
             'matched_registry_codes':matched,'adapter_in_source_registry':bool(set(aliases).intersection(registry)),
             'primary_dispatch':evidence,'schedule_entries':[s['entry'] for s in schedule_hits],
             'reports':reports,'freshness_hint':('unknown' if not recent_age else 'older_than_expected_interval' if min(recent_age)>threshold else 'recent_record_not_necessarily_success'),
             'handoff_task_results':handoffs,'next_step':note,'free_export_confirmed':None}
        row['connection_evidence']='registered_needs_runtime_result' if matched else 'not_in_known_registries'
        emit(row)
    emit({'section':'extra_sources','codes':sorted(set(primary+registry+marketplace)-{a for r in CATALOG for a in r[4]}),'note':'Keep existing sources; not disabled or reconfigured by audit.'})
    # Celery inspection is remote-control read only. Arguments and credentials are omitted.
    for method in ('active','reserved','scheduled'):
        try:
            result=getattr(celery_app.control.inspect(timeout=3),method)()
            compact={}
            for worker,entries in (result or {}).items():
                compact[worker]=[{'id':(x.get('request') or x).get('id'),'name':(x.get('request') or x).get('name')} for x in entries]
            emit({'section':'workers','kind':method,'responded':result is not None,'workers':compact,'note':'Does not inspect waiting broker messages. Empty reply is not proof that the queue is empty.'})
        except Exception as exc:emit({'section':'workers','kind':method,'error_type':type(exc).__name__})
    database_audit()

def database_audit():
    from app.db.session import SyncSessionLocal
    from app.models.database import Tender,Document
    from sqlalchemy import select,func,text
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    aliases={a for row in CATALOG for a in row[4]}
    with SyncSessionLocal() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        db.execute(text("SET LOCAL statement_timeout = '15000ms'"))
        current=(Tender.is_active.is_(True),Tender.submission_deadline>now)
        rows=db.execute(select(Tender.source,Tender.processing_status,Tender.status,Tender.analysis_done,func.count()).where(*current).group_by(Tender.source,Tender.processing_status,Tender.status,Tender.analysis_done)).all()
        emit({'section':'db_current_counts','rows':[{'source':s,'processing':val(p),'decision':val(d),'analysis_done':done,'count':n} for s,p,d,done,n in rows], 'note':'Only active records with future known deadlines; counts do not prove relevance.'})
        emit({'section':'db_unknown_deadlines','rows':[{'source':s,'count':n} for s,n in db.execute(select(Tender.source,func.count()).where(Tender.is_active.is_(True),Tender.submission_deadline.is_(None)).group_by(Tender.source)).all()]})
        for source in sorted(aliases):
            tenders=db.execute(select(Tender).where(Tender.source==source,*current).order_by(Tender.updated_at.desc()).limit(2)).scalars().all()
            for t in tenders:
                docs=db.execute(select(Document.ocr_status,func.count(),func.sum(func.length(Document.extracted_text))).where(Document.tender_id==t.id).group_by(Document.ocr_status)).all()
                emit({'section':'db_recent','source':source,'external_id':t.external_id,'id':str(t.id),'title':t.title[:250],
                    'updated_at':t.updated_at,'age_hours':age(t.updated_at),'processing':val(t.processing_status),'decision':val(t.status),'analysis_done':t.analysis_done,'score':t.score,
                    'documents':[{'ocr_status':val(s),'count':n,'text_characters':length or 0} for s,n,length in docs]})
        # Oldest unfinished current tenders are reported as candidates, not automatically retried.
        waiting=db.execute(select(Tender).where(*current,Tender.analysis_done.is_(False)).order_by(Tender.updated_at.asc()).limit(15)).scalars().all()
        emit({'section':'oldest_unfinished_current','rows':[{'source':t.source,'external_id':t.external_id,'processing':val(t.processing_status),'age_hours':age(t.updated_at)} for t in waiting], 'note':'No diagnosis of stuck task without task/worker evidence; no requeue.'})
        db.rollback()

def dashboard_audit():
    from app.reports.active_tenders import get_tender_dashboard
    from app.reports.review_dashboard import get_review_dashboard
    from app.reports.dashboard_eligibility import evaluate_dashboard_tender
    import inspect
    import app
    root=Path(app.__file__).resolve().parent
    rows=get_tender_dashboard()
    review=get_review_dashboard()
    keys=lambda rr:{(x.get('source'),str(x.get('external_id'))) for x in rr}
    html=(root/'static/index.html').read_text()
    emit({'section':'dashboard','suitable_counts':dict(Counter(r.get('source') for r in rows)),
        'review_counts':dict(Counter(r.get('source') for r in review['tenders'])),
        'duplicate_cards_between_blocks':len(keys(rows)&keys(review['tenders'])),
        'frontend_keeps_manual_review':'allTenders = main.tenders;' in html,
        'backend_separates_relevance_from_participation':"'manual_review'" in inspect.getsource(evaluate_dashboard_tender),
        'control_gpb_2077557':[{k:r.get(k) for k in ('external_id','status','score','analysis_done','matched_count','weight_status')} for r in rows if r.get('source')=='gpb' and str(r.get('external_id'))=='2077557'],
        'note':'Report functions may log errors and return empty lists; retain ERROR lines above, do not interpret empty lists as proof of zero eligible tenders.'})

def classify_page(status,ctype,body):
    text=body.decode('utf-8',errors='replace')
    # Visible text avoids a false CAPTCHA alarm from an unloaded captcha JS library.
    visible=re.sub(r'<(script|style)\b[^>]*>.*?</\1>',' ',text,flags=re.I|re.S)
    visible=re.sub(r'<[^>]+>',' ',visible)
    visible=' '.join(visible.split())
    if status in (401,403,429): return 'access_restricted'
    if status>=400:return 'http_error'
    if not body:return 'empty_response'
    if re.search(r'anti.bot verification|access denied|are you sure you.re not a robot|подтвердите.{0,30}не робот|доступ запрещен|техническая поддержка.{0,100}UUID',visible,re.I):return 'access_challenge'
    if re.search(r'type\s*=\s*[\'"]password',text,re.I):return 'login_form_present'
    if re.search(r'не поддерживается|enable javascript|without javascript',visible,re.I):return 'javascript_required_or_compatibility_notice'
    if 'json' in ctype:return 'json_landing_response_not_validated_export'
    if 'html' in ctype:return 'public_html_not_validated_export'
    return 'non_html_response'

def probe_one(row):
    """One public HTTPS request, no redirects/auth/documents. Isolated hard timeout in parent."""
    import urllib.request
    import urllib.error
    import ssl
    code,name,group,url,aliases,policy,note=row
    if policy not in ('public_check','public_info_only') or not url:
        return {'source':code,'probe':'skipped','reason':policy}
    p=urlsplit(url)
    if p.scheme!='https' or p.username or p.password:raise ValueError('unsafe_probe_url')
    addresses=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):raise ValueError('non_public_address')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    req=urllib.request.Request(url,headers={'User-Agent':'STD-Tender-Audit/1.0 (read-only public availability check)','Accept':'text/html,application/json;q=0.8','Accept-Encoding':'identity'})
    try:
        response=opener.open(req,timeout=12)
    except urllib.error.HTTPError as exc:
        response=exc
    with response:
        status=response.code;ctype=response.headers.get('Content-Type','')
        if 300<=status<400:
            target=urlsplit(urljoin(url,response.headers.get('Location','')))
            return {'source':code,'http':status,'probe':'redirect_not_followed','destination_host':target.hostname,'destination_path':target.path[:180]}
        body=response.read(768*1024) if ('html' in ctype or 'json' in ctype or ctype.startswith('text/')) else b''
        result={'source':code,'http':status,'content_type':ctype[:100],'sample_bytes':len(body),'sample_limited':len(body)==768*1024,'probe':classify_page(status,ctype,body),'export_verified':False}
        # No extraction of documents, sessions, cookies or embedded tokens.
        return result

def run_probes():
    script=Path(sys.argv[0]).read_text() if sys.argv[0]!='-' else None
    # Inside stdin child receives its source from this global, injected by the host.
    script=script or globals().get('STREAMED_SOURCE')
    def run(row):
        if row[5] not in ('public_check','public_info_only') or not row[3]:return {'source':row[0],'probe':'skipped','reason':row[5]}
        try:
            result=subprocess.run([sys.executable,'-','--probe-one',row[0]],input=script,text=True,capture_output=True,timeout=22)
            parsed=[json.loads(line[len(MARKER):]) for line in result.stdout.splitlines() if line.startswith(MARKER)]
            return parsed[-1] if parsed else {'source':row[0],'probe':'child_failed','returncode':result.returncode}
        except subprocess.TimeoutExpired:return {'source':row[0],'probe':'timeout'}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(run,CATALOG):emit({'section':'public_probe',**result})

def inside(surface,probes):
    try:
        if surface=='public_probes':run_probes()
        elif surface=='app':
            runtime(surface);dashboard_audit()
        else:runtime(surface)
    except Exception as exc:
        emit({'section':'audit_error','surface':surface,'type':type(exc).__name__,'reason':clean(exc)})
        return 2
    return 0

def host(probes):
    script=Path(__file__).resolve().read_text()
    print('AUDIT_BEGIN: read-only runtime evidence; no installation or business jobs',flush=True)
    emit({'section':'scope','checked_at':datetime.now(timezone.utc).isoformat(),'sources':len(CATALOG),'public_probe':probes,
          'limitations':'No paid APIs, login, closed sources, document downloads, OCR or LLM calls. Public page availability is not collection success. A new adapter is not installed by this audit.'})
    services=subprocess.run(['docker','compose','ps','--services','--status','running'],capture_output=True,text=True,timeout=20)
    if services.returncode:raise SystemExit('DOCKER_COMPOSE_UNAVAILABLE: run from the project root')
    running=set(services.stdout.split())
    records=[]; failures=[]
    for surface in ('celery_discovery','celery_beat','celery_worker','app','public_probes'):
        if surface=='public_probes' and not probes:continue
        service='celery_discovery' if surface=='public_probes' else surface
        if service not in running:
            emit({'section':'service_missing','service':service});failures.append(surface);continue
        print('\nCHECK:',surface,flush=True)
        payload='STREAMED_SOURCE = '+repr(script)+'\n'+script
        try:
            result=subprocess.run(['docker','compose','exec','-T',service,'python','-','--inside',surface],input=payload,text=True,capture_output=True,timeout=240)
            for line in result.stdout.splitlines():
                if line.startswith(MARKER):
                    try:
                        row=json.loads(line[len(MARKER):]); records.append(row)
                        print(json.dumps(row,ensure_ascii=False),flush=True)
                    except ValueError:print('UNPARSED_AUDIT_OUTPUT',flush=True)
                elif re.search(r'error|failed|traceback',line,re.I):print('APP_LOG:',clean(line),flush=True)
            if result.returncode:
                failures.append(surface)
                emit({'section':'surface_failed','surface':surface,'returncode':result.returncode,'stderr':clean(result.stderr)})
        except subprocess.TimeoutExpired as exc:
            partial=exc.stdout or ''
            if isinstance(partial,bytes):partial=partial.decode('utf-8',errors='replace')
            for line in partial.splitlines():
                if line.startswith(MARKER):
                    try:
                        row=json.loads(line[len(MARKER):]);records.append(row)
                        print(json.dumps(row,ensure_ascii=False),flush=True)
                    except ValueError:pass
            failures.append(surface);emit({'section':'surface_timeout','surface':surface,'result':'incomplete'})
    runtimes=[r for r in records if r.get('section')=='runtime']
    allpaths={p for r in runtimes for p in r.get('fingerprints',{})}
    differences={p:{r['surface']:r.get('fingerprints',{}).get(p) for r in runtimes} for p in allpaths if len({r.get('fingerprints',{}).get(p) for r in runtimes})>1}
    emit({'section':'container_version_differences','files':differences,'note':'App-only dashboard update may explain report/UI differences; task/scoring differences require investigation, not automatic restart.'})
    probes_by_source={r['source']:r for r in records if r.get('section')=='public_probe'}
    print('\nСВОДКА ПО ПЛОЩАДКАМ:',flush=True)
    for r in records:
        if r.get('section')!='source':continue
        probe=probes_by_source.get(r['source'],{}).get('probe','not_requested_or_missing')
        print(r['name']+' | '+r['connection_evidence']+' | расписаний: '+str(len(r['schedule_entries']))+' | '+r['freshness_hint']+' | HTTP: '+probe,flush=True)
    emit({'section':'finish','failed_surfaces':failures,'server_audit_complete':not failures,
        'business_changes':False,'note':'No schedule edits, registrations, queues purged, new tasks, downloads, OCR, LLM, notifications or DB writes. No file report is required: copy terminal output.'})
    return 2 if failures else 0

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-public',action='store_true',help='bounded public landing-page GET checks from discovery container')
    parser.add_argument('--inside',choices=['app','celery_discovery','celery_beat','celery_worker','public_probes'],help=argparse.SUPPRESS)
    parser.add_argument('--probe-one',help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.probe_one:
        row=next(r for r in CATALOG if r[0]==args.probe_one)
        try:emit(probe_one(row))
        except Exception as exc:emit({'source':row[0],'probe':'error','error_type':type(exc).__name__,'reason':clean(exc)})
        return 0
    if args.inside:return inside(args.inside,False)
    return host(args.probe_public)

if __name__=='__main__':sys.exit(main())
