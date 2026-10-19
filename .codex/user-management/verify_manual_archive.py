"""2026-10-19 hoyeon.han: 수동 3파일 백업의 합성자료 검증과 로컬 복구 리허설.

원본 저장소 DB/키/업무자료를 mount하지 않고 임시 경로만 사용한다.
실제 Docker는 --docker 명시 시에만 사용하며 외부 pull/운영 접근을 하지 않는다.
"""
from __future__ import annotations
import argparse,copy,hashlib,importlib.util,io,json,os,secrets,shutil,sqlite3,stat,sys,tarfile,tempfile,time
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name=='user-management' else Path.cwd()
BASE=ROOT/'.codex/user-management/verify_rollback.py'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load_module(path,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
 sys.modules[name]=module;spec.loader.exec_module(module);return module

def release_api():return load_module(ROOT/'scripts/release_snapshot.py','manual_release_api_'+secrets.token_hex(4))
def existing_qa():return load_module(BASE,'manual_existing_qa_'+secrets.token_hex(4))
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()
def write_private(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 path.write_bytes(data if isinstance(data,bytes) else data.encode());path.chmod(0o600)

def add_member(archive,name,data=b'',kind=tarfile.REGTYPE,linkname=''):
 member=tarfile.TarInfo(name);member.type=kind;member.mode=0o700 if kind==tarfile.DIRTYPE else 0o600
 member.linkname=linkname;member.size=len(data) if kind==tarfile.REGTYPE else 0
 archive.addfile(member,io.BytesIO(data) if member.size else None)

class SyntheticArchive:
 """Docker 없이 생성하는 GNU 저장 형식의 합성 3파일과 실제 SQLite 자료."""
 def __init__(self,parent=None,*,deduplicate=False,empty_customer=False):
  self.root=Path(tempfile.mkdtemp(prefix='sollume-manual-mock-',dir=parent or '/private/tmp'))
  self.root.chmod(0o700);self.app=self.root/'app';self.app.mkdir(mode=0o700)
  self.backup=self.app/'database/backups/releases/manual-before-auth-fixture'
  self.backup.mkdir(parents=True,mode=0o700)
  for name in ('processed','uploads','order_data','logs'):(self.app/name).mkdir(mode=0o700)
  write_private(self.app/'거래처마스터.xlsx',b'synthetic master')
  write_private(self.app/'order_data/current.xlsm',b'synthetic original orders')
  self.api_key='synthetic-api-'+secrets.token_urlsafe(20)
  self.password='Synthetic-manual-'+secrets.token_urlsafe(20)
  self.sensitive=[self.api_key,self.password]
  self.env=('ORDER_API_KEY='+self.api_key+'\nTZ=Asia/Seoul\n').encode()
  write_private(self.app/'.env',self.env)
  import bcrypt
  self.old_hash=bcrypt.hashpw(self.password.encode(),bcrypt.gensalt(rounds=4)).decode()
  self.sensitive.append(self.old_hash)
  with closing(sqlite3.connect(self.app/'database/users.db')) as conn,conn:
   conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,password_hash TEXT,full_name TEXT,email TEXT,is_active BOOLEAN,is_admin BOOLEAN,created_at TEXT,last_login TEXT,login_count INTEGER)')
   for uid,name,admin in ((42,'changed',1),(43,'stable',0),(77,'demoted',1),(99,'stopped',0),(105,'deleted',0)):
    conn.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?)',(uid,name,self.old_hash,'합성 직원','fixture@example.invalid',1,admin,'2026-10-19',None,0))
  customer=self.app/'database/customer_master.db'
  if empty_customer:customer.write_bytes(b'')
  else:
   with closing(sqlite3.connect(customer)) as conn,conn:
    conn.execute('CREATE TABLE customers(id INTEGER,label TEXT)');conn.execute('INSERT INTO customers VALUES(1,?)',('합성 거래처',))
  write_private(self.app/'database/users.db-wal',b'')
  self.image_configs=[];self.images=[]
  for role in ('sollume-app','sollume-api'):
   cmd=['streamlit','run','Home.py','--server.address=0.0.0.0','--server.port=8501'] if role=='sollume-app' else ['gunicorn','--bind','0.0.0.0:8502','--workers','1','--pythonpath','/app/Src','api_server:app']
   config={'architecture':'arm64','os':'linux','config':{'WorkingDir':'/app','Env':['PATH=/usr/local/bin:/usr/bin:/bin'],'Entrypoint':None,'Cmd':cmd if not deduplicate else ['streamlit','run','Home.py']},'rootfs':{'type':'layers','diff_ids':[]}}
   raw=canonical(config);identifier='sha256:'+hashlib.sha256(raw).hexdigest()
   self.image_configs.append((identifier,raw,config));self.images.append(identifier)
  self.project='sollume-manual-fixture'
  self.containers=[]
  api=release_api()
  for index,role in enumerate(('sollume-app','sollume-api')):
   target=8501+index;paths=sorted(api.MOUNT_SETS[role]);mounts=[]
   for destination in paths:
    relative='거래처마스터.xlsx' if destination=='/app/Src/거래처마스터.xlsx' else destination.removeprefix('/app/')
    mounts.append({'Type':'bind','Source':str(self.app/relative),'Destination':destination,'RW':not(role=='sollume-api' and destination=='/app/order_data' or destination=='/app/Src/거래처마스터.xlsx')})
   command=['streamlit','run','Home.py','--server.address=0.0.0.0','--server.port=8501'] if index==0 else ['gunicorn','--bind','0.0.0.0:8502','--workers','1','--pythonpath','/app/Src','api_server:app']
   self.containers.append({'Id':str(index+1)*64,'Name':'/sollume-finance-'+('app' if index==0 else 'api'),'Image':self.images[index],
    'Config':{'Image':'fixture:old','WorkingDir':'/app','Cmd':command,'Entrypoint':None,'Env':['ORDER_API_KEY='+self.api_key,'TZ=Asia/Seoul'],
              'Labels':{'com.docker.compose.project':self.project,'com.docker.compose.service':role,'com.docker.compose.project.working_dir':str(self.app)}},
    'Mounts':mounts,'State':{'Running':True},'HostConfig':{'NetworkMode':self.project+'_sollume-network','Privileged':False,
     'PortBindings':{str(target)+'/tcp':[{'HostIp':'127.0.0.1','HostPort':str(target)}]},'ReadonlyRootfs':False,'SecurityOpt':[],
     'Binds':[m['Source']+':'+m['Destination']+(':rw' if m['RW'] else ':ro') for m in mounts],
     'NanoCpus':4_000_000_000 if index==0 else 1_000_000_000,'Memory':20*1024**3 if index==0 else 2*1024**3,'MemoryReservation':4*1024**3 if index==0 else 0},
    'NetworkSettings':{'Networks':{self.project+'_sollume-network':{}}}})
  self.compose={'name':self.project,'services':{},'networks':{'sollume-network':{'name':self.project+'_sollume-network'}}}
  for record in self.containers:
   role=record['Config']['Labels']['com.docker.compose.service'];target=api.SERVICES[role]
   self.compose['services'][role]={'image':'fixture:old','command':record['Config']['Cmd'],'working_dir':'/app','networks':['sollume-network'],'read_only':False,
    'environment':{'ORDER_API_KEY':'${ORDER_API_KEY}'},'ports':[{'target':target,'published':str(target),'host_ip':'127.0.0.1'}],
    'volumes':[{'type':'bind','source':m['Source'],'target':m['Destination'],'read_only':not m['RW']} for m in record['Mounts']],
    'deploy':{'resources':{'limits':{'cpus':str(record['HostConfig']['NanoCpus']/1e9),'memory':record['HostConfig']['Memory']},'reservations':{'memory':record['HostConfig']['MemoryReservation']}}}}
  write_private(self.app/'docker-compose.cloud.yml',json.dumps(self.compose))
  self.members=[('./',b'',tarfile.DIRTYPE,'')]
  for folder in ('database','order_data'):
   self.members.append(('./'+folder+'/',b'',tarfile.DIRTYPE,''))
  for name in ('.env','docker-compose.cloud.yml','database/users.db','database/customer_master.db','database/users.db-wal','order_data/current.xlsm','거래처마스터.xlsx'):
   self.members.append(('./'+name,(self.app/name).read_bytes(),tarfile.REGTYPE,''))
  self.members.append(('./database/backups/nginx-configs/config',b'synthetic prior nginx copy',tarfile.REGTYPE,''))
  self.members.append(('./database/backups/customer_master_backup_old.db',customer.read_bytes(),tarfile.REGTYPE,''))
  self.members.append(('./.venv/bin/python',b'',tarfile.SYMTYPE,'/usr/bin/python3'))
  self.rebuild_application()
  with tarfile.open(self.backup/'images.tar','w',format=tarfile.GNU_FORMAT) as archive:
   manifest=[];seen=set()
   for identifier,raw,config in self.image_configs:
    if identifier in seen:continue
    seen.add(identifier);name=identifier.removeprefix('sha256:')+'.json'
    add_member(archive,name,raw);manifest.append({'Config':name,'RepoTags':[],'Layers':[]})
   add_member(archive,'manifest.json',canonical(manifest))
  write_private(self.backup/'containers.json',json.dumps(self.containers))
  for path in self.backup.iterdir():path.chmod(0o600)
  self.original_hashes=self.archive_hashes()
 def rebuild_application(self):
  with tarfile.open(self.backup/'application.tar.gz','w:gz',format=tarfile.GNU_FORMAT) as archive:
   for name,data,kind,link in self.members:add_member(archive,name,data,kind,link)
  (self.backup/'application.tar.gz').chmod(0o600)
 def archive_hashes(self):return {name:sha(self.backup/name) for name in ('application.tar.gz','images.tar','containers.json')}
 def close(self):shutil.rmtree(self.root)

class RecordingRunner:
 """명시적으로 지원하는 읽기 명령만 응답하며 변경 호출은 기록 후 거부한다."""
 def __init__(self,fixture):self.fixture=fixture;self.calls=[]
 def run(self,argv,*,input=None,env=None):
  argv=list(map(str,argv));self.calls.append(argv)
  if argv[:2]==['docker','inspect']:return json.dumps(self.fixture.containers)
  if argv[:3]==['docker','image','inspect']:
   return json.dumps([{'Id':identifier,'Architecture':config['architecture'],'Os':config['os'],'Config':config['config']} for identifier,raw,config in self.fixture.image_configs if identifier in argv])
  if argv[:2]==['docker','ps']:return '\n'.join(item['Id'] for item in self.fixture.containers)
  if argv[:3]==['docker','network','inspect']:return json.dumps([{'Name':self.fixture.project+'_sollume-network','Driver':'bridge'}])
  if argv[:2]==['docker','compose'] and 'config' in argv:
   rendered=copy.deepcopy(self.fixture.compose)
   for service in rendered['services'].values():service['environment']['ORDER_API_KEY']=self.fixture.api_key
   return json.dumps(rendered)
  raise RuntimeError('모의 runner에서 예상하지 않은 명령: '+str(argv[:3]))
 def https_status(self,*args,**kwargs):self.calls.append(['https-status']);return 503
 def internal_health(self,*args,**kwargs):return True

def manager(fixture,runner=None):
 return release_api().ManualBackupManager(fixture.app,fixture.backup,runner=runner)


class ManualLocalRunner:
 """호스트 Nginx 명령·포트만 격리 fixture에 연결하고 Docker 명령은 실제 실행한다."""
 def __init__(self,fixture):
  self.fixture=fixture;self.base=fixture.base.LocalRunner(fixture);self.calls=self.base.calls
  self.https_observations=[];self.http_observations=[]
 def run(self,argv,*,input=None,env=None):
  command=list(map(str,argv))
  normalized=command[:]
  if normalized[:2]==['sudo','-n']:normalized=['sudo',*normalized[2:]]
  if normalized==['sudo','nginx','-T']:
   self.calls.append(command)
   # 2026-10-19 hoyeon.han: 원본host포트·사이트파일 이름으로 검사하고 실제검사는별도파생구성에연결한다.
   # 2026-10-19 hoyeon.han: 회계 외 사이트도 실제 Nginx 조회에 포함하여 선택적 차단을 검증한다.
   # return '\n'.join('# configuration file '+str(path)+':\n'+path.read_text() for path in self.fixture.nginx_configs)
   return '\n'.join('# configuration file '+str(path)+':\n'+path.read_text() for path in (*self.fixture.nginx_configs,self.fixture.unrelated_site))
  return self.base.run(normalized,input=input,env=env)
 def https_status(self,origin,path,headers=None):
  import ssl,urllib.request,urllib.error
  from urllib.parse import urlsplit
  domain=urlsplit(origin).netloc
  request=urllib.request.Request('https://127.0.0.1:'+str(self.fixture.https_port)+path,headers={'Host':domain,**(headers or {})})
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args,**kwargs):return None
  opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(self.fixture.app/'ssl/fullchain.pem'))),NoRedirect())
  start=time.monotonic()
  try:
   with opener.open(request,timeout=10) as response:response.read();status=response.status
  except urllib.error.HTTPError as error:status=error.code
  except (OSError,urllib.error.URLError):status=0
  self.https_observations.append({'host':domain,'path':path,'status':status,'seconds':round(time.monotonic()-start,3)})
  return status
 def http_status(self,origin,path,headers=None):
  import urllib.request,urllib.error
  from urllib.parse import urlsplit
  host=urlsplit(origin).netloc
  request=urllib.request.Request('http://127.0.0.1:'+str(self.fixture.http_port)+path,headers={'Host':host,**(headers or {})})
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args,**kwargs):return None
  opener=urllib.request.build_opener(NoRedirect())
  try:
   with opener.open(request,timeout=10) as response:response.read();status=response.status
  except urllib.error.HTTPError as error:status=error.code
  except (OSError,urllib.error.URLError):status=0
  self.http_observations.append({'host':host,'path':path,'status':status});return status
 def internal_health(self,*args,**kwargs):return self.base.internal_health(*args,**kwargs)
 def internal_status(self,*args,**kwargs):return self.base.internal_status(*args,**kwargs)


def docker_fixture_type():
 base=existing_qa()
 class ManualFixture(base.Fixture):
  def __init__(self):
   # 2026-10-19 hoyeon.han: HTTP 게시·ACME mount는 공통 Fixture가 소유하므로 중복 게시하지 않는다.
   # super().__init__(legacy=True);self.base=base;self.http_port=base.port()
   # original_command=base.command
   # def fixture_command(argv,**kwargs):
   #  argv=list(argv)
   #  if argv[:2]==['docker','run'] and '--name' in argv and argv[argv.index('--name')+1]==self.nginx_name:
   #   argv=argv[:-1]+['-p','127.0.0.1:'+str(self.http_port)+':80',argv[-1]]
   #  return original_command(argv,**kwargs)
   # base.command=fixture_command
   super().__init__(legacy=True);self.base=base
   self.nginx_configs=[self.app/'nginx.site',self.app/'legacy-nginx.site']
   self.runner=ManualLocalRunner(self)
   self.manager=self.api.ReleaseManager(self.app,self.nginx_configs[0],runner=self.runner)
  def render_runtime_nginx(self):
   content='\n'.join(path.read_text() for path in self.nginx_configs if path.exists())
   for target in (8501,8502,8503):
    content=content.replace('http://127.0.0.1:'+str(target),'http://host.docker.internal:'+str(self.ports[target]))
   content=content.replace('http://sollume-app:8501','http://host.docker.internal:'+str(self.ports[8501]))
   (self.app/'nginx-runtime.site').write_text(content)
  def prepare_manual_files(self):
   super().prepare()
   compose=json.loads((self.app/'docker-compose.cloud.yml').read_text())
   compose['services']['sollume-api']['image']=base.image_id('sollume-finance-sollume-api:latest')
   (self.app/'docker-compose.cloud.yml').write_text(json.dumps(compose))
   base.command(self.compose('up','-d','--pull','never','--no-build','--wait','--wait-timeout','90'))
   primary=self.nginx_configs[0].read_text().replace('http://sollume-app:8501','http://127.0.0.1:8501')
   self.nginx_configs[0].write_text(primary)
   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
   # self.nginx_configs[1].write_text('server { listen 80; server_name sol-fin.duckdns.org; return 301 https://sol-fin.duckdns.org$request_uri; }\n'+primary.replace('default_server','').replace('server_name sollumeesthe.com','server_name sol-fin.duckdns.org'))
   # 2026-10-19 hoyeon.han: 공통 legacy fixture의 HTTP 블록을 재사용하여 중복 server_name을 만들지 않는다.
   # self.nginx_configs[1].write_text('server { listen 80; server_name sol-fin.duckdns.org; return 301 https://sol-fin.duckdns.org$request_uri; }\n'+primary.replace('default_server','').replace('server_name office1.sollumeesthe.com','server_name sol-fin.duckdns.org'))
   self.nginx_configs[1].write_text(primary.replace('default_server','').replace('server_name office1.sollumeesthe.com','server_name sol-fin.duckdns.org'))
   self.runner.run(['sudo','nginx','-t']);self.runner.run(['sudo','systemctl','reload','nginx'])
   (self.app/'.venv/bin').mkdir(parents=True);(self.app/'.venv/bin/python').symlink_to('/usr/bin/python3')
   (self.app/'database/backups/nginx-configs').mkdir(parents=True,exist_ok=True)
   write_private(self.app/'database/backups/nginx-configs/config',primary)
   shutil.copyfile(self.app/'database/customer_master.db',self.app/'database/backups/customer_master_backup_old.db')
   write_private(self.app/'database/users.db-wal',b'')
   self.backup=self.app/'database/backups/releases/manual-before-auth-fixture';self.backup.mkdir(parents=True,mode=0o700)
   identifiers=base.command(self.compose('ps','-aq')).split()
   inspect=json.loads(base.command(['docker','inspect',*identifiers]))
   self.saved_containers=inspect;write_private(self.backup/'containers.json',json.dumps(inspect))
   images=sorted({item['Image'] for item in inspect});self.saved_image_ids=images
   base.command(['docker','image','save','--output',str(self.backup/'images.tar'),*images])
   base.command(self.compose('stop'))
   try:
    secure=base.image_id('sollume-finance-security:venv-test')
    self.gnu_tar_version=base.command(['docker','run','--rm','--pull','never','--network','none','--read-only','--entrypoint','tar',secure,'--version']).splitlines()[0]
    base.command(['docker','run','--rm','--pull','never','--network','none','--read-only',
     '-v',str(self.app)+':/fixture:ro','-v',str(self.backup)+':/out','--entrypoint','tar',secure,
     '--acls','--xattrs','-czf','/out/application.tar.gz','--exclude=./database/backups/releases','-C','/fixture','.'])
   finally:
    orphan=self.app/'database/users.db-wal'
    if orphan.exists() and orphan.stat().st_size==0:orphan.unlink()
    base.command(self.compose('up','-d','--pull','never','--no-build','--wait','--wait-timeout','90'))
   for path in self.backup.iterdir():path.chmod(0o600)
   self.original_manual_hashes={name:sha(self.backup/name) for name in ('application.tar.gz','images.tar','containers.json')}
   return self
  def manual_manager(self,nginx_configs=None):
   return self.api.ManualBackupManager(self.app,self.backup,nginx_configs=self.nginx_configs if nginx_configs is None else nginx_configs,runner=self.runner)
  def upgrade_current_to_security(self):
   from cryptography.fernet import Fernet
   base.command(self.compose('down'))
   self.current_api_key=secrets.token_urlsafe(32);self.secrets.append(self.current_api_key)
   env_path=self.app/'.env';env_path.write_text(env_path.read_text().replace('ORDER_API_KEY='+self.api_key,'ORDER_API_KEY='+self.current_api_key))
   self.secure_image=base.image_id('sollume-finance-security:venv-test')
   config=json.loads((self.app/'docker-compose.cloud.yml').read_text())
   for service in config['services'].values():service['image']=self.secure_image
   auth=copy.deepcopy(config['services']['sollume-app'])
   auth['volumes']=[volume for volume in auth['volumes'] if volume['target'] in ('/app/database','/app/processed','/app/logs')]
   auth['ports']=[{'host_ip':'127.0.0.1','published':str(self.ports[8503]),'target':8503}]
   auth['command']=['gunicorn','--bind','0.0.0.0:8503','--workers','1','--pythonpath','/app/Src','auth_gateway:create_app()']
   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
   # auth['healthcheck']['test']=['CMD','curl','-f','-H','Host: sollumeesthe.com','http://localhost:8503/auth/health']
   auth['healthcheck']['test']=['CMD','curl','-f','-H','Host: office1.sollumeesthe.com','http://localhost:8503/auth/health']
   auth.pop('deploy',None);config['services']['sollume-auth']=auth
   (self.app/'docker-compose.cloud.yml').write_text(json.dumps(config))
   service=base.SecurityService(self.app/'database/users.db',self.key,self.app/'processed/secure_downloads')
   service.reset_password_local(42,self.next_password);service.update_user_local(77,is_admin=False);service.update_user_local(99,is_active=False)
   with closing(sqlite3.connect(self.app/'database/users.db')) as conn,conn:
    conn.execute('DELETE FROM users WHERE id=105')
    conn.execute('INSERT INTO users(id,username,password_hash,full_name,email,is_active,is_admin,permissions) VALUES(?,?,?,?,?,?,?,?)',
      (111,'qa_added',base.SecurityService.hash_password(self.next_password),'추가 직원','added@example.invalid',1,1,'["daily-voucher"]'))
    conn.execute('UPDATE users SET mfa_enrolled=1,mfa_secret_cipher=?,must_change_password=0 WHERE id=43',
      (Fernet(self.key.encode()).encrypt(self.mfa_secret.encode()).decode(),))
   with closing(sqlite3.connect(self.app/'database/customer_master.db')) as conn,conn:
    conn.execute('INSERT INTO customers VALUES(2,?)',('합성 최신 거래처',))
   write_private(self.app/'order_data/current.xlsm',b'synthetic latest orders must survive manual rollback')
   self.current_business={name:sha(self.app/name) for name in ('database/customer_master.db','order_data/current.xlsm','order_data/current.meta.json')}
   primary=(ROOT/'nginx-host-api.conf.example').read_text()
   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
   # primary=primary.replace('/etc/letsencrypt/live/sollumeesthe.com/fullchain.pem',str(self.app/'ssl/fullchain.pem'))
   primary=primary.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/fullchain.pem',str(self.app/'ssl/fullchain.pem'))
   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
   # primary=primary.replace('/etc/letsencrypt/live/sollumeesthe.com/privkey.pem',str(self.app/'ssl/privkey.pem'))
   primary=primary.replace('/etc/letsencrypt/live/office1.sollumeesthe.com/privkey.pem',str(self.app/'ssl/privkey.pem'))
   self.nginx_configs[0].write_text(primary)
   base.command(self.compose('up','-d','--pull','never','--no-build','--wait','--wait-timeout','90'))
   self.runner.run(['sudo','nginx','-t']);self.runner.run(['sudo','systemctl','reload','nginx'])
   return self
 return ManualFixture


class Verification:
 def __init__(self,output):
  self.output=Path(output);self.fixtures=[];self.checks=[];self.failure=None;self.cleanup_complete=True
  self.started=datetime.now(timezone.utc).isoformat();self.scope='manual archive prepare vertical'
  names=('scripts/release_snapshot.py','deploy-oracle.sh','rollback-oracle.sh','.codex/user-management/verify_manual_archive.py','.codex/tests/test_manual_archive.py')
  self.sources={name:sha(ROOT/name) for name in names}
  names=json.loads((ROOT/'.codex/user-management/data-baseline.json').read_text())
  self.originals={name:sha(ROOT/name) for name in names}
 def check(self,name,passed,evidence='actual Docker/GNU tar/SQLite'):
  self.checks.append({'name':name,'passed':bool(passed),'evidence':evidence});print(('PASS ' if passed else 'FAIL ')+name,flush=True)
  if not passed:raise AssertionError(name)
 def prepare(self):
  fixture=docker_fixture_type()();self.fixtures.append(fixture);fixture.prepare_manual_files()
  # 2026-10-19 hoyeon.han: 압축 전후 legacy 실행 상태에서 공개 ACME 파일과 다른 사이트가 살아 있다.
  self.check('manual_initial_acme_http200_body_matches_and_other_sites_preserved',fixture.acme_available() and fixture.unrelated_preserved())
  self.check('actual_gnu_tar_binary_used','GNU tar' in fixture.gnu_tar_version)
  with tarfile.open(fixture.backup/'application.tar.gz','r:gz') as archive:
   members={member.name:member for member in archive.getmembers()}
   self.check('actual_gnu_root_dot_and_dot_slash_prefix_present',any(name in ('.','./') for name in members) and any(name.startswith('./') for name in members))
   self.check('actual_nonselected_virtualenv_symlink_and_past_backups_present',members['./.venv/bin/python'].issym()
    and './database/backups/nginx-configs/config' in members and './database/backups/customer_master_backup_old.db' in members)
   self.check('actual_zero_length_wal_entry_present',members['./database/users.db-wal'].size==0)
  manual=fixture.manual_manager();before=dict(fixture.original_manual_hashes)
  initial_calls=len(fixture.runner.calls);plan=manual.plan()
  self.check('actual_manual_plan_validated_without_docker_mutation',plan['validated'] and plan['dry_run'] and len(fixture.runner.calls)==initial_calls)
  self.check('actual_two_distinct_original_image_ids_preserved',len(fixture.saved_image_ids)==2 and set(plan['images'])==set(fixture.saved_image_ids))
  prepared=manual.prepare(check_current=True);reused=manual.prepare(check_current=True)
  self.check('actual_manual_prepare_idempotent',prepared['prepared'] and reused['reused'] and prepared['release']==reused['release'])
  fixture.manual_release=Path(prepared['release']);fixture.prepared=prepared
  compose=json.loads((fixture.manual_release/'compose.json').read_text())
  self.check('actual_inspect_cmd_entrypoint_and_image_generate_restoration_compose',all(
   compose['services'][item['Config']['Labels']['com.docker.compose.service']]['image']==item['Image']
   and compose['services'][item['Config']['Labels']['com.docker.compose.service']]['command']==item['Config']['Cmd']
   and (compose['services'][item['Config']['Labels']['com.docker.compose.service']]['entrypoint'] or [])==(item['Config']['Entrypoint'] or []) for item in fixture.saved_containers))
  self.check('actual_source_three_archives_unchanged_after_prepare',all(sha(fixture.backup/name)==value for name,value in before.items()))
  return fixture
 def canaries_running(self,fixture):
  values=json.loads(fixture.base.command(['docker','inspect',*fixture.canary_ids]))
  return all(item['State']['Running'] and item['Image']==fixture.nginx_image for item in values)
 def blocked(self,fixture):
  # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
  # return all(fixture.runner.https_status('https://'+host,path)==503 for host in ('sollumeesthe.com','sol-fin.duckdns.org') for path in ('/','/auth/login','/downloads/test')) and all(
  return all(fixture.runner.https_status('https://'+host,path)==503 for host in ('office1.sollumeesthe.com','sol-fin.duckdns.org') for path in ('/','/auth/login','/downloads/test')) and all(
   # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
   # fixture.runner.http_status('http://'+host,'/')==503 for host in ('sollumeesthe.com','sol-fin.duckdns.org'))
   fixture.runner.http_status('http://'+host,'/')==503 for host in ('office1.sollumeesthe.com','sol-fin.duckdns.org'))
 def original_archives(self,fixture):
  return all(sha(fixture.backup/name)==value for name,value in fixture.original_manual_hashes.items())
 def old_image_login(self,fixture,username,password):
  program='import json,sys;sys.path.insert(0,"/app/Src");from user_db import UserDB;v=json.loads(sys.stdin.read());print(json.dumps({"accepted":bool(UserDB("/app/database/users.db").verify_credentials(v["username"],v["password"]))}))'
  output=fixture.base.command(['docker','run','--rm','-i','--pull','never','--network','none','--read-only','--tmpfs','/tmp',
   '-v',str(fixture.app/'database')+':/app/database','--entrypoint','python',fixture.image,'-B','-c',program],input=json.dumps({'username':username,'password':password}))
  return json.loads(output)['accepted']
 def runtime_preserved(self,fixture):
  current=json.loads(fixture.base.command(['docker','inspect',*fixture.base.command(fixture.compose('ps','-aq')).split()]))
  fixture.restored_inspect=current
  original={item['Config']['Labels']['com.docker.compose.service']:item for item in fixture.saved_containers}
  for item in current:
   old=original[item['Config']['Labels']['com.docker.compose.service']]
   if item['Image']!=old['Image']:return False
   for key in ('Cmd','Entrypoint','User','WorkingDir'):
    if key in ('Cmd','Entrypoint'):
     if (item['Config'].get(key) or [])!=(old['Config'].get(key) or []):return False
    elif (item['Config'].get(key) or '')!=(old['Config'].get(key) or ''):return False
   for key in ('NanoCpus','Memory','MemoryReservation','ReadonlyRootfs','LogConfig'):
    if item['HostConfig'].get(key)!=old['HostConfig'].get(key):return False
   before={(mount['Source'],mount['Destination'],mount['RW']) for mount in old['Mounts'] if mount['Type']=='bind'}
   after={(mount['Source'],mount['Destination'],mount['RW']) for mount in item['Mounts'] if mount['Type']=='bind'}
   if before!=after:return False
   name=item['Config']['Labels']['com.docker.compose.service'];target=fixture.api.SERVICES[name]
   if item['HostConfig']['PortBindings']!={str(target)+'/tcp':[{'HostIp':'127.0.0.1','HostPort':str(fixture.ports[target])}]}:return False
  return len(current)==2
 def full(self,fixture):
  self.scope='complete manual archive restore rehearsal'
  # 2026-10-19 hoyeon.han: 다른 서비스 canary는 공통 Fixture에서 시작하여 전 과정 보존을 확인한다.
  # fixture.canary_ids=[]
  # for label in ('n8n','goodsfoundry'):
  #  identifier=fixture.base.command(['docker','run','-d','--name',fixture.project+'-canary-'+label,
  #   '--label','sollume.rollback.qa='+fixture.project,'--pull','never','--network','none','--read-only',
  #   '--entrypoint','sh',fixture.nginx_image,'-c','sleep 900']).strip();fixture.canary_ids.append(identifier)
  fixture.upgrade_current_to_security();manual=fixture.manual_manager()
  self.check('manual_secure_acme200_root401_download401_and_other_sites_preserved',fixture.acme_available()
   and fixture.runner.https_status('https://office1.sollumeesthe.com','/')==401
   and fixture.runner.https_status('https://office1.sollumeesthe.com','/downloads/blocked-test')==401
   and fixture.unrelated_preserved())
  before={str(path):sha(path) for path in (*fixture.nginx_configs,fixture.app/'database/users.db',fixture.app/'docker-compose.cloud.yml')}
  plan=manual.rollback()
  self.check('manual_rollback_defaults_readonly_and_never_public_resume',plan['dry_run'] and not plan['public_resume'] and all(sha(Path(path))==value for path,value in before.items()))
  for flags in ({},{'legacy_private':True},{'restore_users':True}):
   try:manual.rollback(apply=True,**flags);denied=False
   except ValueError:denied=True
   self.check('legacy_apply_requires_both_explicit_flags_'+str(len(flags))+str(flags.get('restore_users',False)),denied)
  try:fixture.manual_manager([fixture.nginx_configs[0]]).rollback(apply=True,legacy_private=True,restore_users=True);denied=False
  except ValueError:denied=True
  self.check('unlisted_actual_legacy_site_rejected_before_any_source_or_runtime_mutation',denied and all(sha(Path(path))==value for path,value in before.items()) and self.canaries_running(fixture))
  fixture.runner.base.fail_stage='image';fixture.runner.base.injected=False
  try:manual.rollback(apply=True,legacy_private=True,restore_users=True);failed=False
  except ValueError:
   if not fixture.runner.base.injected:raise
   failed=True
  receipt=json.loads((fixture.manual_release/'rollback-receipt.json').read_text())
  rescue=Path(receipt['recovery_release'])
  self.check('injected_image_failure_preserves_current_backup_and_all_http_https_ingress503',failed and fixture.runner.base.injected and (rescue/'users.db').is_file() and self.blocked(fixture),evidence='actual Docker/SQLite/HTTP/HTTPS; image load failure injected')
  # 2026-10-19 hoyeon.han: 수동 복구 실패503에서도 office1 ACME만 HTTP200으로 유지한다.
  self.check('manual_failure_acme200_body_matches_and_other_sites_preserved',fixture.acme_available() and fixture.unrelated_preserved())
  self.check('failure_stops_only_accounting_containers_and_preserves_other_canaries',not fixture.base.command(fixture.compose('ps','-q')).strip() and self.canaries_running(fixture))
  self.check('failure_keeps_original_manual_archives_and_current_business_files',self.original_archives(fixture) and all(sha(fixture.app/name)==value for name,value in fixture.current_business.items()))
  fixture.runner.base.fail_stage=None
  result=manual.rollback(apply=True,legacy_private=True,restore_users=True)
  self.check('actual_manual_restore_from_partially_removed_state_completes_private',result['completed'] and not result['public_resume'] and self.blocked(fixture))
  self.check('manual_restore_acme200_body_matches_and_other_sites_preserved',fixture.acme_available() and fixture.unrelated_preserved())
  self.check('actual_inspect_config_resources_logs_bind_rw_and_loopback_ports_match_original',self.runtime_preserved(fixture))
  self.check('current_rotated_api_key_overrides_archived_key',all(dict(value.split('=',1) for value in item['Config']['Env']).get('ORDER_API_KEY')==fixture.current_api_key for item in fixture.restored_inspect if item['Config']['Labels']['com.docker.compose.service']=='sollume-api'))
  # 2026-10-19 hoyeon.han: 기존 도메인 검증을 보존하고 확정된 office1 주소로 검사합니다.
  # self.check('actual_legacy_service_health_checks_pass',fixture.runner.internal_health(8501,'sollumeesthe.com') and fixture.runner.internal_health(8502,'sollumeesthe.com'))
  self.check('actual_legacy_service_health_checks_pass',fixture.runner.internal_health(8501,'office1.sollumeesthe.com') and fixture.runner.internal_health(8502,'office1.sollumeesthe.com'))
  with closing(sqlite3.connect(fixture.app/'database/users.db')) as conn:
   rows={row[0]:row[1:] for row in conn.execute('SELECT id,username,is_active,is_admin FROM users')}
  self.check('latest_added_stopped_deleted_password_changed_accounts_and_demotion_preserved',rows[111]==('qa_added',0,0) and rows[43][1]==1 and rows[77][1:]==(1,0) and all(rows[uid][1]==0 for uid in (42,99,105)))
  rescue=Path(result['recovery_release'])
  with closing(sqlite3.connect(rescue/'users.db')) as conn:
   recovered=conn.execute('SELECT mfa_enrolled,mfa_secret_cipher,permissions FROM users WHERE id=43').fetchone()
   new_account=conn.execute('SELECT is_active,is_admin,permissions FROM users WHERE id=111').fetchone()
  self.check('latest_full_security_state_and_added_account_are_preserved_in_private_rescue',recovered[0]==1 and bool(recovered[1]) and new_account[0:2]==(1,1))
  self.check('current_business_files_original_archives_and_other_canaries_preserved',self.original_archives(fixture) and self.canaries_running(fixture) and all(sha(fixture.app/name)==value for name,value in fixture.current_business.items()))
  self.check('actual_old_image_private_login_accepts_unchanged_user',self.old_image_login(fixture,'qa_stable',fixture.password))
  self.check('actual_old_image_private_login_denies_discarded_password',not self.old_image_login(fixture,'qa_changed',fixture.password))
  for name in ('qa_stopped','qa_deleted'):
   try:manual.password(name);denied=False
   except ValueError:denied=True
   self.check('manual_password_cannot_revive_'+name,denied)
  self.check('manual_password_changed_admin_and_added_account_default_to_plan',manual.password('qa_changed')['dry_run'] and manual.password('qa_added')['account_id']==111)
  self.password_tty(fixture)
  self.check('actual_changed_admin_authenticates_privately_after_tty_reset',self.old_image_login(fixture,'qa_changed',fixture.next_password))
  self.check('manual_password_and_private_login_never_reopen_any_ingress',self.blocked(fixture) and self.canaries_running(fixture) and self.original_archives(fixture))
  self.check('manual_password_restore_keeps_acme200_and_other_sites_preserved',fixture.acme_available() and fixture.unrelated_preserved())
 def password_tty(self,fixture):
  import pty,select,subprocess
  state={'app':str(fixture.app),'backup':str(fixture.backup),'project':fixture.project,'nginx_name':fixture.nginx_name,
         'ports':fixture.ports,'https_port':fixture.https_port,'http_port':fixture.http_port,'sites':list(map(str,fixture.nginx_configs))}
  path=fixture.app/'private-tty-state.json';write_private(path,json.dumps(state));master,slave=pty.openpty()
  process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--password-worker',str(path)],stdin=slave,stdout=slave,stderr=slave,cwd=ROOT)
  os.close(slave);transcript=bytearray()
  def collect():
   if select.select([master],[],[],.2)[0]:
    try:data=os.read(master,65536)
    except OSError:return False
    transcript.extend(data);return bool(data)
   return True
  try:
   for marker in ('새 비밀번호(12자 이상, UTF-8 72바이트 이하): ','새 비밀번호 확인: '):
    deadline=time.monotonic()+90
    while marker not in transcript.decode(errors='replace'):
     if process.poll() is not None or time.monotonic()>deadline:raise AssertionError('manual-password 숨김 입력 prompt 확인 실패')
     collect()
    os.write(master,(fixture.next_password+'\n').encode())
   deadline=time.monotonic()+180
   while process.poll() is None and time.monotonic()<deadline:collect()
   if process.poll() is None:raise AssertionError('manual-password 처리 시간 초과')
   while collect() and select.select([master],[],[],0)[0]:pass
   self.check('actual_manual_password_tty_reset_succeeds_without_echo',process.returncode==0 and fixture.next_password not in transcript.decode(errors='replace'))
  finally:
   if process.poll() is None:process.kill();process.wait()
   os.close(master);path.unlink(missing_ok=True)

 def finish(self):
  diagnostics=[]
  for fixture in self.fixtures:
   diagnostics.append({'gnu_tar':getattr(fixture,'gnu_tar_version',None),'https_observations':fixture.runner.https_observations,
                       'http_observations':fixture.runner.http_observations,'docker_failures':fixture.runner.base.docker_failures,'saved_image_ids':getattr(fixture,'saved_image_ids',[]) })
  for fixture in reversed(self.fixtures):
   try:self.cleanup_complete=fixture.cleanup() and self.cleanup_complete
   except BaseException:self.cleanup_complete=False
  originals=all(sha(ROOT/name)==value for name,value in self.originals.items())
  sources=all(sha(ROOT/name)==value for name,value in self.sources.items())
  exception_chain=[];error=self.failure
  while error:
   message=str(error)
   for fixture in self.fixtures:
    for value in fixture.secrets:message=message.replace(value,'[비밀 제거]')
   exception_chain.append({'type':type(error).__name__,'message':message});error=error.__cause__
  passed=self.failure is None and all(row['passed'] for row in self.checks) and self.cleanup_complete and originals and sources
  report={'started_at':self.started,'generated_at':datetime.now(timezone.utc).isoformat(),'scope':self.scope,'passed':passed,
   'check_count':len(self.checks),'checks':self.checks,'latest_stage':('completed' if passed else (self.checks[-1]['name'] if self.checks else 'fixture_setup')),'helper_source_revision':self.sources['scripts/release_snapshot.py'],'source_sha256':self.sources,'source_unchanged_during_run':sources,
   'original_nine_files_unchanged':originals,'cleanup_complete':self.cleanup_complete,'production_deployed':False,
   'diagnostics':diagnostics,'exception_chain':exception_chain,
   'parent_regression':{'reported_by':'parent agent','directly_executed_here':False,'business_and_security_passed':240,'seconds':32.58,'python_312_stdlib_plan':{'reported_by':'parent agent','directly_executed_here':False,'version':'3.12.13','passed':True,'source_hash':'cb6384c94588019ab051e2364aa4c8e5934fb7ded82154803aa7d0926cf97130'}},
   'limitations':['Nginx sudo 명령은 격리 컨테이너로 연결했고 nginx-T 파일경계는 원본사이트 메타데이터를 반환한다.',
                  '실제 upstream은 host.docker.internal의 고유 loopback 게시포트로 연결한다. 운영8501/8503은 사용하지 않는다.',
                  'TLS는 임시 자체서명 fixture CA이며 외부 도메인에는 연결하지 않는다.', '운영의 원본 수동 3파일은 제공되지 않아 새로 만든 합성 백업으로만 검증했다.', '운영자 private 로그인은 실제 구버전 UserDB 핸들러를 network-none 컨테이너에서 검증했다. 브라우저 GUI 검증은 수행하지 않았다.']}
  serialized=json.dumps(report,ensure_ascii=False,indent=2)+'\n'
  if any(secret in serialized for fixture in self.fixtures for secret in fixture.secrets):raise AssertionError('보고서 비밀값 검사 실패')
  self.output.parent.mkdir(parents=True,exist_ok=True);write_private(self.output,serialized)
  write_private(self.output.with_suffix('.md'),'# 수동 백업 검증\n\n2026-10-19 hoyeon.han\n\n'+f'결과: {passed}, 검증 {len(self.checks)}개, 원본 불변: {originals}, 정리: {self.cleanup_complete}.\n\n'+'| 검증 | 결과 | 증거 |\n|---|---|---|\n'+'\n'.join('| '+row['name']+' | '+str(row['passed'])+' | '+row['evidence']+' |' for row in self.checks)+'\n')
  print(json.dumps({key:report[key] for key in ('passed','check_count','source_unchanged_during_run','original_nine_files_unchanged','cleanup_complete')},ensure_ascii=False),flush=True)
  return passed


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--prepare-smoke',action='store_true');parser.add_argument('--docker',action='store_true');parser.add_argument('--password-worker')
 parser.add_argument('--output',default=str(ROOT/'.codex/user-management/manual-archive-results.json'))
 args=parser.parse_args()
 if args.password_worker:
  state=json.loads(Path(args.password_worker).read_text());kind=docker_fixture_type();fixture=kind.__new__(kind)
  fixture.api=release_api();fixture.base=existing_qa();fixture.app=Path(state['app']);fixture.backup=Path(state['backup']);fixture.project=state['project'];fixture.nginx_name=state['nginx_name']
  # 2026-10-19 hoyeon.han: worker의 Nginx-T 경계에 다른 사이트도 동일하게 포함한다.
  # fixture.ports={int(key):value for key,value in state['ports'].items()};fixture.https_port=state['https_port'];fixture.http_port=state['http_port'];fixture.nginx_configs=list(map(Path,state['sites']))
  fixture.ports={int(key):value for key,value in state['ports'].items()};fixture.https_port=state['https_port'];fixture.http_port=state['http_port'];fixture.nginx_configs=list(map(Path,state['sites']));fixture.unrelated_site=fixture.app/'unrelated-nginx.site'
  fixture.api.EXPECTED_PUBLISHED_PORTS={name:fixture.ports[target] for name,target in fixture.api.SERVICES.items()};fixture.runner=ManualLocalRunner(fixture)
  result=fixture.manual_manager().password('qa_changed',apply=True);print(json.dumps({'completed':result['completed']}));return 0
 if not (args.docker or args.prepare_smoke):parser.error('실제 Docker는 --docker 또는 --prepare-smoke로 명시하세요.')
 verify=Verification(args.output)
 try:
  fixture=verify.prepare()
  if args.docker:verify.full(fixture)
 except BaseException as error:verify.failure=error;print('검증 중단: '+type(error).__name__,flush=True)
 finally:passed=verify.finish()
 if verify.failure:raise verify.failure
 return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
