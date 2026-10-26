#!/usr/bin/env python3
"""Public-source evidence audit. No installation, business tasks, DB writes or LLM.
Run from project root: python3 audit-tender-sources.py
Offline test: python3 audit-tender-sources.py --self-test
Results: one ZIP + report.json + SUMMARY.txt in a new audit directory.
Only Python 3.11 standard library is required. Public source snapshots are data,
never executed. This script deliberately does NOT claim that HTTP 200 proves an
adapter, keyword search, procurement identity, eligibility or LLM handoff works.
"""
import argparse, ast, hashlib, html, io, ipaddress, json, os, re, socket, ssl
import subprocess, sys, tempfile, time, unittest, urllib.request, urllib.error
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urlencode, quote, parse_qsl

VERSION='sources-evidence-audit-20261026-1'
KEYWORDS=('алюминий','алюминиевый лист','алюминиевый профиль','алюминиевая лента','алюминиевая фольга')
# Public official URLs verified from official pages/search on 2026-10-26.
# These are evidence seeds, not invented search API contracts.
NEW={
 'sberbank_ast':('Сбербанк-АСТ','https://www.sberbank-ast.ru/UnitedPurchaseList.html'),
 'rts_tender':('РТС-тендер','https://www.rts-tender.ru/'),
 'tatneft':('Татнефть','https://etp.tatneft.ru/'),
 'surgutneftegas':('Сургутнефтегаз','https://www.surgutneftegas.ru/procurement/'),
 'nornickel':('Норникель','https://nornickel.ru/suppliers/become-supplier/'),
 'gazprom_neft':('Газпром нефть','https://zakupki.gazprom-neft.ru/tenderix/'),
 'lukoil':('ЛУКОЙЛ','https://www.lukoil.com/Company/Tendersandauctions/Tenders'),
 'pik':('ПИК','https://etp.pik.ru/trades'),
 'akvilon':('Группа Аквилон','https://etp.group-akvilon.ru/'),
 'sminex':('Sminex','https://tender.sminex.com/trades'),
 'level':('Level Group','https://etp.level.ru/frame/index.html'),
 'brusnika':('Брусника','https://surgut.brusnika.ru/tender/'),
 'supplier_portal':('Портал поставщиков','https://zakupki.mos.ru/'),
 'eat':('ЕАТ','https://agregatoreat.ru/'),
}
EXISTING=('gpb','tektorg','fabrikant','metal_it','glavstroy','samolet','bidzaar','roseltorg','zakupki_gov_ru')
HELD={'tender_pro':'paused_by_user; previous TCP timeout',
      'b2b_center':'previous_captcha; no automatic access retry',
      'rosatom':'previous_WAF; no automatic access retry',
      'acron':'previous_anti_bot; no automatic access retry',
      'ast_goz':'closed_access_excluded','etprf':'disabled_closed_access'}
SBER_CARD='https://utp.sberbank-ast.ru/Transneft/NBT/PurchaseView/8/0/0/4264478'
SBER_SCRIPTS=('/CoreApl/core.js','/CoreApl/core_ext.js','/js/apl/aplFormScript.js')
SECRET=re.compile(r'token|password|passwd|secret|authorization|cookie|session|csrf|api.?key',re.I)
CHALLENGE=re.compile(r'verify you are human|anti.bot verification|проверка.{0,20}робот|подтвердите.{0,30}человек|access denied|checking your browser',re.I)
CARDPATH=re.compile(r'/(?:trades|tenders?|procedures?|purchases?)/[^?#]*\d|PurchaseView/|view\.php\?ID=|tender-\d',re.I)
TARGET=re.compile(r'алюм|\bАМ[гц]\d*|\bАД(?:0|1|31)\b',re.I)
LINKWORDS=re.compile(r'тендер|закуп|поставщик|торги|procurement|tender|purchase|supplier',re.I)
DOCUMENT=re.compile(r'\.(?:pdf|docx?|xlsx?|zip|rar|7z|tiff?)(?:\?|$)|DocumentView|/files?/|imported-file',re.I)

class Stop(Exception): pass

def public_url(url):
 p=urlsplit(url)
 if p.username or p.password:return '[credentials-in-url]'
 return p._replace(query=urlencode([(k,v) for k,v in parse_qsl(p.query) if not SECRET.search(k)]),fragment='').geturl()

def safe_url(url,hosts):
 try:
  p=urlsplit(url)
  return (p.scheme=='https' and p.hostname in hosts and not p.username and not p.password
    and p.port in (None,443) and not p.fragment
    and not any(SECRET.search(k) for k,v in parse_qsl(p.query))
    and not re.search(r'/(?:login|logout|auth|captcha|register)(?:/|\.|$)',p.path,re.I))
 except ValueError:return False

def scrub(text):
 # Public sources only; never save response headers or cookies.
 text=re.sub(r'(?is)<input\b(?=[^>]*\btype=["\']?hidden\b)[^>]*>', '<!-- hidden input omitted -->',text)
 text=re.sub(r'(?i)((?:[\w]*token|password|secret|authorization|cookie|api_key)\s*["\']?\s*[:=]\s*)["\'][^"\']*["\']',r'\1"[redacted]"',text)
 return text

class Page(HTMLParser):
 def __init__(self,base):
  super().__init__(convert_charrefs=True);self.base=base;self.links=[];self.scripts=[];self.forms=[]
  self.text=[];self.title=[];self.skip=0;self.intitle=False;self.a=None;self.form=None;self.password=False
 def handle_starttag(self,tag,attrs):
  d=dict(attrs)
  if tag in ('script','style'):self.skip+=1
  if tag=='script' and d.get('src'):self.scripts.append(urljoin(self.base,d['src']))
  if tag=='title':self.intitle=True
  if tag=='a':self.a=[urljoin(self.base,d.get('href','')),'']
  if tag=='form':self.form={'action':urljoin(self.base,d.get('action') or self.base),'method':d.get('method','get').lower(),'fields':[],'password':False}
  if tag=='input':
   if d.get('type','').lower()=='password':
    self.password=True
    if self.form:self.form['password']=True
   if self.form and d.get('name'):self.form['fields'].append({'name':d['name'],'type':d.get('type','text').lower()})
 def handle_endtag(self,tag):
  if tag in ('script','style'):self.skip=max(0,self.skip-1)
  if tag=='title':self.intitle=False
  if tag=='a' and self.a:self.links.append(self.a);self.a=None
  if tag=='form' and self.form:self.forms.append(self.form);self.form=None
 def handle_data(self,data):
  if not self.skip:
   self.text.append(data)
   if self.a:self.a[1]+=data
   if self.intitle:self.title.append(data)
 def summary(self):
  title=' '.join(self.title).strip();visible=' '.join(self.text)
  challenge=bool(CHALLENGE.search(title+' '+visible[:16000]))
  return {'title':title,'visible_characters':len(visible),'access_challenge':challenge,'login_form_present':self.password,
   'keyword_mentions_in_page':sorted(set(m.group(0) for m in TARGET.finditer(visible)))[:20],
   'forms':self.forms,'scripts':self.scripts,
   'procurement_links':[{'url':u,'label':t.strip()[:250]} for u,t in self.links if LINKWORDS.search(t+' '+u)][:60],
   'candidate_links':[{'url':u,'title':t.strip()[:250],'eligibility':'unverified'} for u,t in self.links if CARDPATH.search(u) and TARGET.search(t)][:12],
   'document_links':[{'url':u,'label':t.strip()[:200],'identity_verified':False} for u,t in self.links if DOCUMENT.search(u)][:30]}

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

class Reader:
 def __init__(self,directory):
  self.directory=directory;self.requests=0;self.total=0;self.started=time.monotonic();self.evidence=[]
  self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
 def get(self,url,hosts,source,limit=3_000_000,_hops=0):
  if not safe_url(url,hosts):raise Stop('unapproved_or_interactive_url')
  if self.requests>=80 or self.total>=40_000_000 or time.monotonic()-self.started>600:raise Stop('global_budget_exhausted')
  # Refuse local/private destinations even if DNS changes unexpectedly.
  for addr in socket.getaddrinfo(urlsplit(url).hostname,443,type=socket.SOCK_STREAM):
   if not ipaddress.ip_address(addr[4][0]).is_global:raise Stop('non_public_dns')
  self.requests+=1;start=time.monotonic()
  req=urllib.request.Request(url,headers={'User-Agent':'TenderAssistant-Audit/1.0','Accept-Encoding':'identity'})
  try:r=self.opener.open(req,timeout=8)
  except urllib.error.HTTPError as exc:
   if 300<=exc.code<400:
    target=urljoin(url,exc.headers.get('Location',''))
    if _hops>=2 or not safe_url(target,hosts):raise Stop('redirect_requires_review:'+public_url(target))
    return self.get(target,hosts,source,limit,_hops+1)
   raise Stop('http_'+str(exc.code)) from None
  with r:
   body=bytearray()
   while True:
    chunk=r.read(65536)
    if not chunk:break
    self.total+=len(chunk);body.extend(chunk)
    if len(body)>limit or self.total>40_000_000:raise Stop('body_limit_incomplete')
    if time.monotonic()-start>25:raise Stop('body_timeout_incomplete')
   if not body:raise Stop('empty_response')
   if r.headers.get('Content-Encoding','identity').lower() not in ('','identity'):raise Stop('unexpected_content_encoding')
   ctype=r.headers.get('Content-Type','')
   if not any(k in ctype.lower() for k in ('html','javascript','json','text/')):raise Stop('unexpected_non_text_response')
   encoding=r.headers.get_content_charset() or 'utf-8'
   try:text=body.decode(encoding)
   except (UnicodeError,LookupError):
    try:text=body.decode('cp1251')
    except UnicodeError:raise Stop('unknown_encoding')
  content=scrub(text);name=source+'-'+str(self.requests)+('.js' if 'javascript' in ctype or urlsplit(url).path.endswith('.js') else '.html')
  (self.directory/name).write_text(content,encoding='utf-8')
  row={'url':public_url(url),'http':200,'bytes':len(body),'content_type':ctype,
       'response_sha256':hashlib.sha256(body).hexdigest(),'evidence_file':name,
       'saved_sha256':hashlib.sha256(content.encode()).hexdigest(),'sanitized':True,'complete':True}
  self.evidence.append(row);return text,row

def search_form(page,hosts):
 for f in page.forms:
  if f['method']!='get' or f['password'] or not safe_url(f['action'],hosts):continue
  if not re.search(r'search|tender|trade|purchase|procedure',urlsplit(f['action']).path,re.I):continue
  field=next((x['name'] for x in f['fields'] if x['type'] in ('text','search') and x['name'].lower() in ('q','query','search','keyword','query_field')),None)
  if field:
   p=urlsplit(f['action']);params=dict(parse_qsl(p.query));params[field]=KEYWORDS[0]
   return p._replace(query=urlencode(params)).geturl()
 return None

def scripts_for(page,sber=False):
 if sber:
  return [next((u for u in page.scripts if urlsplit(u).path==p),None) for p in SBER_SCRIPTS]
 # Save complete application bundles; third-party chat/analytics are excluded.
 urls=[u for u in page.scripts if re.search(r'\.js(?:\?|$)',u) and not re.search(r'jquery|analytics|metrika|chat|polyfills|runtime|bootstrap|captcha',u,re.I)]
 return sorted(dict.fromkeys(urls),key=lambda u:not bool(re.search(r'main|app|bundle|core',urlsplit(u).path,re.I)))[:2]

def probe(source,reader):
 name,url=NEW[source];host=urlsplit(url).hostname;hosts={host}
 if host.startswith('www.'):hosts.add(host[4:])
 if source=='sberbank_ast':hosts|={'utp.sberbank-ast.ru','www.sberbank-ast.ru','sberbank-ast.ru'}
 row={'source':source,'name':name,'url':url,'status':'not_checked','network_environment':'server_host',
      'stages':{'public_page':False,'keyword_search':'not_verified','native_card_identity':'not_verified','document_download':'not_tested','ocr':'not_run','llm':'not_run','dashboard':'not_verified'},
      'pipeline_ready':False,'errors':[],'pages':[],'requests':0}
 before=reader.requests
 try:
  text,evidence=reader.get(url,hosts,source);page=Page(evidence.get('url',url));page.feed(text);info=page.summary();row['pages'].append({**evidence,**info});row['stages']['public_page']=True
  if info['access_challenge']:raise Stop('access_challenge_stop')
  # A login field alongside public content does not prove the whole portal is closed.
  search=search_form(page,hosts)
  if search:
   text,ev=reader.get(search,hosts,source);page=Page(ev.get('url',search));page.feed(text);info=page.summary();row['pages'].append({**ev,**info})
   row['stages']['keyword_search']='observed_GET_form_submitted_results_unverified'
   if info['access_challenge']:raise Stop('access_challenge_stop')
  if source=='sberbank_ast':
   text,ev=reader.get(SBER_CARD,hosts,source);page=Page(SBER_CARD);page.feed(text);info=page.summary();row['pages'].append({**ev,**info,'historical_diagnostic_card':True})
   if info['access_challenge']:raise Stop('access_challenge_stop')
  elif info['candidate_links']:
   target=next((x['url'] for x in info['candidate_links'] if safe_url(x['url'],hosts)),None)
   if target:
    text,ev=reader.get(target,hosts,source);page=Page(ev.get('url',target));page.feed(text);info=page.summary();row['pages'].append({**ev,**info})
    if info['access_challenge']:raise Stop('access_challenge_stop')
  selected=scripts_for(page,source=='sberbank_ast');row['script_evidence']=[]
  for script in selected:
   if not script:row['errors'].append('expected_loader_not_linked');continue
   if not safe_url(script,hosts):row['errors'].append('external_script_not_fetched');continue
   _,ev=reader.get(script,hosts,source,6_000_000);row['script_evidence'].append(ev)
  row['status']='evidence_collected_adapter_not_verified'
  if row['errors']:row['status']='partial_evidence'
 except Exception as exc:
  row['status']='incomplete'
  row['errors'].append(str(exc) if isinstance(exc,Stop) else type(exc).__name__)
 finally:row['requests']=reader.requests-before
 return row

SNAPSHOT=r'''
import json,ast
from pathlib import Path
from datetime import datetime,timezone
out={'observed_at':datetime.now(timezone.utc).isoformat(),'registry':{},'schedules':[],'reports':{},'errors':[]}
try:
 tree=ast.parse(Path('app/sources/registry.py').read_text())
 for node in ast.walk(tree):
  if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SOURCE_REGISTRY' for t in node.targets) and isinstance(node.value,ast.Dict):
   out['registry']={str(ast.literal_eval(k)):ast.unparse(v) for k,v in zip(node.value.keys,node.value.values) if k is not None}
except Exception as e:out['errors'].append({'section':'registry','type':type(e).__name__})
try:
 from app.workers.celery_app import celery_app
 out['timezone']=celery_app.conf.timezone
 for k,v in celery_app.conf.beat_schedule.items():
  out['schedules'].append({'entry':k,'task':v.get('task'),'args':v.get('args'),'schedule':str(v.get('schedule'))})
except Exception as e:out['errors'].append({'section':'schedule','type':type(e).__name__})
try:
 from app.marketplace_discovery.primary.collector import folder
 root=folder()
 for p in root.glob('*.json'):
  if p.stat().st_size>5000000:continue
  try:
   d=json.loads(p.read_text());out['reports'][p.stem]={k:d.get(k) for k in ('checked_at','status','pipeline_status','backlog_pending','errors')}
  except Exception:pass
except Exception as e:out['errors'].append({'section':'reports','type':type(e).__name__})
print('AUDIT_SNAPSHOT_JSON:'+json.dumps(out,ensure_ascii=False,default=str))
'''

def installed_snapshot(skip=False):
 if skip:return {'status':'skipped','note':'No container inspection requested'}
 try:
  r=subprocess.run(['docker','compose','exec','-T','app','python','-'],input=SNAPSHOT,text=True,capture_output=True,timeout=45)
  line=next((x for x in r.stdout.splitlines() if x.startswith('AUDIT_SNAPSHOT_JSON:')),None)
  if not line:return {'status':'unavailable','exit_code':r.returncode,'note':'app unavailable or snapshot failed; not proof of disconnected sources'}
  data=json.loads(scrub(line.split(':',1)[1]))
  now=datetime.now(timezone.utc)
  for row in data.get('reports',{}).values():
   try:
    dt=datetime.fromisoformat(str(row.get('checked_at')).replace('Z','+00:00'))
    row['age_hours']=round((now-dt).total_seconds()/3600,2) if dt.tzinfo else None
   except (ValueError,TypeError):row['age_hours']=None
  data['note']='Configuration and reports from app image only; running Beat/workers, broker queues and DB states not independently audited'
  return data
 except Exception as exc:return {'status':'unavailable','error_type':type(exc).__name__}

def write_results(folder,report):
 (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 lines=['Проверка источников '+report['started_at'],
        'Это аудит доступности и сохранение публичных исходников. Готовность сбора/OCR/LLM не подтверждается HTTP 200.',
        'Платные агрегаторы исключены. Бесплатность участия/аккредитации отдельно не проверялась.',
        'Порог отбора в действующей системе не меняется: 500 кг; при неизвестной массе 200 шт; без суммирования позиций.',
        'БД/очереди не изменяются. Пустые очереди этим аудитом НЕ подтверждаются.','']
 for row in report['sources']:lines.append(row['source']+': '+row['status']+'; '+', '.join(row.get('errors',[])))
 lines+=['','Отложены: '+json.dumps(HELD,ensure_ascii=False),'',
         'Для следующего этапа нужен report.json и полные evidence-файлы; всё включено в ZIP.',
         'Архив содержит только результаты чтения и публичные источники. Приложение и .env не копируются.']
 (folder/'SUMMARY.txt').write_text('\n'.join(lines),encoding='utf-8')
 archive=folder.with_suffix('.zip')
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(folder.iterdir()):
   if p.is_file():z.write(p,p.name)
 os.chmod(archive,0o600)
 return archive

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--self-test',action='store_true',help='offline tests only; no HTTP or Docker')
 parser.add_argument('--sources',nargs='+',choices=tuple(NEW),help='default: all 14 new/unfinished sources')
 parser.add_argument('--skip-installed',action='store_true',help='skip read-only app configuration/report snapshot')
 args=parser.parse_args()
 if args.self_test:return self_test()
 folder=Path(tempfile.mkdtemp(prefix='tender-audit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-',dir='.')).resolve()
 os.chmod(folder,0o700)
 report={'version':VERSION,'started_at':datetime.now(timezone.utc).isoformat(),'keywords':KEYWORDS,'existing_sources':EXISTING,'held':HELD,'sources':[],'installed':installed_snapshot(args.skip_installed),'business_mutations':False}
 reader=Reader(folder)
 try:
  for source in args.sources or NEW:
   print('CHECKING:',source,flush=True);row=probe(source,reader);report['sources'].append(row)
   print(json.dumps({'source':source,'status':row['status'],'requests':row['requests'],'errors':row['errors']},ensure_ascii=False),flush=True)
 except KeyboardInterrupt:report['interrupted']=True
 finally:
  report.update(finished_at=datetime.now(timezone.utc).isoformat(),requests=reader.requests,downloaded_bytes=reader.total,evidence=reader.evidence)
  archive=write_results(folder,report)
  print('REPORT:',folder/'report.json',flush=True);print('ARCHIVE:',archive,flush=True)
  print('READ_ONLY_BUSINESS: no DB changes, task submissions, OCR, LLM, installs or service restarts; diagnostic files written',flush=True)

# Tests below use local synthetic data and never instantiate a network Reader.
def self_test():
 class Tests(unittest.TestCase):
  def test_urls(self):
   h={'etp.pik.ru'}
   self.assertTrue(safe_url('https://etp.pik.ru/trades',h))
   for u in ['http://etp.pik.ru/','https://evil.test/','https://user@etp.pik.ru/','https://etp.pik.ru:444/','https://etp.pik.ru/?token=x','https://etp.pik.ru/login']:
    self.assertFalse(safe_url(u,h),u)
  def test_page(self):
   p=Page('https://etp.pik.ru/trades');p.feed('<title>Тендеры</title><script src="/main.js">алюминий</script><a href="/trades/44">Лист алюминиевый 44кг</a>')
   d=p.summary();self.assertEqual(d['candidate_links'][0]['eligibility'],'unverified');self.assertFalse(d['access_challenge'])
   self.assertEqual(d['keyword_mentions_in_page'],['алюм'])
  def test_form(self):
   p=Page('https://etp.pik.ru/trades');p.feed('<form action="/trades" method="get"><input name="q"><input type="hidden" name="token" value="secret"></form>')
   u=search_form(p,{'etp.pik.ru'});self.assertNotIn('secret',u);self.assertIn('q=',u)
  def test_sber_full_sources(self):
   p=Page(SBER_CARD);p.feed(''.join('<script src="'+s+'"></script>' for s in SBER_SCRIPTS)+ '<script src="/chat.js"></script>')
   self.assertEqual([urlsplit(u).path for u in scripts_for(p,True)],list(SBER_SCRIPTS))
  def test_scrub(self):
   self.assertNotIn('secret-value',scrub('token="secret-value"'))
   self.assertNotIn('secret-value',scrub('<input type="hidden" value="secret-value">'))
  def test_stop_and_no_false_ready(self):
   class Fake:
    requests=0
    def get(self,*a,**kw):
     self.requests+=1
     return '<title>Anti-bot verification</title>',{'http':200}
   f=Fake();r=probe('pik',f);self.assertEqual(f.requests,1);self.assertFalse(r['pipeline_ready']);self.assertIn('access_challenge_stop',r['errors'])
  def test_evidence_zip(self):
   with tempfile.TemporaryDirectory() as t:
    p=Path(t)/'audit';p.mkdir();body='new Vue('+('x'*200000)+')';(p/'sber.js').write_text(body)
    z=write_results(p,{'started_at':'test','sources':[]})
    with zipfile.ZipFile(z) as a:self.assertEqual(a.read('sber.js').decode(),body)
  def test_no_business_actions(self):
   tree=ast.parse(SNAPSHOT)
   forbidden={'delay','apply_async','commit','flush','revoke','purge','send_task'}
   self.assertFalse(any(isinstance(n,ast.Attribute) and n.attr in forbidden for n in ast.walk(tree)))
  def test_catalog(self):
   self.assertEqual(len(NEW),14);self.assertFalse(set(NEW)&set(HELD));self.assertFalse(set(NEW)&set(EXISTING))
 result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
 if not result.wasSuccessful():raise SystemExit(1)
 print('AUDIT_SELF_TEST_OK: offline; no marketplace HTTP, Docker, DB, queues or LLM')

if __name__=='__main__':main()
