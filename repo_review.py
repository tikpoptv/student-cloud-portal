"""Bounded read-only GitHub analysis and conservative Lab 5 starter-kit edits.
Repository text is data. No repository code, shell, Git hooks or AI instructions run here.
"""
import concurrent.futures
import difflib
import hashlib
import io
import logging
import os
import re
import time
import zipfile
from urllib.parse import urlparse
import requests
from flask import current_app, has_app_context

PATHS=('deploy/deploy.sh','deploy/release.sh','deploy/teardown.sh',
       '.github/workflows/deploy.yml','.github/workflows/ci-docker.yml',
       'deploy/smoke_test.py','deploy/tests/test_deploy_stub.sh',
       'deploy/tests/test_release_stub.sh','Dockerfile')
REPO_RE=re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}')
FETCH_DEADLINE=45
MAX_SCAN_BYTES=200000  # per file; inputs are already capped at 150000 when fetched
GITHUB_AUTH_FAILED='ระบบอ่าน GitHub ไม่ได้ชั่วคราวเพราะการยืนยันตัวตนของระบบหมดอายุ ไม่ใช่ความผิดของกลุ่ม กรุณาแจ้ง TA'
GITHUB_UNAVAILABLE='GitHub ขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้งในอีกสักครู่'
# Bounded quantifiers keep the scan linear: an unbounded `[^\s@]+` rescans to the end of the text from every
# `mysql://a:` start (O(n^2); a 150 KB adversarial file took ~13 s).
CREDENTIAL_URL=re.compile(r'(?:postgres(?:ql)?|mysql)://([^\s:/@]{1,128}):([^\s@]{1,512})@')


def _log():
    return current_app.logger if has_app_context() else logging.getLogger(__name__)


GITHUB_URL_RE=re.compile(r'(?:(?:https?://)?(?:www\.)?github\.com[/:]|git@github\.com:)(.*)',re.IGNORECASE|re.DOTALL)


def normalize_repo(value):
    """Accept owner/repo or a pasted GitHub link (github.com/o/r, https://www.github.com/o/r/tree/main, git@github.com:o/r.git).
    Only github.com is accepted; any other host, or odd characters, is rejected."""
    if not isinstance(value,str):raise ValueError('กรุณาใส่ลิงก์ GitHub repo')
    repo=value.strip()
    link=GITHUB_URL_RE.fullmatch(repo)
    if link:
        # a pasted link may carry a query, fragment or extra path (/tree/main, /issues); keep owner/repo only
        parts=re.split(r'[?#]',link.group(1),maxsplit=1)[0].split('/')
        repo='/'.join(parts[:2])
    repo=repo.removesuffix('/').removesuffix('.git')
    if not REPO_RE.fullmatch(repo) or any(part in ('.','..') for part in repo.split('/')):
        raise ValueError('ใช้ public GitHub repository รูปแบบ owner/repository เท่านั้น')
    return repo


def _auth_headers(url):
    """Optional token is sent to api.github.com only, never to raw hosts or redirects."""
    token=os.environ.get('GITHUB_API_TOKEN','').strip()
    parts=urlparse(url)
    if token and parts.scheme=='https' and parts.hostname=='api.github.com':
        return {'Authorization':'Bearer '+token}
    return {}


def _check_deadline(deadline):
    if deadline is not None and time.monotonic()>deadline:
        raise ValueError('GitHub ตอบช้าเกินเวลาที่กำหนด กรุณาลองใหม่อีกครั้ง')


def get_bytes(url,limit,accept='application/vnd.github+json',meta=False,deadline=None):
    _check_deadline(deadline)
    headers={'Accept':accept,'User-Agent':'CPE334-Student-Portal',**_auth_headers(url)}
    with requests.get(url,timeout=(5,20),stream=True,allow_redirects=False,headers=headers) as res:
        code=res.status_code
        if code==404:return None
        if code in (301,302,307,308):
            raise ValueError('repo นี้ถูกย้ายหรือเปลี่ยนชื่อ กรุณาใช้ลิงก์ repo ปัจจุบันจาก GitHub')
        if code==429 or (code==403 and (res.headers.get('X-RateLimit-Remaining')=='0' or 'Retry-After' in res.headers)):
            raise ValueError('GitHub จำกัดการอ่านชั่วคราว กรุณารอสักครู่แล้วลองใหม่')
        if code==401:
            # Our own GITHUB_API_TOKEN is bad or expired: not the student's fault and not a rate limit. Never log the token.
            _log().warning('GitHub returned 401 for %s: GITHUB_API_TOKEN is invalid or expired',urlparse(url).hostname)
            raise ValueError(GITHUB_AUTH_FAILED)
        if code==403:raise ValueError('GitHub ไม่อนุญาตให้อ่าน repo นี้ ตรวจว่าเป็น public repo ที่เข้าถึงได้')
        if code>=500:
            _log().warning('GitHub returned %s for %s',code,urlparse(url).hostname)
            raise ValueError(GITHUB_UNAVAILABLE)
        if code!=200:raise ValueError('อ่าน GitHub ไม่สำเร็จ ยังไม่มีการแก้ไข repo')
        chunks=[];size=0
        for chunk in res.iter_content(16384):
            _check_deadline(deadline)
            size+=len(chunk)
            if size>limit:
                raise ValueError('อ่านข้อมูล commit จาก GitHub ไม่สำเร็จ ลองใหม่อีกครั้ง' if meta
                                 else 'ไฟล์ใหญ่เกินขอบเขตตรวจอัตโนมัติ ให้ TA ตรวจแทน')
            chunks.append(chunk)
        _check_deadline(deadline)
        return b''.join(chunks)


def fetch_snapshot(repo):
    repo=normalize_repo(repo)
    deadline=time.monotonic()+FETCH_DEADLINE
    # The sha media type returns only the 40-hex SHA, not the (possibly huge) commit details.
    meta=get_bytes(f'https://api.github.com/repos/{repo}/commits/main',4096,
                   accept='application/vnd.github.sha',meta=True,deadline=deadline)
    if meta is None:raise ValueError('ไม่พบ public repo หรือ branch main ตาม Lab 5')
    sha=meta.decode('ascii','replace').strip()
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('ยืนยัน Git commit ไม่สำเร็จ')
    def fetch(path):
        data=get_bytes(f'https://raw.githubusercontent.com/{repo}/{sha}/{path}',150000,deadline=deadline)
        if data is None:return path,None
        try:return path,data.decode('utf-8')
        except UnicodeDecodeError:raise ValueError('พบไฟล์ที่อ่านเป็นข้อความไม่ได้ ให้ TA ตรวจแทน')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        files={p:text for p,text in pool.map(fetch,PATHS) if text is not None}
    return sha,files


def literal(script,key):
    m=re.search(r'^'+re.escape(key)+r'="([a-z][a-z0-9-]{1,60})"\s*$',script,re.M)
    if not m:raise ValueError(f'อ่านค่า {key} จาก deploy/deploy.sh ไม่ได้ ต้องให้กลุ่ม/TA ตรวจ')
    return m.group(1)


def inspect_files(repo,sha,files,prefix,preview=True):
    if not re.fullmatch('[a-z][a-z0-9]{2,9}',prefix):raise ValueError('Invalid assigned prefix')
    for path,text in files.items():
        if path == '.github/workflows/ci-docker.yml':
            continue  # CI is neither changed nor returned; its localhost fixture is not a cloud credential.
        if len(text)>MAX_SCAN_BYTES:raise ValueError('ไฟล์ใหญ่เกินขอบเขตตรวจอัตโนมัติ ให้ TA ตรวจแทน')
        urls=CREDENTIAL_URL.findall(text)
        if 'PRIVATE KEY-----' in text or any('$' not in user+password for user,password in urls):
            raise ValueError('พบรูปแบบ credential ในไฟล์ deploy ให้กลุ่มตรวจและปิดข้อมูลก่อน ระบบยังไม่แสดง diff')
    report={'repo':repo,'source_sha':sha,'prefix':prefix,'preview':preview,'status':'needs_review',
            'changes':[],'warnings':[],'findings':[], 'ci_changed':False,'github_write':False,
            'summary':'ตรวจจากไฟล์เท่านั้น ยังไม่ได้รันแอป เทส หรือ deploy'}
    missing=[p for p in ('deploy/deploy.sh','deploy/release.sh','.github/workflows/deploy.yml','.github/workflows/ci-docker.yml','deploy/smoke_test.py','Dockerfile') if p not in files]
    if missing:
        report['warnings'].append('ยังไม่พบไฟล์ตามโครงสร้าง Starter Kit: '+', '.join(missing))
        return report
    try:
        original=files['deploy/deploy.sh']
        if original.count('set -euo pipefail\n') != 1:raise ValueError('ไม่พบ shell error guard ตาม Starter Kit')
        # Only adapt the documented kit sections; unfamiliar layouts remain read-only.
        first=original.index('# 1. Enable required GCP APIs')
        build=original.index('# 9. Build & Push Unified Container Image via Cloud Build')
        start=first
        tailstart=build
        if min(start,tailstart)<0 or tailstart<=start:raise ValueError('Section boundaries not recognized')
        base=literal(original,'SERVICE_NAME')
        for key,suffix in [('REPO_NAME',''),('SQL_INSTANCE','-pg'),('DB_NAME',''),('DB_USER',''),('MIGRATE_JOB_NAME','-migrate'),('SA_NAME','-runner'),('SECRET_DB_URL','-database-url'),('SECRET_ADMIN_PASS','-admin-password'),('SECRET_DEMO_PASS','-demo-password')]:
            if literal(original,key)!=base+suffix:raise ValueError(f'{key} ไม่ได้ใช้รูปแบบชื่อเดียวกับ Starter Kit ต้องยืนยันกับ TA')
        tail=original[tailstart:]
        build_pattern=r'run_cmd gcloud builds submit \\\n  --tag "\$IMAGE_URI" \\\n  --project "\$PROJECT_ID"'
        if len(re.findall(build_pattern,tail))!=1:raise ValueError('Build command ต่างจากตัวอย่าง ต้องให้กลุ่มตรวจ Dockerfile/context')
        if tail.count('run_cmd gcloud run jobs deploy "$MIGRATE_JOB_NAME"')!=1 or tail.count('run_cmd gcloud run deploy "$SERVICE_NAME"')!=1:raise ValueError('ไม่พบ job/service deploy ที่ปรับอย่างปลอดภัยได้')
        if tail.count('  --platform managed \\\n')!=1 or tail.count('  --allow-unauthenticated \\\n')!=1:raise ValueError('Public-access flags ต่างจาก Starter Kit ต้องให้ TA ตรวจ')
        # Preserve the student's actual stack settings, command, seed and env mappings.
        facts={}
        for key,pattern in [('port',r'--port\s+(\d+)'),('migration',r'--args\s+"([^"\n]+)"'),('command',r'--command\s+"([^"\n]+)"'),('job_env',r'--set-env-vars\s+"([^"\n]+)"')]:
            matches=re.findall(pattern,tail)
            if not matches:raise ValueError(f'อ่าน {key} ไม่ได้ ต้องให้กลุ่มตรวจตาม stack')
            facts[key]=matches[0]
        report['findings']=[{'name':'Port เดิม','value':facts['port']},{'name':'Migration executable เดิม','value':facts['command']},{'name':'Migration/seed เดิม','value':facts['migration']}]
        pre=original[:start]
        # Remove active gcloud project discovery; explicit course project always wins.
        project_start=pre.index('if [ "$DRY_RUN" = "1" ]; then\n  PROJECT_ID=')
        resource_start=pre.index('REPO_NAME=',project_start)
        pre=pre[:project_start]+'''# Shared course project: no project discovery or project IAM changes.
PROJECT_ID="${PROJECT_ID:-cpe-se-course-2026}"
[[ "$PROJECT_ID" == "cpe-se-course-2026" ]] || { echo 'Wrong course project' >&2; exit 1; }
REGION="${REGION:-asia-southeast1}"
[[ "$REGION" == "asia-southeast1" ]] || { echo 'Wrong assigned region' >&2; exit 1; }
'''+pre[resource_start:]
        pre=pre.replace('DRY_RUN="${DRY_RUN:-0}"','DRY_RUN="${DRY_RUN:-1}"')
        # Reject a different original default region rather than keeping two competing definitions.
        pre=re.sub(r'^REGION="\$\{REGION:-[^}]+\}"$', 'REGION="${REGION:-asia-southeast1}"',pre,flags=re.M)
        pre=pre.replace('IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"','''if [ "$DRY_RUN" = "1" ]; then
  IMAGE_TAG="${IMAGE_TAG:-0000000000000000000000000000000000000000}"
else
  IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse HEAD)}"
  [[ "$(git branch --show-current)" == "main" ]] || { echo 'Deploy reviewed main only' >&2; exit 1; }
  [[ "$IMAGE_TAG" == "$(git rev-parse HEAD)" ]] || { echo 'IMAGE_TAG must match HEAD' >&2; exit 1; }
fi
[[ "$IMAGE_TAG" =~ ^[0-9a-f]{40}$ ]] || { echo 'Use full commit SHA' >&2; exit 1; }
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:${IMAGE_TAG}"''')
        if ':latest"' in next((x for x in pre.splitlines() if x.startswith('IMAGE_URI=')),''):raise ValueError('Image setting not recognized')
        jobbase=re.search(r'^JOB_SECRETS="([^"\n]+)"$',original,re.M)
        if not jobbase or jobbase.group(1)!='DATABASE_URL=${SECRET_DB_URL}:latest,ADMIN_PASSWORD=${SECRET_ADMIN_PASS}:latest':raise ValueError('Secret mappings ต่างจากตัวอย่าง ต้องให้ TA จัด secrets ให้ตรงก่อน')
        setup='''# Portal/TA pre-provisions infrastructure and public service IAM (Guide 5.3 steps 1–8, 5.4).
# These names must exist. Never create or modify project-level IAM here.
JOB_SECRETS="DATABASE_URL=${SECRET_DB_URL}:latest,ADMIN_PASSWORD=${SECRET_ADMIN_PASS}:latest"
if [ "$SEED_DEMO_DATA" = "true" ]; then
  JOB_SECRETS="${JOB_SECRETS},DEMO_USER_PASSWORD=${SECRET_DEMO_PASS}:latest"
fi
if [ "$DRY_RUN" != "1" ]; then
  gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" --region "$REGION" >/dev/null
  gcloud run jobs describe "$MIGRATE_JOB_NAME" --project "$PROJECT_ID" --region "$REGION" >/dev/null
fi
'''
        docker='''run_cmd gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
run_cmd docker build --platform linux/amd64 --tag "$IMAGE_URI" .
run_cmd docker push "$IMAGE_URI"
if [ "$DRY_RUN" != "1" ]; then
  IMAGE_URI="$(gcloud artifacts docker images describe "$IMAGE_URI" --project "$PROJECT_ID" --format='value(image_summary.fully_qualified_digest)')"
  [[ "$IMAGE_URI" == "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}@sha256:"* ]] || { echo 'Missing image digest' >&2; exit 1; }
fi'''
        tail=re.sub(build_pattern,lambda _:docker,tail)
        tail=tail.replace('run_cmd gcloud run jobs deploy "$MIGRATE_JOB_NAME"','run_cmd gcloud run jobs update "$MIGRATE_JOB_NAME"')
        tail=tail.replace('  --max-instances 3', '  --max-instances 1')
        tail=tail.replace('run_cmd gcloud run deploy "$SERVICE_NAME"','run_cmd gcloud run services update "$SERVICE_NAME"')
        tail=tail.replace('  --platform managed \\\n','').replace('  --allow-unauthenticated \\\n','')
        tail=tail.replace('if [ "$DRY_RUN" = "1" ]; then\n  SERVICE_URL=', '''run_cmd gcloud run services update-traffic "$SERVICE_NAME" --to-latest --project "$PROJECT_ID" --region "$REGION" --quiet
if [ "$DRY_RUN" = "1" ]; then
  SERVICE_URL=''')
        candidate=pre+setup+tail
        # The preview artifact must not accidentally be executable against paid resources.
        previewguard='''# PORTAL PREVIEW: this proposal has no real infrastructure behind it.
if [ "${DRY_RUN:-1}" != "1" ]; then
  echo 'STOP: preview proposal; request a live proposal after TA activation.' >&2
  exit 1
fi
'''
        if preview:candidate=candidate.replace('set -euo pipefail\n','set -euo pipefail\n'+previewguard,1)
        def rename(text):return re.sub(re.escape(base)+r'(?=[/\-:@"\s}]|$)',prefix,text)
        candidate=rename(candidate)
        # Keep immutable-commit digest validation and main/reusable-test gates in the existing CD.
        workflow=files['.github/workflows/deploy.yml'];release=files['deploy/release.sh']
        for marker in ('needs: test','uses: ./.github/workflows/ci-docker.yml','environment: demo','cancel-in-progress: false','id-token: write','vars.GCP_PROJECT_ID','vars.GCP_REGION','bash deploy/release.sh'):
            if marker not in workflow:raise ValueError('Deployment workflow ต่างจาก Starter Kit: '+marker)
        for marker in ('set -euo pipefail','gcloud run jobs execute','--wait','--to-latest','fully_qualified_digest'):
            if marker not in release:raise ValueError('release.sh ต่างจาก Starter Kit: '+marker)
        newworkflow=rename(workflow);newrelease=rename(release)
        guard='''      - name: Verify course handoff readiness
        run: |
          echo 'STOP: preview proposal. TA must activate real resources and issue a live proposal first.' >&2
          exit 1
'''
        if preview:
            if newworkflow.count('      - uses: actions/checkout@')!=1:raise ValueError('ตำแหน่ง checkout ต่างจาก Starter Kit ต้องให้ TA ตรวจ')
            newworkflow=newworkflow.replace('      - uses: actions/checkout@',guard+'      - uses: actions/checkout@',1)
        updated={'deploy/deploy.sh':candidate,'deploy/release.sh':newrelease,'.github/workflows/deploy.yml':newworkflow}
        if 'deploy/teardown.sh' in files:
            updated['deploy/teardown.sh']='''#!/usr/bin/env bash
set -euo pipefail
echo 'Shared course project: request pause/cleanup from TA; do not run the original teardown.' >&2
exit 1
'''
        # Old deployment tests expected infrastructure creation. Replace only that test, retain release/smoke/CI tests.
        if 'deploy/tests/test_deploy_stub.sh' in files:updated['deploy/tests/test_deploy_stub.sh']=offline_test()
        if 'deploy/tests/test_release_stub.sh' in files:updated['deploy/tests/test_release_stub.sh']=rename(files['deploy/tests/test_release_stub.sh'])
        if re.search(r'gcloud (services enable|sql |iam |secrets (create|versions add|add-iam))|--allow-unauthenticated', '\n'.join(x for x in candidate.splitlines() if not x.lstrip().startswith('#'))):raise ValueError('ยังมีคำสั่ง provision ที่ต้องให้ TA ตรวจ')
        for path,after in updated.items():
            before=files[path]
            if before==after:continue
            diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+path,tofile='b/'+path))
            report['changes'].append({'path':path,'diff':diff,'before':before,'after':after,
                'source_hash':hashlib.sha256(before.encode()).hexdigest()})
        report['status']='prepared'
        report['warnings']=['ตรวจยืนยัน port, migration/seed, env และ smoke test ว่าตรงแอปจริงก่อน merge',
            'ระบบเก็บคำสั่ง migration/port เดิม ไม่ได้รันโค้ดหรือยืนยันว่าแอปทำงานได้',
            'Portal/TA ต้องเตรียม admin-password และ demo-password (เมื่อใช้ --demo) ให้ตรงกับไฟล์เดิม',
            'ไม่แก้ ci-docker.yml และไม่เพิ่ม course-app.json หรือ config ใหม่']
        if preview:report['warnings'].insert(0,'ข้อเสนอโหมดทดลอง: deploy จริงและ CD ถูกบล็อก ต้องออกข้อเสนอ live ใหม่หลัง TA เปิดทรัพยากร')
        return report
    except (ValueError,KeyError) as err:
        report['changes']=[];report['warnings'].append(str(err));return report


def offline_test():
    return '''#!/usr/bin/env bash
# Shared-project adaptation: original CI still invokes this existing test path.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
for executable in gcloud docker; do
  printf '%s\\n' '#!/usr/bin/env bash' 'echo "Unexpected cloud/build call" >&2; exit 99' > "$tmp/bin/$executable"
  chmod +x "$tmp/bin/$executable"
done
PATH="$tmp/bin:$PATH" DRY_RUN=1 bash "$ROOT/deploy/deploy.sh" > "$tmp/plan"
grep -q '\\[DRY_RUN\\]' "$tmp/plan"
if grep -E '^\\[DRY_RUN\\].*(services enable|sql instances create|add-iam-policy-binding|secrets create)' "$tmp/plan"; then
  echo 'Forbidden infrastructure command in plan' >&2; exit 1
fi
grep -q 'docker build' "$tmp/plan"
grep -q 'run jobs update' "$tmp/plan"
grep -q 'run services update' "$tmp/plan"
echo 'Shared-project deploy dry-run: PASS (no cloud or Docker execution)'
'''


def patch_bytes(report):
    return ''.join(c['diff'] for c in report['changes']).encode()


def zip_review(report):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('lab5-'+report['prefix']+'.patch',patch_bytes(report))
        z.writestr('REVIEW.md',f"# Lab 5 proposal\nRepo: {report['repo']}\nSource main SHA: {report['source_sha']}\nPreview: {report['preview']}\n\nReview the diff in the portal, run git apply --check, and ask a teammate to review the PR from staging to main as described in the guide.\nNo new configuration file is added. Ports and migrations follow your existing files.\n\nตรวจ diff ในเว็บ ใช้ git apply --check ก่อน และให้เพื่อน review PR เข้า staging → main ตามไกด์\nไม่เพิ่ม config ใหม่; พอร์ตและ migration ยึดไฟล์เดิม\n")
        for change in report['changes']:z.writestr('patched-files/'+change['path'],change['after'])
    stream.seek(0);return stream


LAB5_KIT_PATHS=('deploy/deploy.sh','deploy/release.sh','.github/workflows/deploy.yml')
LAB5_KIT_EXECUTABLE={'deploy/deploy.sh','deploy/release.sh'}


def lab5_kit_files(prefix,project,region,ref_dir):
    """Pristine Starter Kit scripts adapted for one team by the same adapter as the patch flow.
    Files we do not ship are neutral stand-ins only needed to satisfy the adapter's layout check.
    Returns {path: text}; raises ValueError if the adapter cannot adapt the pristine kit."""
    ref_dir=os.fspath(ref_dir)
    names={'deploy/deploy.sh':'deploy.sh','deploy/release.sh':'release.sh','.github/workflows/deploy.yml':'deploy.yml'}
    files={}
    for path,name in names.items():
        with open(os.path.join(ref_dir,name),encoding='utf-8') as f:files[path]=f.read()
    files.update({'.github/workflows/ci-docker.yml':'name: CI\n','deploy/smoke_test.py':'# stand-in\n','Dockerfile':'FROM scratch\n'})
    report=inspect_files('course/starter-kit','0'*40,files,prefix,preview=False)
    if report['status']!='prepared':raise ValueError('; '.join(report['warnings']))
    after={c['path']:c['after'] for c in report['changes']}
    out={p:after.get(p,files[p]) for p in LAB5_KIT_PATHS}
    readme=open(os.path.join(ref_dir,'README-LAB5.template.md'),encoding='utf-8').read()
    out['README-LAB5.md']=readme.replace('{{PREFIX}}',prefix).replace('{{PROJECT}}',project).replace('{{REGION}}',region)
    return out


def zip_lab5_kit(prefix,project,region,ref_dir):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for path,text in lab5_kit_files(prefix,project,region,ref_dir).items():
            info=zipfile.ZipInfo('lab5-starter-kit-'+prefix+'/'+path,(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            info.create_system=3  # Unix: required for the mode bits below to be honoured
            # Regular-file type bits (S_IFREG) are required or Finder/Archive Utility drops the exec bit.
            info.external_attr=(0o100755 if path in LAB5_KIT_EXECUTABLE else 0o100644)<<16
            z.writestr(info,text)
    return stream.getvalue()
