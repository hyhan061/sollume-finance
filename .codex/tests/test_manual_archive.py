"""2026-10-19 hoyeon.han: 수동 백업 3파일의 안전 파싱·사전 차단·실제 격리 복구 검증."""
from __future__ import annotations
import copy,importlib.util,json,os,stat,subprocess,sys,tarfile,sqlite3
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]

def qa():
 spec=importlib.util.spec_from_file_location('manual_archive_qa',ROOT/'.codex/user-management/verify_manual_archive.py')
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
 (app/'.env').write_text('AUTH_ENV=production\nAUTH_PUBLIC_ORIGIN=https://sollumeesthe.com\nAUTH_ENCRYPTION_KEY=synthetic-not-an-operational-key\nORDER_API_KEY=synthetic-api\n');(app/'.env').chmod(0o600)
 (app/'docker-compose.cloud.yml').write_text('{"original":"unchanged"}')
 sites=[tmp_path/'primary.site',tmp_path/'legacy.site']
 for site in sites:site.write_text((ROOT/'nginx-host-api.conf.example').read_text())
 backup=app/'database/backups/releases/manual-original';backup.mkdir(mode=0o700)
 calls=tmp_path/'calls.jsonl';rendered=tmp_path/'rendered.json'
 rendered.write_text(json.dumps({'services':{name:{'ports':[{'host_ip':'127.0.0.1','target':port}],
  'environment':{'AUTH_ENV':'production','AUTH_PUBLIC_ORIGIN':'https://sollumeesthe.com','AUTH_ENCRYPTION_KEY':'synthetic-key'}}
  for name,port in {'sollume-app':8501,'sollume-api':8502,'sollume-auth':8503}.items()}}))
 helper=app/'scripts/release_snapshot.py'
 helper.write_text('import json,os,pathlib,sys\nwith pathlib.Path(os.environ["MANUAL_QA_CALLS"]).open("a") as log:log.write(json.dumps(["helper",*sys.argv[1:]])+"\\n")\nprint(json.dumps({"dry_run":True,"validated":True}))\nraise SystemExit(int(os.environ.get("MANUAL_QA_HELPER_STATUS","17")))\n')
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
 primary.write_text('server { listen 443 ssl; server_name sollumeesthe.com; location / { proxy_pass http://127.0.0.1:8501; } }')
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
 site.write_text('server { listen 443 ssl; server_name sollumeesthe.com n8n.sollumeesthe.com; location / { proxy_pass http://127.0.0.1:8501; } }')
 before=helper.sha(site)
 class Runner(helper.RecordingRunner):
  def run(self,argv,**kwargs):
   if list(argv)==['sudo','-n','nginx','-T']:
    self.calls.append(list(argv));return '# configuration file '+str(site)+':\n'+site.read_text()
   return super().run(argv,**kwargs)
 runner=Runner(value);api=helper.release_api()
 with pytest.raises(ValueError):api.ManualBackupManager(value.app,value.backup,[site],runner=runner)._blocked_sites(False)
 assert helper.sha(site)==before and not any('reload' in command for command in runner.calls)


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
