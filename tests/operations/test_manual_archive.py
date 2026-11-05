# 2026-11-05 hoyeon.han: 재사용 검증 소스를 tests의 보안·운영 테스트로 분리한다.
"""2026-10-19 hoyeon.han: 수동 백업 3파일의 안전 파싱·사전 차단·실제 격리 복구 검증."""
from __future__ import annotations
import copy,importlib.util,json,os,stat,subprocess,sys,tarfile,sqlite3
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]

def qa():
 # spec=importlib.util.spec_from_file_location('manual_archive_qa',ROOT/'.codex/user-management/verify_manual_archive.py')
 # 2026-11-05 hoyeon.han: 로컬 작업 폴더 없이도 합성 fixture를 재사용한다.
 spec=importlib.util.spec_from_file_location('manual_archive_qa',ROOT/'scripts/verification/verify_manual_archive.py')
 loaded=importlib.util.module_from_spec(spec);sys.modules[spec.name]=loaded;spec.loader.exec_module(loaded);return loaded

@pytest.fixture
def fixture():
 helper=qa();value=helper.SyntheticArchive()
 try:yield helper,value
 finally:value.close()

def assert_offline_rejected(helper,value):
 runner=helper.RecordingRunner(value);before=value.archive_hashes()
 api=helper.release_api()
 with pytest.raises((api.SafetyError,ValueError,sqlite3.Error)):
  api.ManualBackupManager(value.app,value.backup,runner=runner).plan()
 assert value.archive_hashes()==before
 assert not runner.calls

def test_gnu_root_prefix_empty_customer_and_zero_wal_are_accepted():
 helper=qa();value=helper.SyntheticArchive(empty_customer=True)
 try:
  before=value.archive_hashes();runner=helper.RecordingRunner(value)
  result=helper.manager(value,runner).plan()
  assert isinstance(result,dict)
  assert value.archive_hashes()==before
  assert not runner.calls
 finally:value.close()

@pytest.mark.parametrize('duplicate_images',[False,True])
def test_saved_images_can_be_two_distinct_ids_or_one_shared_id(duplicate_images):
 helper=qa();value=helper.SyntheticArchive(deduplicate=duplicate_images)
 try:
  result=helper.manager(value,helper.RecordingRunner(value)).plan()
  assert isinstance(result,dict)
  assert len(set(value.images))==(1 if duplicate_images else 2)
 finally:value.close()

# 2026-10-20 hoyeon.han: 실제 운영과 같은 partial OCI 자료를 Docker 없이 만들어 안전 파싱 계약을 검증한다.
def oci_members(value):
 with tarfile.open(value.backup/'images.tar','r') as archive:
  return {member.name:archive.extractfile(member).read() for member in archive if member.isfile()}

def write_oci_members(helper,value,members):
 with tarfile.open(value.backup/'images.tar','w',format=tarfile.GNU_FORMAT) as archive:
  for name,data in members.items():helper.add_member(archive,name,data)
 (value.backup/'images.tar').chmod(0o600)

def replace_oci_root(helper,value,members,change):
 old=value.partial_oci['roots'][0]['image_id'];root=json.loads(members['blobs/sha256/'+old[7:]])
 change(root);raw=helper.canonical(root);new='sha256:'+helper.hashlib.sha256(raw).hexdigest()
 members['blobs/sha256/'+new[7:]]=raw;members.pop('blobs/sha256/'+old[7:],None)
 index=json.loads(members['index.json'])
 for descriptor in index['manifests']:
  if descriptor['digest']==old:descriptor.update(digest=new,size=len(raw))
 members['index.json']=helper.canonical(index)
 for record in value.containers:
  if record['Image']==old:record['Image']=new
 helper.write_private(value.backup/'containers.json',json.dumps(value.containers))

@pytest.mark.parametrize('shared_index',[False,True])
def test_partial_oci_plan_prepare_preserve_three_files_without_docker(shared_index):
 helper=qa();value=helper.SyntheticArchive(partial_oci=True,deduplicate=shared_index)
 try:
  members=oci_members(value);roots=value.partial_oci['roots']
  assert len(set(value.images))==(1 if shared_index else 2)
  assert 'index.json' in members and 'oci-layout' in members
  for root in roots:
   children=root['descriptor']['manifests']
   assert children[0]['platform']=={'os':'linux','architecture':'arm64'}
   assert all('blobs/sha256/'+children[index]['digest'][7:] in members for index in (0,2))
   assert all('blobs/sha256/'+children[index]['digest'][7:] not in members for index in (1,3))
  before=value.archive_hashes();runner=helper.RecordingRunner(value);manager=helper.manager(value,runner)
  plan=manager.plan();prepared=manager.prepare();reused=manager.prepare()
  assert plan['validated'] and plan['dry_run'] and prepared['prepared'] and reused['reused']
  assert set(plan['images'])==set(value.images)
  assert value.archive_hashes()==before and not runner.calls
 finally:value.close()

@pytest.mark.parametrize('artifact',['root','manifest','config','layer'])
@pytest.mark.parametrize('mutation',['missing','corrupted'])
def test_partial_oci_executable_chain_missing_or_changed_is_rejected(artifact,mutation):
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  root=value.partial_oci['roots'][0];digest={'root':root['image_id'],'manifest':root['runtime_digest'],
   'config':root['config_digest'],'layer':root['layer_digests'][0]}[artifact]
  members=oci_members(value);name='blobs/sha256/'+digest[7:]
  if mutation=='missing':members.pop(name)
  else:members[name]=b'X'+members[name][1:]
  write_oci_members(helper,value,members);assert_offline_rejected(helper,value)
 finally:value.close()

@pytest.mark.parametrize('platform',[None,{}, {'os':'linux'}, {'architecture':'amd64'},
 {'os':'unknown','architecture':'amd64'},{'os':'linux','architecture':'unknown'},
 {'os':'linux','architecture':'arm64'},{'os':'linux','architecture':'arm64','variant':'v7'}])
def test_partial_oci_missing_same_or_ambiguous_platform_is_rejected(platform):
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  members=oci_members(value)
  def change(root):
   if platform is None:root['manifests'][1].pop('platform')
   else:root['manifests'][1]['platform']=platform
  replace_oci_root(helper,value,members,change);write_oci_members(helper,value,members)
  assert_offline_rejected(helper,value)
 finally:value.close()

@pytest.mark.parametrize('mutation',['wrong-platform','missing-marker','wrong-marker','bad-annotations','bad-annotation-value'])
def test_partial_oci_invalid_attestation_descriptor_is_rejected(mutation):
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  members=oci_members(value)
  def change(root):
   child=root['manifests'][2 if mutation=='wrong-platform' else 3]
   if mutation=='wrong-platform':child['platform']={'os':'linux','architecture':'arm64'}
   elif mutation=='missing-marker':child['annotations'].pop('vnd.docker.reference.type')
   elif mutation=='wrong-marker':child['annotations']['vnd.docker.reference.type']='not-attestation'
   elif mutation=='bad-annotations':child['annotations']=[]
   else:child['annotations']['vnd.docker.reference.type']=True
  replace_oci_root(helper,value,members,change);write_oci_members(helper,value,members)
  assert_offline_rejected(helper,value)
 finally:value.close()

@pytest.mark.parametrize('mutation',['sha','size','boolean-size','invalid-digest'])
def test_partial_oci_foreign_present_blob_or_descriptor_corruption_is_rejected(mutation):
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  root=value.partial_oci['roots'][0];members=oci_members(value)
  name='blobs/sha256/'+root['foreign_descriptor']['digest'][7:];members[name]=root['foreign_raw']
  if mutation=='sha':members[name]=b'X'+members[name][1:]
  else:
   def change(node):
    child=node['manifests'][1]
    if mutation=='size':child['size']+=1
    elif mutation=='boolean-size':child['size']=True
    else:child['digest']='sha256:'+'g'*64
   replace_oci_root(helper,value,members,change)
  write_oci_members(helper,value,members);assert_offline_rejected(helper,value)
 finally:value.close()

def test_partial_oci_present_valid_foreign_descriptor_is_hash_checked_then_excluded():
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  members=oci_members(value)
  for root in value.partial_oci['roots']:
   members['blobs/sha256/'+root['foreign_descriptor']['digest'][7:]]=root['foreign_raw']
  write_oci_members(helper,value,members);before=value.archive_hashes();runner=helper.RecordingRunner(value)
  assert helper.manager(value,runner).plan()['validated']
  assert not runner.calls and value.archive_hashes()==before
 finally:value.close()

def test_partial_oci_duplicate_executable_selection_is_rejected():
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  members=oci_members(value)
  replace_oci_root(helper,value,members,lambda root:root['manifests'].append(copy.deepcopy(root['manifests'][0])))
  write_oci_members(helper,value,members);assert_offline_rejected(helper,value)
 finally:value.close()

def test_partial_oci_unused_valid_config_cannot_be_silently_excluded():
 helper=qa();value=helper.SyntheticArchive(partial_oci=True)
 try:
  members=oci_members(value);records=json.loads(members['manifest.json']);extra=copy.deepcopy(records[0])
  config=json.loads(members[extra['Config']]);config['config']['Labels']={'fixture':'unreferenced valid config'}
  raw=helper.canonical(config);name='blobs/sha256/'+helper.hashlib.sha256(raw).hexdigest();members[name]=raw
  extra['Config']=name;extra['RepoTags']=[];records.append(extra);members['manifest.json']=helper.canonical(records)
  write_oci_members(helper,value,members);assert_offline_rejected(helper,value)
 finally:value.close()

@pytest.mark.parametrize('bad_name',['../outside','./../outside','/etc/outside','one/../../outside'])
def test_tar_path_escape_is_rejected_before_any_docker_command(fixture,bad_name):
 helper,value=fixture;value.members.append((bad_name,b'x',tarfile.REGTYPE,''));value.rebuild_application()
 assert_offline_rejected(helper,value)

@pytest.mark.parametrize('kind,link',[(tarfile.SYMTYPE,'/etc/passwd'),(tarfile.LNKTYPE,'./elsewhere')])
def test_selected_database_links_are_rejected_without_extraction(fixture,kind,link):
 helper,value=fixture
 value.members=[row for row in value.members if row[0]!='./database/users.db']
 value.members.append(('./database/users.db',b'',kind,link));value.rebuild_application()
 assert_offline_rejected(helper,value)

@pytest.mark.parametrize('kind',[tarfile.FIFOTYPE,tarfile.CHRTYPE,tarfile.BLKTYPE])
def test_special_files_are_rejected(fixture,kind):
 helper,value=fixture;value.members.append(('./forbidden-special',b'',kind,''));value.rebuild_application()
 assert_offline_rejected(helper,value)

def test_normalized_duplicate_database_path_is_rejected(fixture):
 helper,value=fixture
 payload=next(row[1] for row in value.members if row[0]=='./database/users.db')
 value.members.append(('database/users.db',payload,tarfile.REGTYPE,''));value.rebuild_application()
 assert_offline_rejected(helper,value)

def test_nonselected_virtualenv_symlink_is_ignored_without_following(fixture):
 helper,value=fixture
 assert any(row[0]=='./.venv/bin/python' and row[2]==tarfile.SYMTYPE for row in value.members)
 assert isinstance(helper.manager(value,helper.RecordingRunner(value)).plan(),dict)
 assert not (value.app/'.venv').exists()

def test_corrupted_sqlite_database_is_rejected(fixture):
 helper,value=fixture
 value.members=[(name,b'not a SQLite database' if name=='./database/users.db' else data,kind,link) for name,data,kind,link in value.members]
 value.rebuild_application();assert_offline_rejected(helper,value)

def test_inspect_image_missing_from_saved_image_archive_is_rejected(fixture):
 helper,value=fixture;records=copy.deepcopy(value.containers);records[0]['Image']='sha256:'+'f'*64
 helper.write_private(value.backup/'containers.json',json.dumps(records));assert_offline_rejected(helper,value)

def test_container_mount_outside_original_application_is_rejected(fixture):
 helper,value=fixture;records=copy.deepcopy(value.containers);records[0]['Mounts'][0]['Source']='/unrelated/database'
 helper.write_private(value.backup/'containers.json',json.dumps(records));assert_offline_rejected(helper,value)


def shell_fixture(tmp_path):
 """실제 wrapper만 실행하고 외부 명령은 합성 파일을 읽는 실행 파일로 교체한다."""
 app=tmp_path/'app';(app/'scripts').mkdir(parents=True);(app/'database/backups/releases').mkdir(parents=True,mode=0o700)
 (app/'database/backups').chmod(0o755)
 for name in ('users.db','customer_master.db'):(app/'database'/name).write_bytes(b'synthetic unchanged database')
 # 2026-10-19 hoyeon.han: 실제 운영 도메인으로 wrapper의 사전 차단을 검증합니다.
 # (app/'.env').write_text('AUTH_ENV=production\nAUTH_PUBLIC_ORIGIN=https://sollumeesthe.com\nAUTH_ENCRYPTION_KEY=synthetic-not-an-operational-key\nORDER_API_KEY=synthetic-api\n');(app/'.env').chmod(0o600)
 (app/'.env').write_text('AUTH_ENV=production\nAUTH_PUBLIC_ORIGIN=https://office1.sollumeesthe.com\nAUTH_ENCRYPTION_KEY=synthetic-not-an-operational-key\nORDER_API_KEY=synthetic-api\n');(app/'.env').chmod(0o600)
 (app/'docker-compose.cloud.yml').write_text('{"original":"unchanged"}')
 sites=[tmp_path/'primary.site',tmp_path/'legacy.site']
 for site in sites:site.write_text((ROOT/'nginx-host-api.conf.example').read_text())
 backup=app/'database/backups/releases/manual-original';backup.mkdir(mode=0o700)
 calls=tmp_path/'calls.jsonl';rendered=tmp_path/'rendered.json'
 rendered.write_text(json.dumps({'services':{name:{'ports':[{'host_ip':'127.0.0.1','target':port}],
  # 2026-10-19 hoyeon.han: 렌더링된 합성 Compose도 office1으로 제한합니다.
  # 'environment':{'AUTH_ENV':'production','AUTH_PUBLIC_ORIGIN':'https://sollumeesthe.com','AUTH_ENCRYPTION_KEY':'synthetic-key'}}
  'environment':{'AUTH_ENV':'production','AUTH_PUBLIC_ORIGIN':'https://office1.sollumeesthe.com','AUTH_ENCRYPTION_KEY':'synthetic-key'}}
  for name,port in {'sollume-app':8501,'sollume-api':8502,'sollume-auth':8503}.items()}}))
 helper=app/'scripts/release_snapshot.py'
 helper.write_text('import json,os,pathlib,sys\nwith pathlib.Path(os.environ["MANUAL_QA_CALLS"]).open("a") as log:log.write(json.dumps(["helper",*sys.argv[1:]])+"\\n")\nprint(json.dumps({"dry_run":True,"validated":True}))\nraise SystemExit(int(os.environ.get("MANUAL_QA_HELPER_STATUS","17")))\n')
 # 2026-10-20 hoyeon.han: 공통 검사와 백업 준비 각각의 실패 순서를 실제 wrapper로 확인한다.
 (app/'scripts/deployment_preflight.py').write_text('import json,os,pathlib,sys\nwith pathlib.Path(os.environ["MANUAL_QA_CALLS"]).open("a") as log:log.write(json.dumps(["preflight",*sys.argv[1:]])+"\\n")\nprint(json.dumps({"runtime_transition_required":False}))\nraise SystemExit(int(os.environ.get("MANUAL_QA_PREFLIGHT_STATUS","0")))\n')
 tool='''#!PYTHON
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name
with pathlib.Path(os.environ['MANUAL_QA_CALLS']).open('a') as log:log.write(json.dumps([name,*sys.argv[1:]])+'\\n')
if name=='docker':
 if 'config' not in sys.argv:raise SystemExit(91)
 print(pathlib.Path(os.environ['MANUAL_QA_RENDERED']).read_text())
elif name=='curl':
 if '-o' not in sys.argv:raise SystemExit(92)
 shutil.copyfile(os.environ['MANUAL_QA_RENDERED'],sys.argv[sys.argv.index('-o')+1])
elif name=='sudo':
 if sys.argv[1:]!=['-n','nginx','-t']:raise SystemExit(93)
'''.replace('PYTHON',sys.executable)
 binary=tmp_path/'bin';binary.mkdir()
 for name in ('docker','curl','sudo'):
  target=binary/name;target.write_text(tool);target.chmod(0o700)
 env=dict(os.environ,PATH=str(binary)+':/usr/bin:/bin',SOLLUME_APP_DIR=str(app),SOLLUME_OPS_PYTHON=sys.executable,
  SOLLUME_NGINX_SITE_CONFIG=str(sites[0]),MANUAL_QA_CALLS=str(calls),MANUAL_QA_RENDERED=str(rendered))
 return app,backup,sites,calls,env


def test_deployment_manual_prepare_failure_prevents_pull_stop_run_up(tmp_path):
 app,backup,sites,calls,env=shell_fixture(tmp_path);helper=qa()
 before={str(path):helper.sha(path) for path in (app/'.env',app/'docker-compose.cloud.yml',app/'database/users.db',app/'database/customer_master.db',*sites)}
 result=subprocess.run(['bash',str(ROOT/'deploy-oracle.sh'),'--backup-dir',str(backup),
  '--nginx-config',str(sites[0]),'--nginx-config',str(sites[1])],env=env,capture_output=True,text=True,timeout=30)
 observed=[json.loads(row) for row in calls.read_text().splitlines()]
 preparation=[row for row in observed if row[:2]==['helper','manual-prepare']]
 assert result.returncode!=0 and len(preparation)==1 and '--check-current' in preparation[0]
 assert all(str(site) in preparation[0] for site in sites)
 assert not any(row[0]=='docker' and any(value in row for value in ('pull','up','down','stop','run','rm','load','save')) for row in observed)
 assert {str(path):helper.sha(path) for path in (app/'.env',app/'docker-compose.cloud.yml',app/'database/users.db',app/'database/customer_master.db',*sites)}==before
 assert stat.S_IMODE((app/'database/backups').stat().st_mode)==0o755
 assert '압축 백업 또는 현재 실행 상태 검증에 실패' in result.stderr


# 2026-10-20 hoyeon.han: 자동 snapshot과 압축 백업 모두 공통 검사 실패 뒤 외부 변경을 금지한다.
@pytest.mark.parametrize('manual_backup',[False,True])
def test_common_ingress_preflight_failure_prevents_both_backup_branches_and_pull(tmp_path,manual_backup):
 app,backup,sites,calls,env=shell_fixture(tmp_path);helper=qa()
 protected=(app/'.env',app/'docker-compose.cloud.yml',app/'database/users.db',app/'database/customer_master.db',*sites)
 before={str(path):helper.sha(path) for path in protected}
 env['MANUAL_QA_PREFLIGHT_STATUS']='19'
 args=['bash',str(ROOT/'deploy-oracle.sh'),'--nginx-config',str(sites[0]),'--nginx-config',str(sites[1])]
 if manual_backup:args+=['--backup-dir',str(backup)]
 result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=30)
 observed=[json.loads(row) for row in calls.read_text().splitlines()]
 assert result.returncode!=0 and '직접 포트 사전 검사 실패' in result.stderr
 preflight=[row for row in observed if row[0]=='preflight']
 assert len(preflight)==1 and preflight[0][1]=='ready'
 assert all(str(site) in preflight[0] for site in sites)
 assert not any(row[0]=='helper' for row in observed)
 assert not any(row[0]=='docker' and any(value in row for value in ('pull','up','down','stop','run','rm','load','save')) for row in observed)
 assert not any(row[0]=='sudo' and 'reload' in row for row in observed)
 assert {str(path):helper.sha(path) for path in protected}==before
 assert not list(app.glob('docker-compose.cloud.yml.preflight.*'))


# 2026-10-20 hoyeon.han: 실제 셸의 교체 직전 재검사·교체 후 검사·완료 메시지 순서를 확인한다.
@pytest.mark.parametrize('failure_stage',['second-ready','verify',None])
def test_deployment_rechecks_policy_and_runtime_before_reporting_success(tmp_path,failure_stage):
 app,backup,sites,calls,env=shell_fixture(tmp_path)
 for name in ('users.db','customer_master.db'):
  path=app/'database'/name;path.unlink()
  with sqlite3.connect(path) as conn:conn.execute('CREATE TABLE synthetic(value TEXT)')
 helper=qa();protected=(app/'.env',app/'database/users.db',app/'database/customer_master.db',*sites)
 before={str(path):helper.sha(path) for path in protected}
 (app/'scripts/release_snapshot.py').write_text(
  'import json,os,pathlib,sys\n'
  'with pathlib.Path(os.environ["MANUAL_QA_CALLS"]).open("a") as log:log.write(json.dumps(["helper",*sys.argv[1:]])+"\\n")\n'
  'print(json.dumps({"release":str(pathlib.Path(sys.argv[sys.argv.index("--backup-dir")+1]))}))\n')
 (app/'scripts/deployment_preflight.py').write_text(
  'import json,os,pathlib,sys\n'
  'log=pathlib.Path(os.environ["MANUAL_QA_CALLS"])\n'
  'previous=[json.loads(row) for row in log.read_text().splitlines()]\n'
  'with log.open("a") as stream:stream.write(json.dumps(["preflight",*sys.argv[1:]])+"\\n")\n'
  'phase=sys.argv[1]\n'
  'assert pathlib.Path(sys.argv[sys.argv.index("--compose-json")+1]).is_absolute()\n'
  'if "--baseline" in sys.argv:assert pathlib.Path(sys.argv[sys.argv.index("--baseline")+1]).is_absolute()\n'
  'second=any(row[:2]==["preflight","ready"] for row in previous)\n'
  'failure=os.environ.get("MANUAL_QA_FAILURE_STAGE","")\n'
  'print(json.dumps({"runtime_transition_required":True}))\n'
  'raise SystemExit(21 if (failure=="verify" and phase=="verify") or (failure=="second-ready" and phase=="ready" and second) else 0)\n')
 tool='''#!PYTHON
import json,os,pathlib,shutil,sys
name=pathlib.Path(sys.argv[0]).name
with pathlib.Path(os.environ['MANUAL_QA_CALLS']).open('a') as log:log.write(json.dumps([name,*sys.argv[1:]])+'\\n')
# if name=='docker' and 'config' in sys.argv:
#  print(pathlib.Path(os.environ['MANUAL_QA_RENDERED']).read_text())
# 2026-11-04 hoyeon.han: 현재 Compose 해석·후보 재해석과 받은 latest의 실제 ID를 구분한다.
if name=='docker':
 if 'config' in sys.argv:
  source=pathlib.Path(sys.argv[sys.argv.index('-f')+1]);config=json.loads(source.read_text())
  print(source.read_text() if 'services' in config else pathlib.Path(os.environ['MANUAL_QA_RENDERED']).read_text())
 elif sys.argv[1:3]==['image','inspect']:
  print('sha256:'+'a'*64 if sys.argv[sys.argv.index('--format')+1]=='{{.Id}}' else 'sha256:'+'a'*64+' linux arm64')
 elif sys.argv[1]=='info':print('linux aarch64')
elif name=='curl':
 if '--resolve' in sys.argv:
  print('403' if '/media/' in sys.argv[-1] else '401')
 elif '-o' in sys.argv:
  shutil.copyfile(os.environ['MANUAL_QA_RENDERED'],sys.argv[sys.argv.index('-o')+1])
'''.replace('PYTHON',sys.executable)
 for name in ('docker','curl','sudo'):(app.parent/'bin'/name).write_text(tool)
 env['MANUAL_QA_FAILURE_STAGE']=failure_stage or ''
 result=subprocess.run(['bash',str(ROOT/'deploy-oracle.sh'),'--backup-dir',str(backup),
  '--nginx-config',str(sites[0]),'--nginx-config',str(sites[1])],env=env,capture_output=True,text=True,timeout=30)
 observed=[json.loads(row) for row in calls.read_text().splitlines()]
 checks=[(index,row) for index,row in enumerate(observed) if row[0]=='preflight']
 assert [row[1] for _,row in checks][:2]==['ready','ready']
 assert '--baseline' not in checks[0][1] and '--baseline' in checks[1][1]
 pull=next(index for index,row in enumerate(observed) if row[0]=='docker' and 'pull' in row)
 assert checks[0][0]<pull<checks[1][0]
 renders=[index for index,row in enumerate(observed) if row[0]=='docker' and 'config' in row]
 # assert renders[0]<checks[0][0]<pull<renders[1]<checks[1][0]
 # 2026-11-04 hoyeon.han: 최초 운영 Compose 해석이 추가되지만 pull 이후 재검사는 필수다.
 assert renders[0]<checks[0][0]<pull
 assert any(pull<index<checks[1][0] for index in renders)
 if failure_stage=='second-ready':
  assert result.returncode!=0 and len(checks)==2
  assert not any(row[0]=='docker' and 'up' in row for row in observed)
 else:
  up=next(index for index,row in enumerate(observed) if row[0]=='docker' and 'up' in row)
  reload=next(index for index,row in enumerate(observed) if row[0]=='sudo' and 'reload' in row)
  assert len(checks)==3 and checks[2][1][1]=='verify' and '--baseline' in checks[2][1]
  assert checks[1][0]<up<reload<checks[2][0]
  # assert len(renders)==3 and reload<renders[2]<checks[2][0]
  # 2026-11-04 hoyeon.han: 운영 원본·최초 후보·교체 직전·적용 후 순서로 네 번 해석한다.
  assert len(renders)==4 and reload<renders[-1]<checks[2][0]
  assert (result.returncode==0)==(failure_stage is None)
 assert ('배포 및 기본 접근 차단 검증 완료' in result.stdout)==(failure_stage is None)
 assert {str(path):helper.sha(path) for path in protected}==before
 assert not list(app.glob('docker-compose.cloud.yml.preflight.*'))


def test_real_rollback_wrapper_dispatches_manual_backup_without_implicit_apply(tmp_path):
 app,backup,sites,calls,env=shell_fixture(tmp_path)
 wrapper=app/'rollback-oracle.sh';wrapper.write_bytes((ROOT/'rollback-oracle.sh').read_bytes())
 env['MANUAL_QA_HELPER_STATUS']='0'
 result=subprocess.run(['bash',str(wrapper),'--app-dir',str(app),'--backup-dir',str(backup),
  '--nginx-config',str(sites[0])],env=env,capture_output=True,text=True,timeout=30)
 observed=[json.loads(row) for row in calls.read_text().splitlines()]
 assert result.returncode==0 and len(observed)==1 and observed[0][:2]==['helper','manual-rollback']
 assert '--apply' not in observed[0]


def test_prepare_is_private_idempotent_and_references_immutable_original_image_archive(fixture):
 helper,value=fixture;runner=helper.RecordingRunner(value);before=value.archive_hashes()
 parent=value.app/'database/backups';parent.chmod(0o755)
 service=helper.manager(value,runner)
 first=service.prepare(check_current=True);second=service.prepare(check_current=True)
 release=Path(first['release']);secret=value.app/'database/.release-secrets'/release.name
 assert first['prepared'] and second['reused'] and second['release']==str(release)
 assert value.archive_hashes()==before and not (release/'images.tar').exists()
 assert release.parent==value.app/'database/backups/releases'
 assert stat.S_IMODE(parent.stat().st_mode)==0o755
 assert stat.S_IMODE(release.stat().st_mode)==stat.S_IMODE(secret.stat().st_mode)==0o700
 assert all(stat.S_IMODE(path.stat().st_mode)==0o600 for directory in (release,secret) for path in directory.iterdir() if path.is_file())
 assert stat.S_IMODE((value.backup/'manual-prepared.json').stat().st_mode)==0o600
 metadata=[path for path in release.iterdir() if path.suffix=='.json']
 assert all(not any(sensitive in path.read_text() for sensitive in value.sensitive) for path in metadata)
 compose=json.loads((release/'compose.json').read_text())
 for record in value.containers:
  name=record['Config']['Labels']['com.docker.compose.service'];saved=compose['services'][name]
  assert saved['image']==record['Image'] and saved['command']==record['Config']['Cmd'] and (saved['entrypoint'] or [])==(record['Config']['Entrypoint'] or [])
  assert saved['env_file'][0]['format']=='raw' and Path(saved['env_file'][0]['path']).is_relative_to(secret)
 assert not any(any(word in command for word in ('up','stop','rm','load','save','pull')) for command in runner.calls)


@pytest.mark.parametrize('field',['image','mount','command','entrypoint','environment','working_dir','user'])
def test_prepare_rejects_changed_current_runtime_before_mutations(fixture,field):
 helper,value=fixture;runner=helper.RecordingRunner(value);before=value.archive_hashes()
 current=value.containers[0]
 if field=='image':current['Image']='sha256:'+'f'*64
 elif field=='mount':current['Mounts'][0]['Source']=str(value.app/'wrong-source')
 elif field=='command':current['Config']['Cmd']=['changed-runtime-command']
 elif field=='entrypoint':current['Config']['Entrypoint']=['changed-entrypoint']
 elif field=='environment':current['Config']['Env'].append('EXTRA_CHANGED=1')
 elif field=='working_dir':current['Config']['WorkingDir']='/wrong-working-directory'
 elif field=='user':current['Config']['User']='123:456'
 with pytest.raises((ValueError,RuntimeError)):
  helper.manager(value,runner).prepare(check_current=True)
 assert value.archive_hashes()==before
 assert not (value.backup/'manual-prepared.json').exists()
 assert not any(any(word in command for word in ('up','stop','rm','load','save','pull')) for command in runner.calls)


def test_readonly_original_backup_can_be_planned_without_chmod_or_chown(fixture):
 helper,value=fixture;before=value.archive_hashes();value.backup.chmod(0o500)
 try:
  assert helper.manager(value,helper.RecordingRunner(value)).plan()['validated']
  with pytest.raises((OSError,ValueError)):
   helper.manager(value,helper.RecordingRunner(value)).prepare()
  assert stat.S_IMODE(value.backup.stat().st_mode)==0o500
  assert value.archive_hashes()==before and not (value.backup/'manual-prepared.json').exists()
 finally:value.backup.chmod(0o700)


def test_current_nonempty_sqlite_journal_rejected_without_modifying_original_database(fixture):
 helper,value=fixture;runner=helper.RecordingRunner(value);before=value.archive_hashes()
 database=value.app/'database/users.db';original=helper.sha(database)
 journal=Path(str(database)+'-journal');journal.write_bytes(b'synthetic live rollback journal')
 with pytest.raises(ValueError):helper.manager(value,runner).prepare(check_current=True)
 assert helper.sha(database)==original and journal.read_bytes()==b'synthetic live rollback journal'
 assert value.archive_hashes()==before and not (value.backup/'manual-prepared.json').exists()
 assert not any(any(word in command for word in ('up','stop','rm','load','save','pull')) for command in runner.calls)


@pytest.mark.parametrize('hidden',["server { listen 443 ssl; server_name sol-fin.duckdns.org; location / { proxy_pass \"http://127.0.0.1:8501\"; } }",
 'upstream hidden_backend { server 127.0.0.1:8501; } server { listen 443 ssl; server_name sol-fin.duckdns.org; location / { proxy_pass http://hidden_backend; } }',
 'server { listen 443 ssl; server_name sol-fin.duckdns.org; set $hidden http://127.0.0.1:8501; location / { proxy_pass $hidden; } }'])
def test_unlisted_quoted_alias_or_variable_nginx_accounting_route_is_rejected(fixture,hidden):
 helper,value=fixture;primary=value.root/'primary.site';extra=value.root/'unlisted.site'
 # 2026-10-19 hoyeon.han: 도메인 거절보다 누락된 proxy 탐지가 먼저 검증되도록 정상 office1을 사용합니다.
 # primary.write_text('server { listen 443 ssl; server_name sollumeesthe.com; location / { proxy_pass http://127.0.0.1:8501; } }')
 primary.write_text('server { listen 443 ssl; server_name office1.sollumeesthe.com; location / { proxy_pass http://127.0.0.1:8501; } }')
 extra.write_text(hidden);before={path:helper.sha(path) for path in (primary,extra)}
 class Runner(helper.RecordingRunner):
  def run(self,argv,**kwargs):
   if list(argv)==['sudo','-n','nginx','-T']:
    self.calls.append(list(argv));return '\n'.join('# configuration file '+str(path)+':\n'+path.read_text() for path in (primary,extra))
   return super().run(argv,**kwargs)
 runner=Runner(value);api=helper.release_api()
 with pytest.raises(ValueError):api.ManualBackupManager(value.app,value.backup,[primary],runner=runner)._blocked_sites(False)
 assert {path:helper.sha(path) for path in before}==before
 assert not any('reload' in command or 'stop' in command for command in runner.calls)


def test_shared_accounting_and_n8n_site_rejected_before_config_replacement(fixture):
 helper,value=fixture;site=value.root/'mixed.site'
 # 2026-10-19 hoyeon.han: office1과 다른 서비스가 혼합된 사이트는 계속 거절합니다.
 # site.write_text('server { listen 443 ssl; server_name sollumeesthe.com n8n.sollumeesthe.com; location / { proxy_pass http://127.0.0.1:8501; } }')
 site.write_text('server { listen 443 ssl; server_name office1.sollumeesthe.com n8n.sollumeesthe.com; location / { proxy_pass http://127.0.0.1:8501; } }')
 before=helper.sha(site)
 class Runner(helper.RecordingRunner):
  def run(self,argv,**kwargs):
   if list(argv)==['sudo','-n','nginx','-T']:
    self.calls.append(list(argv));return '# configuration file '+str(site)+':\n'+site.read_text()
   return super().run(argv,**kwargs)
 runner=Runner(value);api=helper.release_api()
 with pytest.raises(ValueError):api.ManualBackupManager(value.app,value.backup,[site],runner=runner)._blocked_sites(False)
 assert helper.sha(site)==before and not any('reload' in command for command in runner.calls)


def test_manual_rollback_preserves_only_fixed_office1_http_acme_path_and_other_service(fixture):
 """2026-10-19 hoyeon.han: 기존 임의 파일 경로는 복사하지 않고 office1 갱신 경로만 생성합니다."""
 helper,value=fixture;api=helper.release_api()
 office=value.root/'office1.site';legacy=value.root/'duckdns.site';other=value.root/'n8n.site'
 office.write_text('server { listen 80; server_name office1.sollumeesthe.com; '
  'location /old { alias /private/old-data; } location / { return 301 https://office1.sollumeesthe.com$request_uri; } }\n'
  'server { listen 443 ssl; server_name office1.sollumeesthe.com; '
  'ssl_certificate /certificate.pem; ssl_certificate_key /private.pem; '
  'location / { proxy_pass http://127.0.0.1:8501; } }')
 legacy.write_text('server { listen 80; server_name sol-fin.duckdns.org; '
  'location / { proxy_pass http://127.0.0.1:8501; } }')
 other.write_text('server { listen 443 ssl; server_name sollume-n8n.duckdns.org; '
  'location / { proxy_pass http://127.0.0.1:5678; } }');untouched=other.read_bytes()
 class Runner:
  def __init__(self):self.calls=[]
  def run(self,argv,**kwargs):
   self.calls.append(list(argv))
   if list(argv)==['sudo','-n','nginx','-T']:
    return '\n'.join('# configuration file '+str(path)+':\n'+path.read_text() for path in (office,legacy,other))
   assert list(argv) in (['sudo','-n','nginx','-t'],['sudo','-n','systemctl','reload','nginx'])
   return ''
 runner=Runner();service=api.ManualBackupManager(value.app,value.backup,[office,legacy],runner=runner)
 plans=service._blocked_sites(True);rendered=office.read_text();blocked_legacy=legacy.read_text()
 assert rendered.count('root /var/www/letsencrypt;')==1
 assert 'location ^~ /.well-known/acme-challenge/' in rendered and 'try_files $uri =404;' in rendered
 assert rendered.count('return 503;')==2 and 'location / { add_header Cache-Control no-store always; return 503;' in rendered
 assert not any(token in rendered for token in ('/private/old-data','alias ','proxy_pass','return 301','default_server'))
 assert 'acme-challenge' not in blocked_legacy and 'return 503;' in blocked_legacy
 assert other.read_bytes()==untouched
 assert ('office1.sollumeesthe.com' in plans[0][0] and ['80'] in plans[0][1])


@pytest.mark.parametrize('hostnames',['sollumeesthe.com','office1.sollumeesthe.com sollumeesthe.com',
 'office1.sollumeesthe.com sol-fin.duckdns.org'])
def test_root_domain_or_mixed_office1_acme_server_is_rejected_before_write(fixture,hostnames):
 """2026-10-19 hoyeon.han: 루트 사이트는 복구 대상이 아니며 ACME 예외를 다른 도메인에 확장하지 않습니다."""
 helper,value=fixture;api=helper.release_api();site=value.root/'rejected.site'
 site.write_text('server { listen 80; server_name '+hostnames+'; location / { proxy_pass http://127.0.0.1:8501; } }')
 before=site.read_bytes()
 class Runner:
  def __init__(self):self.calls=[]
  def run(self,argv,**kwargs):
   self.calls.append(list(argv));assert list(argv)==['sudo','-n','nginx','-T']
   return '# configuration file '+str(site)+':\n'+site.read_text()
 runner=Runner();service=api.ManualBackupManager(value.app,value.backup,[site],runner=runner)
 with pytest.raises(api.SafetyError):service._blocked_sites(True)
 assert site.read_bytes()==before and len(runner.calls)==1


def test_manual_user_merge_keeps_added_accounts_inactive_and_revoked_states(fixture):
 helper,value=fixture;api=helper.release_api();service=api.ManualBackupManager(value.app,value.backup,runner=helper.RecordingRunner(value))
 release=Path(service.prepare()['release']);database=value.app/'database/users.db'
 connection=sqlite3.connect(database)
 try:
  connection.execute('UPDATE users SET password_hash=? WHERE id=42',('synthetic-new-encoded-password',))
  connection.execute('UPDATE users SET is_admin=0 WHERE id=77')
  connection.execute('UPDATE users SET is_active=0 WHERE id=99')
  connection.execute('DELETE FROM users WHERE id=105')
  connection.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?,?,?,?)',(111,'added','new-encoded-password','추가 직원','added@example.invalid',1,1,'2026-10-19',None,0));connection.commit()
 finally:connection.close()
 latest=value.root/'latest-users.db';api._sqlite_backup(database,latest);latest_before=helper.sha(latest)
 Path(str(database)+'-wal').unlink(missing_ok=True)
 required=service._restore_manual_users(release,latest)
 connection=sqlite3.connect(database)
 try:rows={row[0]:row[1:] for row in connection.execute('SELECT id,username,is_active,is_admin,password_hash FROM users')}
 finally:connection.close()
 assert rows[111][:3]==('added',0,0) and rows[43][1]==1 and rows[77][1:3]==(1,0)
 assert all(rows[identifier][1]==0 for identifier in (42,99,105))
 assert 42 in required and 111 in required and 99 not in required
 assert helper.sha(latest)==latest_before


@pytest.mark.parametrize('collision',['same_id_new_name','same_name_new_id'])
def test_manual_user_identity_collision_rejected_before_database_replacement(fixture,collision):
 helper,value=fixture;api=helper.release_api();service=api.ManualBackupManager(value.app,value.backup,runner=helper.RecordingRunner(value))
 release=Path(service.prepare()['release']);database=value.app/'database/users.db'
 connection=sqlite3.connect(database)
 try:
  if collision=='same_id_new_name':connection.execute('UPDATE users SET username=? WHERE id=42',('different-account',))
  else:connection.execute('UPDATE users SET id=111 WHERE username=?',('changed',))
  connection.commit()
 finally:connection.close()
 latest=value.root/'latest-users.db';api._sqlite_backup(database,latest);before=helper.sha(database)
 with pytest.raises(ValueError):service._restore_manual_users(release,latest)
 assert helper.sha(database)==before


def test_prepared_compose_passes_actual_local_compose_schema_without_starting_services(fixture):
 import shutil
 if shutil.which('docker') is None:pytest.skip('로컬 Docker CLI가 없어 실제 Compose 파서는 확인할 수 없습니다.')
 helper,value=fixture;prepared=helper.manager(value,helper.RecordingRunner(value)).prepare()
 result=subprocess.run(['docker','compose','--project-directory',str(value.app),'--env-file',str(value.app/'.env'),
  '--project-name',value.project,'--file',str(Path(prepared['release'])/'compose.json'),'config','--format','json'],
  capture_output=True,text=True,timeout=30)
 assert result.returncode==0,'합성prepared Compose의실제CLI schema검증실패(비밀로그출력생략)'
 rendered=json.loads(result.stdout)
 assert set(rendered['services'])=={'sollume-app','sollume-api'}
