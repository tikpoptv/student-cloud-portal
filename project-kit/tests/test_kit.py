"""Offline tests for kit.sh / from-portal-json.sh (no real gcloud/docker calls).
ทดสอบแบบออฟไลน์ ทั้งข้อความภาษาอังกฤษ (ค่าเริ่มต้น) และภาษาไทย
Run:  python3 -m unittest discover -s project-kit/tests -v
"""
import json, os, re, stat, subprocess, tempfile, unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
KITSH = str(KIT / "kit.sh")
CONVERT = str(KIT / "from-portal-json.sh")
SECRET_VALUE = "SUPERSECRETVALUE-9f3a"

RESOURCES = """PROJECT_ID=cpe-se-course-2026
REGION=asia-southeast1
PREFIX=grp01
STACK=python
PORT=8000
MIGRATE_COMMAND=alembic upgrade head
"""
APP_ENV = "NODE_ENV=production\nTZ=Asia/Bangkok\nGREETING=hello, world\n"
SECRETS_MAP = "ADMIN_PASSWORD=grp01-admin-password:latest\nDATABASE_URL=grp01-database-url\n"

STUB = """#!/bin/sh
# stub: records the commands that were called, and pretends to print a "secret" when a secret is read
echo "$0 $*" >> "$STUB_LOG"
case "$*" in
  *"latestRevision.yesno"*) echo "${TRAFFIC_STATE:-LATEST}"; exit 0 ;;
  *"revisions list"*) [ -n "$REVS" ] && printf '%%b' "$REVS"; exit 0 ;;
  *"status.traffic[0].revisionName"*) echo "$CUR_REV"; exit 0 ;;
  *"buildx build"*) if [ -n "$BUILD_FAIL" ]; then exit 1; fi ;;
  *"secrets versions list"*) echo "PERMISSION_DENIED: Permission 'secretmanager.versions.list' denied" >&2; exit 1 ;;
  *"versions access latest --secret=grp01-app-secret-2"*) echo "SLOT-PAYLOAD-xyz"; exit 0 ;;
  *"versions access latest --secret=grp01-app-secret-5"*) if [ -n "$SL5_STATE" ]; then echo "ERROR: (gcloud.secrets.versions.access) FAILED_PRECONDITION: Secret Version [projects/1/secrets/grp01-app-secret-5/versions/1] is in $SL5_STATE state." >&2; exit 1; fi; echo "NOT_FOUND: Secret [projects/1/secrets/x] not found or has no versions" >&2; exit 1 ;;
  *"versions access latest --secret=grp01-app-secret-1"*|*"versions access latest --secret=grp01-app-secret-5"*) echo "NOT_FOUND: Secret [projects/1/secrets/x] not found or has no versions" >&2; exit 1 ;;
  *"versions access latest --secret=grp01-app-secret-3"*) echo "PERMISSION_DENIED: Permission 'secretmanager.versions.access' denied" >&2; exit 1 ;;
  *"versions access latest --secret=grp01-app-secret-4"*) echo "ERROR: boom AAAAAAAAAAAAAAAAAAAAAAAAAAAA" >&2; echo "second-line-hidden" >&2; echo "SLOT-PAYLOAD-xyz"; exit 1 ;;
  *"secrets versions add"*) cat > "$STUB_STDIN"; exit 0 ;;
  *"secrets versions access"*) echo "%s"; exit 0 ;;
  *"auth list"*) echo "me@gmail.com" ;;
  *"--format=value(status.url)"*) echo "https://grp01-xyz.a.run.app" ;;
  *"env[].name"*) echo "NODE_ENV;DATABASE_URL" ;;
esac
exit 0
""" % SECRET_VALUE


def sh(args, cwd, env=None, timeout=60):
    e = dict(os.environ)
    for k in ("LC_ALL", "LC_MESSAGES", "LANG", "KIT_LANG"):   # tests start from a neutral locale
        e.pop(k, None)
    e["LANG"] = "C"
    e.update(env or {})
    return subprocess.run(args, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "resources.env").write_text(RESOURCES)
        (self.dir / "app.env").write_text(APP_ENV)
        (self.dir / "secrets.map").write_text(SECRETS_MAP)
        (self.dir / "Dockerfile").write_text("FROM scratch\n")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name in ("gcloud", "docker"):
            p = self.bin / name
            p.write_text(STUB)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / "stub.log"
        self.stdin_file = self.dir / "stub.stdin"
        self.env = {"STUB_LOG": str(self.log), "STUB_STDIN": str(self.stdin_file), "PATH": f"{self.bin}:{os.environ['PATH']}", "HOME": str(self.dir), "KIT_CMD": "./kit.sh"}

    def tearDown(self):
        self.tmp.cleanup()

    def kit(self, *args, env=None, **kw):
        e = dict(self.env); e.update(env or {})
        return sh(["bash", KITSH, *args], self.dir, e, **kw)

    def kit_all(self, *args, **kw):
        r = self.kit(*args, **kw)
        return r.stdout + r.stderr  # read-only commands print to stderr in dry-run

    def stub_calls(self):
        return self.log.read_text() if self.log.exists() else ""

    def edit_resources(self, extra):
        (self.dir / "resources.env").write_text(RESOURCES + extra)


class DryRunCommands(Base):
    def test_build_command(self):
        r = self.kit("--dry-run", "build", "--tag", "v1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("docker buildx build --platform linux/amd64", r.stdout)
        self.assertIn("-t asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01:v1", r.stdout)
        self.assertIn("-f Dockerfile", r.stdout)
        self.assertIn("--push .", r.stdout)
        self.assertEqual(self.stub_calls(), "", "dry-run must not call gcloud/docker")

    def test_build_default_tag_timestamp_outside_git(self):
        r = self.kit("--dry-run", "build")
        self.assertRegex(r.stdout, r"grp01/grp01:(git-[0-9a-f]+|ts-\d{8}-\d{6})")

    def test_build_custom_dockerfile_and_context(self):
        r = self.kit("--dry-run", "build", "--tag", "t", "--dockerfile", "api/Dockerfile", "--context", "api")
        self.assertIn("-f api/Dockerfile", r.stdout)
        self.assertIn("--push api", r.stdout)

    def test_deploy_order_and_flags(self):
        r = self.kit("--dry-run", "deploy")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        i_job_update = out.index("gcloud run jobs update grp01-migrate")
        i_exec = out.index("gcloud run jobs execute grp01-migrate")
        i_svc = out.index("gcloud run services update grp01 ")
        self.assertLess(i_job_update, i_exec)
        self.assertLess(i_exec, i_svc)
        self.assertIn("--wait", out)
        self.assertIn("--max-instances 1", out)
        self.assertIn("--port 8000", out)
        self.assertIn("--add-cloudsql-instances cpe-se-course-2026:asia-southeast1:grp01-pg", out)
        self.assertIn("--update-env-vars", out)
        self.assertIn("--update-secrets ADMIN_PASSWORD=grp01-admin-password:latest,DATABASE_URL=grp01-database-url:latest", out)
        self.assertIn("--command alembic --args ^|^upgrade|head", out.replace("'", ""))   # plain command: exec-style, no sh
        self.assertIn("update-traffic grp01", out)

    def test_no_destructive_flags_by_default(self):
        out = self.kit("--dry-run", "deploy").stdout + self.kit("--dry-run", "migrate").stdout
        for bad in ("--set-env-vars", "--set-secrets", "--clear-env-vars", "--clear-secrets", "--remove-secrets"):
            self.assertNotIn(bad, out)

    def test_env_values_with_commas_use_custom_delimiter(self):
        out = self.kit("--dry-run", "deploy", "--skip-migrate").stdout
        self.assertIn("^@^NODE_ENV=***@TZ=***@GREETING=***", out)   # values are masked in everything that is printed
        self.assertNotIn("hello, world", out)
        self.assertNotIn("production", out)

    def test_skip_migrate(self):
        out = self.kit("--dry-run", "deploy", "--skip-migrate").stdout
        self.assertNotIn("jobs execute", out)
        self.assertIn("services update grp01", out)

    def test_no_migrate_command_skips_in_deploy_but_fails_in_migrate(self):
        (self.dir / "resources.env").write_text(RESOURCES.replace("MIGRATE_COMMAND=alembic upgrade head\n", ""))
        out = self.kit("--dry-run", "deploy").stdout
        self.assertNotIn("jobs execute", out)
        self.assertIn("skipping the migration", out)
        r = self.kit("--dry-run", "migrate")
        self.assertNotEqual(r.returncode, 0)

    def test_replace_env_requires_flag_and_uses_set(self):
        r = self.kit("--dry-run", "deploy", "--skip-migrate", "--replace-env")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--set-env-vars", r.stdout)
        self.assertIn("--set-secrets", r.stdout)
        self.assertIn("would ask for confirmation", r.stdout)

    def test_replace_env_real_run_refuses_without_tty_even_with_yes(self):
        r = self.kit("--yes", "deploy", "--skip-migrate", "--replace-env", "--image",
                     "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:" + "a" * 64)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("services update", self.stub_calls())

    def test_env_set_unset(self):
        out = self.kit("--dry-run", "env", "set", "FOO=bar", "--job").stdout
        self.assertIn("run services update grp01", out)
        self.assertIn("run jobs update grp01-migrate", out)
        self.assertIn("--update-env-vars", out)
        out = self.kit("--dry-run", "env", "unset", "FOO").stdout
        self.assertIn("--remove-env-vars FOO", out)
        self.assertNotIn("jobs update", out)

    def test_env_set_secretish_refused(self):
        r = self.kit("--dry-run", "env", "set", "DB_PASSWORD=hunter2")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("hunter2", r.stdout + r.stderr.replace("DB_PASSWORD=hunter2", ""))

    def test_logs_status_open_rollback(self):
        out = self.kit("--dry-run", "logs", "--severity", "error", "--limit", "10").stdout
        self.assertIn("gcloud logging read", out)
        self.assertIn("severity>=ERROR", out)
        self.assertIn("--view=grp01", out)
        self.assertIn("cloud_run_job", self.kit("--dry-run", "logs", "job").stdout)
        self.assertEqual(self.kit("--dry-run", "logs", "--severity", "bogus").returncode, 1)
        out = self.kit_all("--dry-run", "status")
        self.assertIn("run services describe grp01", out)
        self.assertIn("run jobs executions list --job grp01-migrate", out)
        self.assertIn("run services describe grp01", self.kit_all("--dry-run", "open"))
        out = self.kit_all("--dry-run", "rollback")
        self.assertIn("run revisions list --service grp01", out)
        self.assertIn("--to-revisions", out)
        self.assertEqual(self.kit("--dry-run", "rollback", "--to", "other-00001").returncode, 1)

    def test_doctor_and_secrets_dry_run(self):
        out = self.kit("--dry-run", "doctor").stdout
        self.assertIn("run services describe grp01", out)
        self.assertIn("artifacts repositories describe grp01", out)
        self.assertIn("grp01-admin-password", self.kit("--dry-run", "secrets").stdout)

    def test_init_copies_template(self):
        (self.dir / "Dockerfile").unlink()
        r = self.kit("init", "--stack", "go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("golang", (self.dir / "Dockerfile").read_text())
        self.assertTrue((self.dir / ".dockerignore").exists())

    def test_stack_sets_default_port(self):
        (self.dir / "resources.env").write_text("PREFIX=grp01\n")
        out = self.kit("--dry-run", "deploy", "--skip-migrate", "--stack", "node").stdout
        self.assertIn("--port 8080", out)
        self.assertIn("services update grp01", out)


class PrefixGuard(Base):
    def assert_blocked(self, extra=None, files=None, args=("--dry-run", "deploy")):
        if extra:
            self.edit_resources(extra)
        for name, text in (files or {}).items():
            (self.dir / name).write_text(text)
        r = self.kit(*args)
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.stub_calls(), "")
        self.assertNotIn("gcloud run", r.stdout)
        return r

    def test_foreign_service(self):
        r = self.assert_blocked("SERVICE_NAME=otherteam\n")
        self.assertIn("does not belong to your team", r.stderr)

    def test_prefix_lookalike_blocked(self):
        self.assert_blocked("SERVICE_NAME=grp011\n")  # starts with grp01 but has no '-'

    def test_foreign_job(self):
        self.assert_blocked("MIGRATE_JOB_NAME=other-migrate\n")

    def test_foreign_registry(self):
        self.assert_blocked("REGISTRY=cpe334-portal\n", args=("--dry-run", "build"))

    def test_foreign_runtime_sa(self):
        self.assert_blocked("RUNTIME_SA=other-runner@cpe-se-course-2026.iam.gserviceaccount.com\n")

    def test_foreign_sql(self):
        self.assert_blocked("SQL_CONNECTION_NAME=cpe-se-course-2026:asia-southeast1:other-pg\n")

    def test_foreign_secret_in_map(self):
        self.assert_blocked(files={"secrets.map": "X=other-database-url:latest\n"})

    def test_foreign_image_override(self):
        self.assert_blocked(args=("--dry-run", "deploy", "--image",
                                  "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/other/other@sha256:" + "b" * 64))

    def test_foreign_revision_and_env_job(self):
        self.assert_blocked(args=("--dry-run", "rollback", "--to", "otherteam-00001-abc"))

    def test_bad_prefix(self):
        (self.dir / "resources.env").write_text("PREFIX=BAD_PREFIX\n")
        self.assertNotEqual(self.kit("--dry-run", "status").returncode, 0)


class Secrets(Base):
    def test_plain_env_rejects_secret_like_keys_and_urls(self):
        for text in ("DB_PASSWORD=hunter2\n", "API_KEY=abc\n", "DATABASE_URL=postgres://u:p@h/db\n",
                     "FOO=postgres://user:pw123@host/db\n", "PORT=3000\n", "AUTH_TOKEN=x\n"):
            (self.dir / "app.env").write_text(text)
            r = self.kit("--dry-run", "deploy", "--skip-migrate")
            self.assertNotEqual(r.returncode, 0, text)
            self.assertNotIn("hunter2", r.stdout + r.stderr)
            self.assertNotIn("pw123", r.stdout + r.stderr)

    def test_secret_values_never_printed(self):
        calls = [("secrets",), ("doctor",), ("status",), ("env", "list"), ("logs",)]
        for c in calls:
            r = self.kit(*c, "--yes")
            self.assertNotIn(SECRET_VALUE, r.stdout + r.stderr, c)
        self.assertIn("versions access", self.stub_calls())  # a real check happened but the result was discarded
        r = self.kit("secrets")
        self.assertIn("grp01-admin-password", r.stdout)
        self.assertIn("[readable]", r.stdout)

    def test_status_shows_env_names_only(self):
        r = self.kit("status")
        self.assertIn("NODE_ENV", r.stdout)
        self.assertNotIn("production", r.stdout)

    def test_real_run_deploy_calls_in_order(self):
        img = "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:" + "c" * 64
        r = self.kit("--yes", "deploy", "--image", img)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.stub_calls()
        self.assertLess(calls.index("run jobs update"), calls.index("run jobs execute"))
        self.assertLess(calls.index("run jobs execute"), calls.index("run services update"))
        self.assertNotIn("--set-env-vars", calls)

    def test_migration_failure_aborts_deploy(self):
        p = self.bin / "gcloud"
        p.write_text(STUB.replace('esac\nexit 0', 'esac\ncase "$*" in *"jobs execute"*) exit 1;; esac\nexit 0'))
        img = "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:" + "d" * 64
        r = self.kit("--yes", "deploy", "--image", img)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("run services update", self.stub_calls())
        self.assertIn("logs job", r.stderr)


SAMPLE = {
    "team": "Group 1", "mode": "live", "created_in_google_cloud": True, "github_connected": False,
    "project_id": "cpe-se-course-2026", "region": "asia-southeast1", "prefix": "grp01",
    "resources": {
        "cloud_run_service": "grp01", "migration_job": "grp01-migrate", "sql_instance": "grp01-pg",
        "database": "grp01", "registry": "grp01",
        "runtime_service_account": "grp01-runner@cpe-se-course-2026.iam.gserviceaccount.com",
        "database_secret": "grp01-database-url", "admin_password_secret": "grp01-admin-password",
        "demo_password_secret": "grp01-demo-password",
        "sql_connection_name": "cpe-se-course-2026:asia-southeast1:grp01-pg",
        "image_repository": "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01",
    },
    "usage_notes": ["x"],
}


class FromPortalJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def convert(self, data, *extra, raw=None):
        f = self.dir / "in.json"
        f.write_text(raw if raw is not None else json.dumps(data))
        return sh(["bash", CONVERT, str(f), *extra], self.dir)

    def test_conversion_and_kit_accepts_it(self):
        r = self.convert(SAMPLE)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.dir / "resources.env").read_text()
        for line in ("PREFIX=grp01", "SERVICE_NAME=grp01", "MIGRATE_JOB_NAME=grp01-migrate", "REGISTRY=grp01",
                     "IMAGE_NAME=grp01", "PROJECT_ID=cpe-se-course-2026", "REGION=asia-southeast1",
                     "SQL_CONNECTION_NAME=cpe-se-course-2026:asia-southeast1:grp01-pg"):
            self.assertIn(line, text.splitlines())
        r2 = sh(["bash", KITSH, "--dry-run", "status"], self.dir)
        self.assertEqual(r2.returncode, 0, r2.stderr)

    def test_refuses_overwrite_unless_force(self):
        self.assertEqual(self.convert(SAMPLE).returncode, 0)
        self.assertNotEqual(self.convert(SAMPLE).returncode, 0)
        self.assertEqual(self.convert(SAMPLE, "--force").returncode, 0)

    def test_stdout_mode(self):
        r = self.convert(SAMPLE, "-o", "-")
        self.assertIn("PREFIX=grp01", r.stdout)

    def test_missing_keys_clear_error(self):
        d = json.loads(json.dumps(SAMPLE))
        del d["resources"]["migration_job"]
        del d["prefix"]
        r = self.convert(d)
        self.assertEqual(r.returncode, 1)
        self.assertIn("prefix", r.stderr)
        self.assertIn("resources.migration_job", r.stderr)
        self.assertFalse((self.dir / "resources.env").exists())

    def test_no_resources_and_bad_json(self):
        self.assertIn("resources", self.convert({"prefix": "grp01"}).stderr)
        r = self.convert(None, raw="{not json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("JSON", r.stderr)
        self.assertEqual(sh(["bash", CONVERT, str(self.dir / "nope.json")], self.dir).returncode, 2)

    def test_unsafe_value_rejected(self):
        d = json.loads(json.dumps(SAMPLE))
        d["resources"]["cloud_run_service"] = "grp01; rm -rf /"
        self.assertEqual(self.convert(d).returncode, 1)

    def test_preview_warns(self):
        d = dict(SAMPLE, created_in_google_cloud=False, mode="preview")
        self.assertIn("preview", self.convert(d).stderr)


class ReviewFixes(Base):
    """Regression tests for the verified review findings (H2, H3, M1-M7, L1-L13)."""

    # ---- H2 / L2 / L7 / L8 : templates
    def test_h2_static_init_keeps_dist_and_build(self):
        (self.dir / "Dockerfile").unlink()
        r = self.kit("init", "--stack", "static")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = (self.dir / ".dockerignore").read_text().splitlines()
        self.assertNotIn("dist", lines)
        self.assertNotIn("build", lines)
        self.assertIn("node_modules", lines)
        self.assertIn("COPY dist/", (self.dir / "Dockerfile").read_text())

    def test_h2_default_dockerignore_and_trap_warning(self):
        text = (KIT / "templates" / "dockerignore.example").read_text()
        for needle in ("**/.env", "**/.env.*", "**/*.pem", "**/node_modules", "**/.git"):
            self.assertIn(needle, text.splitlines())
        (self.dir / "Dockerfile").write_text("FROM nginx\nCOPY dist/ /usr/share/nginx/html/\n")
        (self.dir / ".dockerignore").write_text("node_modules\ndist\n")
        r = self.kit("--dry-run", "build", "--tag", "t")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("excludes it", r.stderr)
        (self.dir / ".dockerignore").write_text("node_modules\n")
        self.assertNotIn("excludes it", self.kit("--dry-run", "build", "--tag", "t").stderr)

    def test_l7_templates_non_root_and_node_multistage(self):
        t = KIT / "templates"
        for name in ("python", "java", "go", "node"):
            self.assertRegex((t / f"Dockerfile.{name}").read_text(), r"(?m)^USER \S+", name)
        node = (t / "Dockerfile.node").read_text()
        self.assertIn("AS build", node)
        self.assertIn("npm run build", node)
        self.assertIn("npm prune --omit=dev", node)
        self.assertIn("adduser", (t / "Dockerfile.go").read_text())
        self.assertNotIn("distroless/static", (t / "Dockerfile.go").read_text())

    # ---- H3 : secret-looking names and values, masking
    def test_h3_secret_like_names_refused(self):
        for name in ("API_KEY", "OPENAI_KEY", "DB_PWD", "DB_PASS", "ADMIN_PASSWORD", "MY_SECRET", "AUTH_TOKEN",
                     "WEBHOOK_SIGNATURE", "AWS_CREDENTIALS", "PRIVATE_KEY", "DATABASE_URL"):
            (self.dir / "app.env").write_text(f"{name}=abc\n")
            r = self.kit("--dry-run", "deploy", "--skip-migrate")
            self.assertNotEqual(r.returncode, 0, name)
            self.assertIn("secrets add", r.stderr, name)
            self.assertIn("secrets map", r.stderr, name)
        for name in ("KEYCLOAK_URL", "KEYCLOAK_REALM", "KEYCLOAK_CLIENT_ID", "LOG_LEVEL"):
            (self.dir / "app.env").write_text(f"{name}=abc\n")
            self.assertEqual(self.kit("--dry-run", "deploy", "--skip-migrate").returncode, 0, name)

    def test_h3_secret_like_values_refused_and_never_printed(self):
        values = ["sk-abcdef1234567890", "sk_live_abc123", "AIzaSyA-fake-key-0000", "ghp_abcdefghijklmnop", "github_pat_11ABCDE",
                  "xoxb-1234-5678", "AKIAIOSFODNN7EXAMPLE", "-----BEGIN PRIVATE KEY-----",
                  "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc", "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3", "0123456789abcdef" * 4]
        for v in values:
            (self.dir / "app.env").write_text(f"GREETING={v}\n")
            for args in (("--dry-run", "deploy", "--skip-migrate"), ("--dry-run", "env", "set", f"GREETING={v}")):
                r = self.kit(*args)
                self.assertNotEqual(r.returncode, 0, (v, args))
                self.assertNotIn(v, r.stdout + r.stderr, v)
                self.assertIn("secrets add", r.stderr)
        (self.dir / "app.env").write_text("GREETING=hello world 12345\nURL=https://example.com/a/b\n")
        self.assertEqual(self.kit("--dry-run", "deploy", "--skip-migrate").returncode, 0)

    def test_h3_env_values_masked_in_dry_run_and_real_run(self):
        img = "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:" + "e" * 64
        out = self.kit("--dry-run", "env", "set", "FOO=plainvalue1", "BAR=two").stdout
        self.assertIn("--update-env-vars '^@^FOO=***@BAR=***'", out)
        self.assertNotIn("plainvalue1", out)
        r = self.kit("--yes", "deploy", "--image", img)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NODE_ENV=***", r.stdout)
        self.assertNotIn("Asia/Bangkok", r.stdout + r.stderr)
        self.assertIn("NODE_ENV=production", self.stub_calls())       # the real command still gets the real values
        r = self.kit("--dry-run", "deploy", "--skip-migrate", "--replace-env")
        self.assertIn("--set-env-vars '^@^NODE_ENV=***", r.stdout)

    # ---- M1 : logs --follow
    def test_m1_follow_takes_timestamp_from_entries_and_surfaces_errors(self):
        cnt = self.dir / "cnt"
        (self.bin / "gcloud").write_text(f"""#!/bin/sh
echo "$*" >> "$STUB_LOG"
case "$*" in *"logging read"*)
  n=$(cat {cnt} 2>/dev/null || echo 0); n=$((n+1)); echo $n > {cnt}
  if [ $n -eq 1 ]; then printf '2026-11-19T10:00:00.123456Z\\tERROR\\tValueError: boom\\n  File "x.py", line 1\\nTypeError: y\\n'; exit 0; fi
  echo "ERROR: (gcloud.logging.read) PERMISSION_DENIED on the view" >&2; exit 1 ;;
esac
exit 0
""")
        r = self.kit("logs", "--follow", env={"KIT_FOLLOW_INTERVAL": "0", "KIT_FOLLOW_MAX": "10"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("ValueError: boom", r.stdout)
        calls = [l for l in self.stub_calls().splitlines() if "logging read" in l]
        self.assertGreaterEqual(len(calls), 4)
        self.assertIn('timestamp>"2026-11-19T10:00:00.123456Z"', calls[1])
        self.assertNotIn("ValueError", calls[1])
        self.assertIn("PERMISSION_DENIED on the view", r.stderr)
        self.assertIn("failed 3 times in a row", r.stderr)

    # ---- M2 : traffic pinned after rollback
    def test_m2_env_set_unset_warn_when_traffic_pinned(self):
        for args in (("env", "set", "FOO=bar"), ("--yes", "env", "unset", "FOO")):
            r = self.kit(*args, env={"TRAFFIC_STATE": "PINNED"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("pinned to one revision", r.stderr)
            self.assertIn("update-traffic grp01 --to-latest", r.stderr)
            r = self.kit(*args, env={"TRAFFIC_STATE": "LATEST"})
            self.assertNotIn("pinned", r.stderr)
        th = self.kit("--lang", "th", "env", "set", "FOO=bar", env={"TRAFFIC_STATE": "PINNED"})
        self.assertIn("ถูกตรึง", th.stderr)
        self.assertNotIn("pinned", self.kit("--dry-run", "env", "set", "FOO=bar").stderr)
        self.assertIn("./kit.sh deploy, which routes traffic to the latest revision", self.kit("--yes", "rollback", "--to", "grp01-00001-a").stdout)

    # ---- M3 : read_kv sentinel
    def test_m3_values_that_contain_err_prefix_work(self):
        (self.dir / "app.env").write_text("LOG_PREFIX=ERR: x\nMSG=xERR:y\nERR=ERR:z\n")
        r = self.kit("--dry-run", "deploy", "--skip-migrate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("LOG_PREFIX=***@MSG=***@ERR=***", r.stdout)
        self.edit_resources("MIGRATE_COMMAND=echo ERR: not an error\n")
        self.assertEqual(self.kit("--dry-run", "deploy").returncode, 0)

    # ---- M4 : caps
    def test_m4_cpu_memory_min_caps(self):
        for extra, text in (("CPU=4\n", "CPU '4' is above the limit"), ("CPU=2.5\n", "above the limit"), ("MEMORY=4Gi\n", "MEMORY '4Gi' is above the limit"),
                            ("MEMORY=4096Mi\n", "above the limit"), ("MIN_INSTANCES=1\n", "must be 0")):
            self.edit_resources(extra)
            r = self.kit("--dry-run", "deploy")
            self.assertEqual(r.returncode, 1, extra)
            self.assertIn(text, r.stderr, extra)
        self.edit_resources("CPU=2\nMEMORY=2Gi\n")
        self.assertEqual(self.kit("--dry-run", "deploy").returncode, 0)
        self.edit_resources("CPU=0.5\nMEMORY=2048Mi\n")
        self.assertEqual(self.kit("--dry-run", "deploy").returncode, 0)
        self.edit_resources("MIN_INSTANCES=1\n")
        r = self.kit("--allow-min-instances", "--dry-run", "deploy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--min-instances 1", r.stdout)
        self.assertIn("would ask for confirmation", r.stdout)
        th = self.kit("--lang", "th", "--dry-run", "deploy")
        self.assertIn("--allow-min-instances", th.stderr)

    # ---- M5 : from-portal-json.sh on Windows
    def test_m5_python_writes_utf8_file_without_console_output(self):
        f = self.dir / "in.json"
        f.write_text(json.dumps(SAMPLE))
        r = sh(["bash", CONVERT, str(f), "-o", str(self.dir / "out.env")], self.dir, {"PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0", "LC_ALL": "C"})
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = (self.dir / "out.env").read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertIn("สร้างจาก portal JSON".encode("utf-8"), raw)
        self.assertNotIn("สร้างจาก".encode("utf-8"), r.stdout.encode("utf-8"))
        self.assertIn(b"PREFIX=grp01", raw)

    def test_m5_python_store_stub_detected(self):
        fake = self.dir / "fakebin"
        fake.mkdir()
        for n in ("python3", "python"):
            (fake / n).write_text("#!/bin/sh\nexit 9\n")
            (fake / n).chmod(0o755)
        f = self.dir / "in.json"
        f.write_text(json.dumps(SAMPLE))
        env = {"PATH": f"{fake}:{os.environ['PATH']}"}
        en = sh(["bash", CONVERT, str(f), "-o", "-"], self.dir, {**env, "KIT_LANG": "en"})
        th = sh(["bash", CONVERT, str(f), "-o", "-"], self.dir, {**env, "KIT_LANG": "th"})
        self.assertEqual((en.returncode, th.returncode), (2, 2))
        self.assertIn("Microsoft Store", en.stderr)
        self.assertIn("python.org", en.stderr)
        self.assertIn("Microsoft Store", th.stderr)
        self.assertIn("ติดตั้ง Python 3", th.stderr)

    # ---- M6 : CRLF and Windows
    def test_m6_crlf_detected_with_clear_fix(self):
        for src in (KITSH, CONVERT):
            crlf = self.dir / ("crlf-" + Path(src).name)
            crlf.write_bytes(Path(src).read_bytes().replace(b"\n", b"\r\n"))
            r = sh(["bash", str(crlf), "help"], self.dir)
            self.assertEqual(r.returncode, 1, src)
            self.assertIn("Windows line endings", r.stderr)
            self.assertIn("dos2unix", r.stderr)
            self.assertIn("sed -i", r.stderr)
            self.assertNotIn("invalid option name", r.stderr)

    def test_m6_gitattributes_and_windows_docs(self):
        self.assertIn("*.sh text eol=lf", (KIT / ".gitattributes").read_text())
        for readme, words in (("README.md", ("## Windows", "WSL", "Git Bash", "chmod +x project-kit/*.sh", "bash project-kit/kit.sh", "python3",
                                              ".gitattributes", "MSYS_NO_PATHCONV=1", "dos2unix")),
                              ("README.th.md", ("## Windows", "WSL", "Git Bash", "chmod +x project-kit/*.sh", "bash project-kit/kit.sh", "python3",
                                                 ".gitattributes", "MSYS_NO_PATHCONV=1", "dos2unix"))):
            text = (KIT / readme).read_text(encoding="utf-8")
            for w in words:
                self.assertIn(w, text, (readme, w))

    # ---- M7 : never echo values from secrets.map
    def test_m7_secrets_map_errors_show_env_name_and_line_only(self):
        real = "sk-REALVALUE0123456789abcdef"
        for text, expect in ((f"MY_API_KEY={real}\n", "line 1"), (f"# c\nMY_API_KEY=other-{real}:latest\n", "line 2"),
                             (f"MY_API_KEY={real} with spaces\n", "line 1"), (f"{real}\n", "secrets.map:1:")):
            (self.dir / "secrets.map").write_text(text)
            for cmd in (("--dry-run", "doctor"), ("--dry-run", "deploy"), ("--dry-run", "secrets")):
                r = self.kit(*cmd)
                self.assertEqual(r.returncode, 1, (text, cmd))
                self.assertNotIn(real, r.stdout + r.stderr, (text, cmd))
                self.assertIn(expect, r.stderr)
        (self.dir / "secrets.map").write_text(f"MY_API_KEY={real}\n")
        self.assertIn("MY_API_KEY", self.kit("--dry-run", "deploy").stderr)
        self.assertNotIn(real, self.kit("--lang", "th", "--dry-run", "deploy").stderr)

    # ---- L1 : dirty check and .gitignore
    def test_l1_dirty_ignores_kit_files_and_init_updates_gitignore(self):
        def git(*a):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.dir, capture_output=True, text=True, timeout=60,
                                  env={**os.environ, "HOME": str(self.dir)})
        git("init", "-q"); git("add", "Dockerfile", "bin"); git("commit", "-qm", "x")
        (self.dir / ".kit-state").mkdir()
        (self.dir / ".kit-state" / "last-image").write_text("x\n")
        out = self.kit("--dry-run", "build").stdout
        self.assertRegex(out, r"grp01:git-[0-9a-f]{12}[ )\n']")
        self.assertNotIn("dirty", out)
        (self.dir / "new.txt").write_text("x")
        self.assertIn("dirty", self.kit("--dry-run", "build").stdout)
        # init: no .gitignore -> created with a note; existing one -> lines appended once
        r = self.kit("init", "--stack", "go")
        text = (self.dir / ".gitignore").read_text()
        for e in (".kit-state/", "resources.env", "app.env", "secrets.map", "do not commit"):
            self.assertIn(e, text)
        self.kit("init", "--stack", "go")
        self.assertEqual((self.dir / ".gitignore").read_text(), text)
        (self.dir / ".gitignore").write_text("node_modules\napp.env")
        self.kit("init", "--stack", "go")
        lines = (self.dir / ".gitignore").read_text().splitlines()
        self.assertEqual(lines.count("app.env"), 1)
        self.assertIn(".kit-state/", lines)
        self.assertIn("node_modules", lines)

    # ---- L3 : trailing newline
    def test_l3_trailing_newline_removed_from_file_and_stdin(self):
        (self.dir / "k.txt").write_text("filevalue\n")
        self.assertEqual(self.kit("secrets", "add", "1", "--from-file", "k.txt").returncode, 0)
        self.assertEqual(self.stdin_file.read_text(), "filevalue")
        r = subprocess.run(["bash", KITSH, "secrets", "add", "3", "--from-stdin"], cwd=self.dir, env={**os.environ, **self.env},
                           input="piped\n", capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.stdin_file.read_text(), "piped")
        (self.dir / "e.txt").write_text("\n")
        self.assertNotEqual(self.kit("secrets", "add", "1", "--from-file", "e.txt").returncode, 0)

    # ---- L4 : explicit flag, missing file
    def test_l4_explicit_missing_files_are_errors(self):
        for flag in ("--app-env", "--secrets-map"):
            r = self.kit(flag, "typo.env", "--dry-run", "deploy")
            self.assertEqual(r.returncode, 1, flag)
            self.assertIn("file not found: typo.env", r.stderr)
            self.assertIn(flag, r.stderr)
            th = self.kit("--lang", "th", flag, "typo.env", "--dry-run", "deploy")
            self.assertIn("ไม่พบไฟล์ typo.env", th.stderr)
        (self.dir / "app.env").unlink()   # not given explicitly: still fine to be missing
        self.assertEqual(self.kit("--dry-run", "deploy", "--skip-migrate").returncode, 0)
        r = self.kit("--secrets-map", "new.map", "secrets", "map", "FOO_KEY", "1")   # `secrets map` creates the file
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.dir / "new.map").exists())

    # ---- L5 : tolerant parsing
    def test_l5_bom_crlf_comments_and_spaces(self):
        (self.dir / "resources.env").write_bytes(("﻿PREFIX=grp01   # my team\r\nPORT = 8000  \r\n  STACK=python\t# stack\r\n").encode("utf-8"))
        (self.dir / "app.env").write_bytes(b"\xef\xbb\xbfNODE_ENV=production # prod\r\nTZ=\"Asia/Bangkok\"  # quoted\r\nQ='a b'\r\n")
        r = self.kit("--dry-run", "deploy", "--skip-migrate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--port 8000", r.stdout)
        self.assertIn("^@^NODE_ENV=***@TZ=***@Q=***", r.stdout)
        self.assertNotIn("Warning", r.stderr)
        # the real value is correct (checked through a real run with the stub)
        img = "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:" + "f" * 64
        self.assertEqual(self.kit("--yes", "deploy", "--skip-migrate", "--image", img).returncode, 0)
        self.assertIn("^@^NODE_ENV=production@TZ=Asia/Bangkok@Q=a b", self.stub_calls())

    def test_l5_bad_line_reports_file_and_line_but_not_text(self):
        (self.dir / "app.env").write_text("OK=1\nsk-realsecretvalue1234567890\n")
        r = self.kit("--dry-run", "deploy", "--skip-migrate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("app.env:2:", r.stderr)
        self.assertNotIn("sk-realsecret", r.stderr)

    # ---- L6 : MIGRATE_COMMAND delimiter
    def test_l6_migrate_command_without_safe_delimiter_dies(self):
        self.edit_resources("MIGRATE_COMMAND=a|b@c~d!e;f%g\n")
        r = self.kit("--dry-run", "migrate")
        self.assertEqual(r.returncode, 1)
        self.assertIn("MIGRATE_COMMAND contains too many special characters", r.stderr)
        self.assertNotIn("jobs update", r.stdout)
        th = self.kit("--lang", "th", "--dry-run", "migrate")
        self.assertIn("MIGRATE_COMMAND มีอักขระพิเศษมากเกินไป", th.stderr)

    # ---- L9 / L10 : docs agree with the code
    def test_l9_readme_claims(self):
        for readme in ("README.md", "README.th.md"):
            text = (KIT / readme).read_text(encoding="utf-8")
            self.assertNotIn("tests/                    offline", text)
            self.assertNotIn("tests/                    ทดสอบ", text)
            self.assertIn("lab5-<prefix>-handoff.json", text)
            self.assertNotIn("portal-resources.json", text)
            self.assertIn("project-kit/resources.env", text)
            self.assertIn("Do not overwrite" if readme == "README.md" else "อย่าเขียนทับ", text)
        # kit.sh search order: current folder first, then the kit folder
        (self.dir / "resources.env").unlink()
        self.assertEqual(self.kit("--dry-run", "status").returncode, 1)
        r = self.kit("--lang", "en", "--dry-run", "status")
        self.assertIn("project-kit/resources.env", r.stderr)
        self.assertIn(str(KIT), r.stderr)

    # ---- L11 : open
    def test_l11_open_tries_windows_and_wsl_openers(self):
        src = Path(KITSH).read_text(encoding="utf-8")
        for opener in ("wslview", "explorer.exe", "start", "xdg-open", "cmd.exe"):
            self.assertIn(opener, src)
        r = self.kit("open")
        self.assertIn("https://grp01-xyz.a.run.app", r.stdout)

    # ---- L12
    def test_l12_github_actions_uses_bash(self):
        text = (KIT / "templates" / "deploy.github-actions.example.yml").read_text()
        self.assertIn("bash ./project-kit/kit.sh", text)
        self.assertNotIn("run: ./project-kit/kit.sh", text)

    # ---- L13
    def test_l13_init_dry_run_does_not_say_created(self):
        (self.dir / "Dockerfile").unlink()
        r = self.kit("--dry-run", "init", "--stack", "node")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("created", r.stdout)
        self.assertIn("cp ", r.stdout)
        self.assertFalse((self.dir / "Dockerfile").exists())
        self.assertFalse((self.dir / ".gitignore").exists())

    def test_l13_severity_message_lists_all_values(self):
        r = self.kit("--dry-run", "logs", "--severity", "bogus")
        for v in ("DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"):
            self.assertIn(v, r.stderr)
        self.assertEqual(self.kit("--dry-run", "logs", "--severity", "alert").returncode, 0)

    def test_l13_env_unset_job_confirmation_wording(self):
        a = self.kit("--dry-run", "env", "unset", "FOO", "--job").stdout
        b = self.kit("--dry-run", "env", "unset", "FOO").stdout
        self.assertIn("from the service AND from the migrate job", a)
        self.assertNotIn("migrate job", b.split("\n")[1])
        self.assertIn("และออกจาก migrate job", self.kit("--lang", "th", "--dry-run", "env", "unset", "FOO", "--job").stdout)

    def test_l13_build_failure_leaves_no_meta_file(self):
        tmpdir = self.dir / "tmpd"; tmpdir.mkdir()
        r = self.kit("build", "--tag", "v1", env={"BUILD_FAIL": "1", "TMPDIR": str(tmpdir)})
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual([p.name for p in tmpdir.iterdir() if p.name.startswith("kit-build-meta")], [])

    def test_l13_rollback_skips_not_ready_revisions(self):
        revs = "grp01-00004-aaa\\tReady\\tTrue\\ngrp01-00003-bbb\\tReady\\tFalse\\ngrp01-00002-ccc\\tReady\\tTrue\\n"
        r = self.kit("--yes", "rollback", env={"REVS": revs, "CUR_REV": "grp01-00004-aaa"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--to-revisions grp01-00002-ccc=100", self.stub_calls())
        self.assertNotIn("grp01-00003-bbb=100", self.stub_calls())


class ReviewRound2(Base):
    """M1 secret filter redesign, M3 go/migrate, M4 init, M5/U1 templates, L1-L3, L8, L9, L11."""

    def deploy_with(self, line, *flags):
        (self.dir / "app.env").write_text(line + "\n")
        return self.kit(*flags, "--dry-run", "deploy", "--skip-migrate")

    def test_m1_ordinary_env_passes(self):
        ok = ["NEXTAUTH_URL=http://localhost:3000", "AUTH_TRUST_HOST=true", "ACCESS_TOKEN_EXPIRE_MINUTES=30", "BCRYPT_SALT_ROUNDS=10",
              "PUBLIC_KEY_URL=https://example.com/jwks", "AUTHOR_NAME=Somchai", "PASSPORT_STRATEGY=local", "MONKEY_MODE=on",
              "REGION_LABEL=ASIA-SE", "UPLOAD_DIR=/var/lib/myapp/uploads/public/images",
              "BUCKET=cpe-se-course-2026-team-abc-uploads-bucket", "FEATURE_FLAGS=enable-new-dashboard-and-reports-v2",
              "COMMIT_SHA=" + "0123456789abcdef0123456789abcdef01234567", "NODE_ENV=production", "TZ=Asia/Bangkok", "LOG_LEVEL=debug",
              "APP_MODE=dev", "DATABASE_HOST=10.0.0.5", "API_URL=https://api.example.com", "KEYCLOAK_URL=https://kc.example.com",
              "GOOGLE_CLIENT_ID=123-abc.apps.example.com", "REDIS_URL=redis://cache:6379", "CORS_ORIGIN=https://app.example.com",
              "AWS_ACCESS_KEY_ID=abc"]
        for line in ok:
            r = self.deploy_with(line)
            self.assertEqual(r.returncode, 0, (line, r.stderr))
            name, value = line.split("=", 1)
            r = self.kit("--dry-run", "env", "set", line)
            self.assertEqual(r.returncode, 0, (line, r.stderr))
            self.assertNotIn("=" + value, r.stdout, "values stay masked")

    def test_m1_secrets_still_blocked(self):
        bad_names = ["STRIPE_KEY", "OPENAI_API_KEY", "JWT_SECRET", "DB_PASSWORD", "DB_PWD", "API_TOKEN", "GOOGLE_CLIENT_SECRET",
                     "SESSION_SECRET", "AWS_SECRET_ACCESS_KEY", "PRIVATE_KEY", "AUTH", "GITHUB_AUTH_TOKEN", "SERVICE_AUTH_KEY",
                     "APP_AUTH_SECRET", "SENTRY_DSN", "DB_CONNECTION_STRING", "DATABASE_URL", "DB_PASS", "WEBHOOK_SIGNATURE"]
        for name in bad_names:
            r = self.deploy_with(name + "=abc")
            self.assertEqual(r.returncode, 1, name)
            self.assertIn("secrets add", r.stderr, name)
            r = self.kit("--dry-run", "env", "set", name + "=abc")
            self.assertEqual(r.returncode, 1, name)
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.sig"
        for v in ["sk_live_abc123", "sk_test_abc123", "ghp_abcdefghijklmnop", "gho_abcdefghijklmnop", "ghu_abcdefghijklmnop",
                  "ghs_abcdefghijklmnop", "ghr_abcdefghijklmnop", "AKIAIOSFODNN7EXAMPLE", "ASIAIOSFODNN7EXAMPLE",
                  "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7d", jwt, "-----BEGIN RSA PRIVATE KEY-----"]:
            for r in (self.deploy_with("GREETING=" + v), self.kit("--dry-run", "env", "set", "GREETING=" + v)):
                self.assertEqual(r.returncode, 1, v)
                self.assertNotIn(v, r.stdout + r.stderr)
                self.assertIn("--allow-plain GREETING", r.stderr)

    def test_m1_allow_plain_flag_and_directive(self):
        # flag (repeatable), skips name and value checks, still masked
        (self.dir / "app.env").write_text("MY_SECRET=abc\nGREETING=sk-notreallyasecretvalue\n")
        r = self.kit("--allow-plain", "MY_SECRET", "--allow-plain", "greeting", "--dry-run", "deploy", "--skip-migrate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MY_SECRET=***", r.stdout)
        self.assertNotIn("sk-notreally", r.stdout + r.stderr)
        r = self.kit("--dry-run", "env", "set", "--allow-plain", "MY_SECRET", "MY_SECRET=abc")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MY_SECRET=***", r.stdout)
        # directive in app.env (not passed to the app as an env variable)
        (self.dir / "app.env").write_text("ALLOW_PLAIN=MY_SECRET, GREETING\nMY_SECRET=abc\nGREETING=sk-notreallyasecretvalue\n")
        r = self.kit("--dry-run", "deploy", "--skip-migrate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("ALLOW_PLAIN", r.stdout)
        self.assertIn("MY_SECRET=***", r.stdout)
        # directive in resources.env also applies to env set; other names are still checked
        (self.dir / "app.env").write_text(APP_ENV)
        self.edit_resources("ALLOW_PLAIN=MY_SECRET\n")
        self.assertEqual(self.kit("--dry-run", "env", "set", "MY_SECRET=abc").returncode, 0)
        self.assertEqual(self.kit("--dry-run", "env", "set", "OTHER_SECRET=abc").returncode, 1)
        self.assertNotIn("unknown", self.kit("--dry-run", "env", "set", "MY_SECRET=abc").stderr.lower())
        # bad names in the directive are an error
        self.edit_resources("ALLOW_PLAIN=bad name!\n")
        self.assertEqual(self.kit("--dry-run", "status").returncode, 1)

    def test_m3_go_template_has_shell_and_migrate_exec_style(self):
        go = (KIT / "templates" / "Dockerfile.go").read_text()
        self.assertNotIn("distroless/static", go)
        self.assertIn("alpine", go)
        self.assertIn("adduser", go)
        self.assertRegex(go, r"(?m)^USER app")
        self.assertIn("/tmp", go)
        # plain command -> exec-style
        self.edit_resources("")
        (self.dir / "resources.env").write_text(RESOURCES.replace("alembic upgrade head", "/app/server migrate"))
        out = self.kit("--dry-run", "migrate").stdout.replace("'", "")
        self.assertIn("--command /app/server --args ^|^migrate", out)
        self.assertNotIn("--command sh", out)
        (self.dir / "resources.env").write_text(RESOURCES.replace("alembic upgrade head", "/app/migrate"))
        self.assertIn("--command /app/migrate --args ''", self.kit("--dry-run", "migrate").stdout)
        (self.dir / "resources.env").write_text(RESOURCES.replace("alembic upgrade head", "npx prisma migrate deploy"))
        self.assertIn("--command npx --args ^|^prisma|migrate|deploy", self.kit("--dry-run", "migrate").stdout.replace("'", ""))
        # shell syntax -> still sh -c
        for cmd in ("cd /app && ./migrate", "FOO=1 ./migrate", "./migrate > /tmp/x", "echo $HOME", "./migrate 'a b'"):
            (self.dir / "resources.env").write_text(RESOURCES.replace("alembic upgrade head", cmd))
            out = self.kit("--dry-run", "migrate").stdout
            self.assertIn("--command sh", out, cmd)
            self.assertIn("-c", out, cmd)

    def test_m4_init_requires_stack(self):
        (self.dir / "Dockerfile").unlink()
        (self.dir / "resources.env").write_text(RESOURCES.replace("STACK=python\n", ""))
        for lang, word in (("en", "does not guess"), ("th", "ไม่เดา")):
            r = self.kit("--lang", lang, "init")
            self.assertEqual(r.returncode, 1)
            self.assertIn("node|python|java|go|static", r.stderr)
            self.assertIn("--stack python init", r.stderr)
            self.assertIn(word, r.stderr)
            self.assertFalse((self.dir / "Dockerfile").exists())
        # --stack wins over resources.env STACK
        (self.dir / "resources.env").write_text(RESOURCES)
        self.assertEqual(self.kit("init", "--stack", "go").returncode, 0)
        self.assertIn("golang", (self.dir / "Dockerfile").read_text())
        # existing Dockerfile: never overwritten + how to start over
        out = self.kit("--stack", "node", "init").stdout
        self.assertIn("never overwrites", out)
        self.assertIn("rm Dockerfile", out)
        self.assertIn("golang", (self.dir / "Dockerfile").read_text())

    def test_m5_u1_templates(self):
        t = KIT / "templates"
        node = (t / "Dockerfile.node").read_text()
        self.assertIn("if [ -f package-lock.json ]; then npm ci; else npm install; fi", node)
        self.assertIn("devDependencies", node)
        self.assertIn("prisma", node)
        self.assertIn("AS build", node)
        self.assertRegex(node, r"(?m)^USER node")
        self.assertIn("chown node:node /app", node)
        self.assertIn("chown app:app /app", (t / "Dockerfile.python").read_text())
        self.assertIn("chown app:app /app", (t / "Dockerfile.java").read_text())
        self.assertIn("npm prune --omit=dev", self.kit("--lang", "en", "--stack", "node", "init").stdout)
        self.assertIn("npm prune --omit=dev", self.kit("--lang", "th", "--stack", "node", "init").stdout)
        for readme in ("README.md", "README.th.md"):
            text = (KIT / readme).read_text(encoding="utf-8")
            self.assertIn("npm prune --omit=dev", text)
            self.assertIn("prisma", text)

    def stdin_run(self, args, data):
        e = dict(os.environ); e.update(self.env)
        return subprocess.run(["bash", KITSH, *args], cwd=self.dir, env=e, input=data, capture_output=True, text=True, timeout=60)

    def test_l1_strips_trailing_cr(self):
        f = self.dir / "v.txt"
        f.write_bytes(b"  my value \r\n")
        r = self.kit("secrets", "add", "1", "--from-file", str(f))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.stdin_file.read_bytes(), b"  my value ")
        r = self.stdin_run(["secrets", "add", "2", "--from-stdin"], "abc \r\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.stdin_file.read_bytes(), b"abc ")

    def test_l2_messages_use_the_invocation(self):
        kitdir = self.dir / "project-kit"
        kitdir.mkdir()
        (kitdir / "kit.sh").write_text(Path(KITSH).read_text())
        (kitdir / "kit.sh").chmod(0o755)
        for args, cmd in ((["bash", "project-kit/kit.sh"], "./project-kit/kit.sh"), (["./project-kit/kit.sh"], "./project-kit/kit.sh")):
            r = sh([*args, "--dry-run", "build"], self.dir, {**self.env, "KIT_CMD": ""})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("next step: " + cmd + " deploy", r.stdout)
        r = sh(["./project-kit/kit.sh", "--dry-run", "env", "set", "DB_PASSWORD=x"], self.dir, {**self.env, "KIT_CMD": ""})
        self.assertIn("./project-kit/kit.sh secrets add", r.stderr)
        self.assertNotIn(" ./kit.sh", r.stderr)
        # the READMEs use the real path
        for readme in ("README.md", "README.th.md"):
            text = (KIT / readme).read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?<![\w/])\./kit\.sh")

    def test_l3_both_file_names(self):
        for readme in ("README.md", "README.th.md"):
            text = (KIT / readme).read_text(encoding="utf-8")
            self.assertIn("<prefix>-resources.json", text)
            self.assertIn("lab5-<prefix>-handoff.json", text)
        for f in ("resources.example.env",):
            text = (KIT / f).read_text()
            self.assertIn("<prefix>-resources.json", text)
            self.assertIn("lab5-<prefix>-handoff.json", text)
        for lang in ("en", "th"):
            r = sh(["bash", CONVERT, "--lang", lang, "--help"], self.dir)
            self.assertIn("<prefix>-resources.json", r.stdout)
            self.assertIn("lab5-<prefix>-handoff.json", r.stdout)
        (self.dir / "resources.env").unlink()
        r = self.kit("--lang", "en", "--dry-run", "status", env={"KIT_CMD": ""})
        self.assertIn("<prefix>-resources.json", r.stderr)
        self.assertIn("lab5-<prefix>-handoff.json", r.stderr)

    def test_l8_open_failure_keeps_exit_zero(self):
        p = self.bin / "open"
        p.write_text("#!/bin/sh\nexit 1\n")
        p.chmod(0o755)
        r = self.kit("open")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("https://grp01-xyz.a.run.app", r.stdout)

    def test_l9_follow_removes_temp_files(self):
        tmpd = self.dir / "tmpd"
        tmpd.mkdir()
        env = {"TMPDIR": str(tmpd), "KIT_FOLLOW_INTERVAL": "0", "KIT_FOLLOW_MAX": "2"}
        r = self.kit("logs", "--follow", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(list(tmpd.iterdir()), [])
        (self.bin / "gcloud").write_text("#!/bin/sh\ncase \"$*\" in *\"logging read\"*) echo oops >&2; exit 1 ;; esac\nexit 0\n")
        r = self.kit("logs", "--follow", env={**env, "KIT_FOLLOW_MAX": "10"})
        self.assertEqual(r.returncode, 1)
        self.assertEqual(list(tmpd.iterdir()), [])

    def test_l10_l11_docs_and_dockerignore(self):
        en = (KIT / "README.md").read_text(encoding="utf-8")
        th = (KIT / "README.th.md").read_text(encoding="utf-8")
        for text in (en, th):
            self.assertIn("env: bash\\r: No such file or directory", text)
            self.assertIn("bad interpreter", text)
            self.assertIn("dos2unix", text)
            self.assertIn("eol=lf", text)
            self.assertIn("--allow-plain", text)
            self.assertIn("ALLOW_PLAIN=", text)
        self.assertIn("backslash escapes", en)
        self.assertIn("!.env.production", (KIT / "templates" / "dockerignore.example").read_text())


class Syntax(unittest.TestCase):
    def test_bash_syntax(self):
        for f in (KITSH, CONVERT):
            self.assertEqual(sh(["bash", "-n", f], KIT).returncode, 0, f)
        self.assertTrue(os.access(KITSH, os.X_OK) and os.access(CONVERT, os.X_OK))




class SecretSlots(Base):
    def test_list_probes_with_access_and_reports_each_outcome(self):
        exp = {
            "en": ["[2] grp01-app-secret-2  — has a value", "[1] grp01-app-secret-1  — READY / EMPTY",
                   "[5] grp01-app-secret-5  — READY / EMPTY", "[3] grp01-app-secret-3  — NO ACCESS or NOT CREATED",
                   "[4] grp01-app-secret-4  — UNKNOWN error: ERROR: boom [redacted]"],
            "th": ["[2] grp01-app-secret-2  — มีค่าแล้ว", "[1] grp01-app-secret-1  — พร้อมใช้/ว่าง",
                   "[5] grp01-app-secret-5  — พร้อมใช้/ว่าง", "[3] grp01-app-secret-3  — ไม่มีสิทธิ์ หรือยังไม่ได้สร้าง",
                   "[4] grp01-app-secret-4  — ข้อผิดพลาดที่ไม่รู้จัก: ERROR: boom [redacted]"],
        }
        for lang, lines in exp.items():
            r = self.kit("--lang", lang, "secrets", "list")
            self.assertEqual(r.returncode, 0, r.stderr)
            for l in lines:
                self.assertIn(l, r.stdout, lang)
            self.assertNotIn("SLOT-PAYLOAD", r.stdout + r.stderr, lang)
            self.assertNotIn("second-line-hidden", r.stdout + r.stderr, lang)
            self.assertNotIn("AAAAAAAA", r.stdout + r.stderr, lang)
        calls = self.stub_calls()
        self.assertIn("versions access latest --secret=grp01-app-secret-1", calls)
        self.assertNotIn("versions list", calls)

    def test_list_destroyed_and_disabled_latest_version(self):
        exp = {"en": "[5] grp01-app-secret-5  — latest version is DISABLED/DESTROYED - add a new value with ./kit.sh secrets add 5",
               "th": "[5] grp01-app-secret-5  — version ล่าสุดถูกปิด/ทำลายแล้ว (DISABLED/DESTROYED) - เพิ่มค่าใหม่ด้วย ./kit.sh secrets add 5"}
        for state in ("DESTROYED", "DISABLED"):
            for lang, line in exp.items():
                r = self.kit("--lang", lang, "secrets", "list", env={"SL5_STATE": state})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(line, r.stdout, (state, lang))
                self.assertNotIn("grp01-app-secret-5  — UNKNOWN", r.stdout, (state, lang))
                self.assertNotIn("FAILED_PRECONDITION", r.stdout + r.stderr, (state, lang))
                self.assertNotIn("SLOT-PAYLOAD", r.stdout + r.stderr)

    def test_list_dry_run(self):
        out = self.kit("--dry-run", "secrets", "list").stdout
        for n in "12345":
            self.assertIn(f"gcloud secrets versions access latest --secret=grp01-app-secret-{n}", out)
        self.assertEqual(self.stub_calls().count("versions"), 0)
        self.assertNotIn("versions list", out)

    def test_add_from_stdin_value_goes_via_stdin_only(self):
        r = subprocess.run(["bash", KITSH, "secrets", "add", "3", "--from-stdin"], cwd=self.dir, env={**os.environ, **self.env},
                           input="my-api-key-VALUE", capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.stdin_file.read_text(), "my-api-key-VALUE")
        calls = self.stub_calls()
        self.assertIn("secrets versions add grp01-app-secret-3 --project cpe-se-course-2026 --data-file=-", calls)
        self.assertNotIn("my-api-key-VALUE", calls + r.stdout + r.stderr)

    def test_add_from_file_and_dry_run(self):
        (self.dir / "k.txt").write_text("filevalue")
        r = self.kit("secrets", "add", "1", "--from-file", "k.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--data-file=-", self.stub_calls())
        self.assertEqual(self.stdin_file.read_text(), "filevalue")
        r = self.kit("--dry-run", "secrets", "add", "4", "--from-stdin")
        self.assertIn("grp01-app-secret-4", r.stdout)
        self.assertNotIn("grp01-app-secret-4", self.stub_calls())

    def test_add_rejects_value_arguments_bad_slot_and_missing_tty(self):
        for args in (("add", "6"), ("add", "0"), ("add", "x"), ("add"), ("add", "2", "sk-live-123"), ("map", "lower", "1"), ("map", "OK", "9")):
            args = args if isinstance(args, tuple) else (args,)
            r = self.kit("secrets", *args)
            self.assertNotEqual(r.returncode, 0, args)
            self.assertNotIn("sk-live-123", self.stub_calls())
        r = self.kit("secrets", "add", "2")  # stdin is not a terminal -> must not use hidden input
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("versions add", self.stub_calls())

    def test_map_appends_and_refuses_duplicates(self):
        r = self.kit("secrets", "map", "OPENAI_API_KEY", "2")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("OPENAI_API_KEY=grp01-app-secret-2:latest\n", (self.dir / "secrets.map").read_text())
        self.assertNotEqual(self.kit("secrets", "map", "OPENAI_API_KEY", "3").returncode, 0)
        out = self.kit("--dry-run", "deploy", "--skip-migrate").stdout
        self.assertIn("OPENAI_API_KEY=grp01-app-secret-2:latest", out)

    def test_map_dry_run_does_not_write(self):
        before = (self.dir / "secrets.map").read_text()
        r = self.kit("--dry-run", "secrets", "map", "STRIPE_KEY", "5")
        self.assertIn("STRIPE_KEY=grp01-app-secret-5:latest", r.stdout)
        self.assertEqual((self.dir / "secrets.map").read_text(), before)


class SecretPrompt(Base):
    def test_hidden_prompt_via_tty_not_echoed_not_in_argv(self):
        import pty, select, time
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.dir)
            os.execvpe("bash", ["bash", KITSH, "secrets", "add", "5"], {**os.environ, **self.env})
        buf = b""; sent = False; end = time.time() + 30
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.5)
            if r:
                try: chunk = os.read(fd, 4096)
                except OSError: break
                if not chunk: break
                buf += chunk
                if not sent and b"is not shown" in buf:
                    time.sleep(0.3); os.write(fd, b"tty-secret-VALUE\n"); sent = True
        os.waitpid(pid, 0)
        self.assertTrue(sent, buf)
        self.assertNotIn(b"tty-secret-VALUE", buf)  # not echoed
        self.assertEqual(self.stdin_file.read_text(), "tty-secret-VALUE")
        self.assertNotIn("tty-secret-VALUE", self.stub_calls())


# ============================================================ bilingual (English / Thai)
THAI = re.compile(r"[฀-๿]")
IMG = "asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:" + "e" * 64


def command_part(text):
    """The gcloud/docker part of the [dry-run] lines (same in every language)."""
    out = []
    for line in text.splitlines():
        if not line.startswith("[dry-run]"):
            continue
        m = re.search(r"\b(gcloud|docker) ", line)
        if m:
            out.append(re.sub(r"kit-build-meta\.\d+", "kit-build-meta.PID", line[m.start():].split(" (")[0]))
    return out


def pty_run(args, env, cwd, prompt, answer, timeout=30):
    """Run a command in a pseudo terminal, type `answer` when `prompt` appears. -> (output, exit code)"""
    import pty, select, time
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(cwd)
        os.execvpe("bash", ["bash", KITSH, *args], env)
    buf = b""; sent = False; end = time.time() + timeout
    while time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try: chunk = os.read(fd, 4096)
            except OSError: break
            if not chunk: break
            buf += chunk
            if not sent and prompt.encode() in buf:
                time.sleep(0.3); os.write(fd, answer.encode() + b"\n"); sent = True
    _, status = os.waitpid(pid, 0)
    return buf.decode("utf-8", "replace"), os.waitstatus_to_exitcode(status), sent


class LanguageSelection(Base):
    def run_help(self, *args, env=None):
        return self.kit(*args, "help", env=env).stdout

    def test_default_is_english(self):
        out = self.run_help(env={"LANG": "C"})
        self.assertIn("Usage:", out)
        self.assertFalse(THAI.search(out))
        self.assertIn("Usage:", self.run_help(env={"LANG": "en_US.UTF-8"}))
        self.assertIn("Usage:", self.run_help(env={"LANG": ""}))

    def test_lang_flag(self):
        self.assertIn("ใช้:", self.run_help("--lang", "th"))
        self.assertIn("ใช้:", self.kit("help", "--lang", "th").stdout)  # flag after the command
        self.assertIn("ใช้:", self.kit("--lang=th", "help").stdout)
        self.assertIn("Usage:", self.run_help("--lang", "en", env={"LANG": "th_TH.UTF-8"}))

    def test_kit_lang_env(self):
        self.assertIn("ใช้:", self.run_help(env={"KIT_LANG": "th"}))
        self.assertIn("ใช้:", self.run_help(env={"KIT_LANG": "TH"}))
        self.assertIn("Usage:", self.run_help(env={"KIT_LANG": "en", "LANG": "th_TH.UTF-8"}))
        self.assertIn("Usage:", self.run_help(env={"KIT_LANG": "fr"}))  # unknown value is ignored -> English
        self.assertIn("ใช้:", self.run_help("--lang", "th", env={"KIT_LANG": "en"}))  # flag beats env

    def test_locale_autodetect(self):
        self.assertIn("ใช้:", self.run_help(env={"LANG": "th_TH.UTF-8"}))
        self.assertIn("ใช้:", self.run_help(env={"LC_MESSAGES": "th_TH.UTF-8"}))
        self.assertIn("ใช้:", self.run_help(env={"LC_ALL": "th_TH.UTF-8", "LANG": "C"}))
        self.assertIn("Usage:", self.run_help(env={"LC_ALL": "C", "LANG": "th_TH.UTF-8"}))  # LC_ALL wins

    def test_bad_lang_value(self):
        r = self.kit("--lang", "fr", "help")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--lang must be en or th", r.stderr)
        self.assertEqual(self.kit("--lang").returncode, 1)

    def test_no_args_shows_help_in_chosen_language(self):
        self.assertIn("Usage:", self.kit().stdout)
        self.assertIn("ใช้:", self.kit("--lang", "th").stdout)

    def test_help_documents_language_and_confirmation_word(self):
        en = self.run_help()
        self.assertIn("--lang en|th", en)
        self.assertIn("KIT_LANG", en)
        self.assertIn("replace", en)
        self.assertIn("replace", self.run_help("--lang", "th"))


class BothLanguages(Base):
    """The same flows in English and Thai: same commands, different text, no secrets."""
    FLOWS = [
        ("doctor",), ("build", "--tag", "v1"), ("deploy",), ("migrate",), ("env", "list"), ("env", "set", "FOO=bar", "--job"),
        ("env", "unset", "FOO"), ("secrets",), ("secrets", "list"), ("secrets", "map", "X_KEY", "3"), ("secrets", "add", "2", "--from-stdin"),
        ("logs", "job", "--follow"), ("status",), ("open",), ("rollback",),
    ]

    def test_dry_run_flows_same_commands_in_both_languages(self):
        for flow in self.FLOWS:
            en = self.kit("--dry-run", "--lang", "en", *flow)
            th = self.kit("--dry-run", "--lang", "th", *flow)
            self.assertEqual(en.returncode, 0, (flow, en.stderr))
            self.assertEqual(th.returncode, 0, (flow, th.stderr))
            e_all, t_all = en.stdout + en.stderr, th.stdout + th.stderr
            self.assertEqual(command_part(e_all), command_part(t_all), flow)
            self.assertFalse(THAI.search(e_all), (flow, e_all))
            self.assertTrue(THAI.search(t_all), (flow, t_all))
        self.assertEqual(self.stub_calls(), "")

    def test_dry_run_labels_localized(self):
        en = self.kit("--dry-run", "--lang", "en", "doctor").stdout
        th = self.kit("--dry-run", "--lang", "th", "doctor").stdout
        self.assertIn("== Checking the setup for team 'grp01'", en)
        self.assertIn("check can see Cloud Run service 'grp01'", en)
        self.assertIn("(dry-run: nothing was really checked)", en)
        self.assertIn("== ตรวจระบบสำหรับกลุ่ม 'grp01'", th)
        self.assertIn("ตรวจ เห็น Cloud Run service 'grp01'", th)
        self.assertIn("[dry-run] No real command is run", self.kit("--dry-run", "--lang", "en", "status").stdout)
        self.assertIn("[dry-run] ไม่รันคำสั่งจริง", self.kit("--dry-run", "--lang", "th", "status").stdout)

    def test_real_run_status_and_secrets_in_both_languages(self):
        en = self.kit("--lang", "en", "secrets")
        th = self.kit("--lang", "th", "secrets")
        self.assertIn("[readable]", en.stdout)
        self.assertIn("[อ่านได้]", th.stdout)
        self.assertIn("Notes", en.stdout)
        self.assertIn("หมายเหตุ", th.stdout)
        self.assertIn("grp01-app-secret-1..5", en.stdout + th.stdout)
        for lang in ("en", "th"):
            for flow in (("secrets",), ("doctor",), ("status",), ("env", "list"), ("secrets", "list")):
                r = self.kit("--lang", lang, *flow)
                self.assertNotIn(SECRET_VALUE, r.stdout + r.stderr, (lang, flow))
        self.assertIn("[1] grp01-app-secret-1  — READY / EMPTY", self.kit("--lang", "en", "secrets", "list").stdout)
        self.assertIn("[2] grp01-app-secret-2  — มีค่าแล้ว", self.kit("--lang", "th", "secrets", "list").stdout)
        self.assertIn("URL:", self.kit("--lang", "th", "status").stdout)
        self.assertIn("https://grp01-xyz.a.run.app", self.kit("--lang", "th", "status").stdout)

    def test_doctor_real_run_tags(self):
        en = self.kit("--lang", "en", "doctor")
        th = self.kit("--lang", "th", "doctor")
        self.assertEqual(en.returncode, 0, en.stdout + en.stderr)
        self.assertEqual(th.returncode, 0, th.stdout + th.stderr)
        self.assertIn("[PASS] gcloud found", en.stdout)
        self.assertIn("[ผ่าน] พบ gcloud", th.stdout)
        self.assertIn("logged in to gcloud as: me@gmail.com", en.stdout)
        self.assertIn("ล็อกอิน gcloud แล้วด้วย: me@gmail.com", th.stdout)
        self.assertIn("ready to use", en.stdout)
        self.assertIn("พร้อมใช้งาน", th.stdout)

    def test_doctor_failure_hint_both_languages(self):
        (self.bin / "gcloud").write_text(STUB.replace('*"auth list"*) echo "me@gmail.com" ;;', '*"auth list"*) ;;'))
        en = self.kit("--lang", "en", "doctor")
        th = self.kit("--lang", "th", "doctor")
        self.assertEqual((en.returncode, th.returncode), (1, 1))
        self.assertIn("[FAIL] not logged in -> run: gcloud auth login", en.stdout)
        self.assertIn("[ไม่ผ่าน] ยังไม่ได้ล็อกอิน -> รัน: gcloud auth login", th.stdout)

    def test_error_messages(self):
        cases = [
            (("bogus",), "unknown command 'bogus'", "ไม่รู้จักคำสั่ง 'bogus'"),
            (("--dry-run", "logs", "--severity", "bogus"), "--severity must be", "--severity ต้องเป็น"),
            (("--dry-run", "logs", "--since", "x"), "--since must look like", "--since เช่น"),
            (("--dry-run", "rollback", "--to", "other-00001"), "does not belong to service grp01", "ไม่ใช่ของ service grp01"),
            (("--dry-run", "env", "set", "DB_PASSWORD=hunter2"), "looks like a secret", "ดูเหมือนความลับ"),
            (("--dry-run", "env", "set", "PORT=1"), "is set by Cloud Run itself", "เป็นตัวแปรที่ Cloud Run กำหนดเอง"),
            (("--dry-run", "env", "set"), "usage: ./kit.sh env set", "ใช้: ./kit.sh env set"),
            (("--dry-run", "env", "nope"), "the subcommand must be", "คำสั่งย่อยต้องเป็น"),
            (("secrets", "add", "9"), "the slot number must be 1-5", "เลข slot ต้องเป็น 1-5"),
            (("secrets", "add", "2", "sk-live-123"), "never put a secret value as an argument", "ห้ามใส่ค่าความลับเป็นอาร์กิวเมนต์"),
            (("secrets", "add", "2"), "there is no terminal for hidden input", "ไม่มี terminal สำหรับพิมพ์ค่าแบบซ่อน"),
            (("secrets", "map", "lower", "1"), "ENV_NAME must be uppercase", "ENV_NAME ต้องเป็นตัวพิมพ์ใหญ่"),
            (("secrets", "nope"), "the subcommand must be list", "คำสั่งย่อยต้องเป็น list"),
            (("deploy",), "no image yet", "ยังไม่มี image"),
            (("--dry-run", "build", "--tag"), "--tag needs a value", "--tag ต้องมีค่า"),
            (("--dry-run", "build", "--bad"), "build: unknown option --bad", "build: ไม่รู้จักตัวเลือก --bad"),
            (("--dry-run", "build", "--tag", "bad tag!"), "is not valid", "ไม่ถูกต้อง"),
            (("--env-file",), "--env-file needs a value", "--env-file ต้องมีค่า"),
        ]
        for args, en_text, th_text in cases:
            en = self.kit("--lang", "en", *args)
            th = self.kit("--lang", "th", *args)
            self.assertNotEqual(en.returncode, 0, args)
            self.assertEqual(en.returncode, th.returncode, args)
            self.assertIn("Error: ", en.stderr, args)
            self.assertIn("ผิดพลาด: ", th.stderr, args)
            self.assertIn(en_text, en.stderr, (args, en.stderr))
            self.assertIn(th_text, th.stderr, (args, th.stderr))
            self.assertNotIn("hunter2", en.stderr + th.stderr.replace("DB_PASSWORD=hunter2", ""))
        self.assertEqual(self.stub_calls(), "")

    def test_missing_config_errors(self):
        (self.dir / "resources.env").unlink()
        en = self.kit("--lang", "en", "--dry-run", "status")
        th = self.kit("--lang", "th", "--dry-run", "status")
        self.assertIn("resources.env not found", en.stderr)
        self.assertIn("ไม่พบ resources.env", th.stderr)
        (self.dir / "resources.env").write_text("PROJECT_ID=cpe-se-course-2026\n")
        self.assertIn("PREFIX is required", self.kit("--lang", "en", "--dry-run", "status").stderr)
        self.assertIn("ต้องกรอก PREFIX", self.kit("--lang", "th", "--dry-run", "status").stderr)
        (self.dir / "resources.env").write_text("PREFIX=grp01\nBOGUS=1\n")
        self.assertIn("Warning: unknown variable BOGUS", self.kit("--lang", "en", "--dry-run", "status").stderr)
        self.assertIn("คำเตือน: ไม่รู้จักตัวแปร BOGUS", self.kit("--lang", "th", "--dry-run", "status").stderr)
        (self.dir / "resources.env").write_text("PREFIX=grp01\nnot a pair\n")
        self.assertIn("missing \"=\" sign", self.kit("--lang", "en", "--dry-run", "status").stderr)
        self.assertIn("ไม่มีเครื่องหมาย =", self.kit("--lang", "th", "--dry-run", "status").stderr)

    def test_prefix_guard_message_both_languages(self):
        self.edit_resources("SERVICE_NAME=otherteam\n")
        en = self.kit("--lang", "en", "--dry-run", "deploy")
        th = self.kit("--lang", "th", "--dry-run", "deploy")
        for r in (en, th):
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("gcloud run", r.stdout)
        self.assertIn("SERVICE_NAME = 'otherteam' does not belong to your team (it must be 'grp01' or start with 'grp01-')", en.stderr)
        self.assertIn("kit.sh never touches resources of other teams", en.stderr)
        self.assertIn("SERVICE_NAME = 'otherteam' ไม่ใช่ของกลุ่มคุณ (ต้องเป็น 'grp01' หรือขึ้นต้นด้วย 'grp01-')", th.stderr)
        self.assertEqual(self.stub_calls(), "")
        # all guards stay active in Thai as well
        for extra in ("MIGRATE_JOB_NAME=other-migrate\n", "REGISTRY=zzz\n", "RUNTIME_SA=other-runner@cpe-se-course-2026.iam.gserviceaccount.com\n",
                      "SQL_CONNECTION_NAME=cpe-se-course-2026:asia-southeast1:other-pg\n"):
            self.edit_resources(extra)
            self.assertEqual(self.kit("--lang", "th", "--dry-run", "deploy").returncode, 1, extra)
        self.edit_resources("")
        (self.dir / "secrets.map").write_text("X=other-database-url:latest\n")
        r = self.kit("--lang", "th", "--dry-run", "deploy")
        self.assertEqual(r.returncode, 1)
        self.assertIn("secrets.map บรรทัดที่ 1: secret ของ X ต้องเป็น 'grp01'", r.stderr)
        self.assertIn("secrets.map line 1: the secret of X must be 'grp01'", self.kit("--lang", "en", "--dry-run", "deploy").stderr)

    def test_migration_failure_message(self):
        (self.bin / "gcloud").write_text(STUB.replace('esac\nexit 0', 'esac\ncase "$*" in *"jobs execute"*) exit 1;; esac\nexit 0'))
        en = self.kit("--lang", "en", "--yes", "deploy", "--image", IMG)
        th = self.kit("--lang", "th", "--yes", "deploy", "--image", IMG)
        self.assertEqual((en.returncode, th.returncode), (1, 1))
        self.assertIn('migration job "grp01-migrate" failed - stopping, not deploying', en.stderr)
        self.assertIn('migration job "grp01-migrate" ล้มเหลว', th.stderr)
        for r in (en, th):
            self.assertIn("./kit.sh logs job --severity ERROR", r.stderr)
        self.assertNotIn("run services update", self.stub_calls())

    def test_init_and_hints(self):
        (self.dir / "Dockerfile").unlink()
        en = self.kit("--lang", "en", "init", "--stack", "node")
        self.assertIn("created ./Dockerfile from the node template", en.stdout)
        self.assertIn("init never overwrites it. To start over: delete it (rm Dockerfile)", self.kit("--lang", "en", "init", "--stack", "node").stdout)
        th = self.kit("--lang", "th", "init", "--stack", "node")
        self.assertIn("มี Dockerfile อยู่แล้ว — init ไม่เขียนทับเด็ดขาด", th.stdout)
        self.assertIn("MIGRATE_COMMAND=npx prisma migrate deploy", en.stdout)
        self.assertIn("ตัวอย่าง MIGRATE_COMMAND สำหรับ node", th.stdout)
        r = self.kit("--lang", "th", "--dry-run", "migrate")  # no MIGRATE_COMMAND
        (self.dir / "resources.env").write_text(RESOURCES.replace("MIGRATE_COMMAND=alembic upgrade head\n", ""))
        for lang, text in (("en", "MIGRATE_COMMAND is not set"), ("th", "ยังไม่ได้ตั้ง MIGRATE_COMMAND")):
            r = self.kit("--lang", lang, "--dry-run", "migrate")
            self.assertEqual(r.returncode, 1)
            self.assertIn(text, r.stderr)

    def test_build_dry_run_messages(self):
        en = self.kit("--lang", "en", "--dry-run", "build", "--tag", "v1")
        th = self.kit("--lang", "th", "--dry-run", "build", "--tag", "v1")
        self.assertIn("next step: ./kit.sh deploy", en.stdout)
        self.assertIn("ขั้นต่อไป: ./kit.sh deploy", th.stdout)
        self.assertIn("image: asia-southeast1-docker.pkg.dev/cpe-se-course-2026/grp01/grp01@sha256:<DIGEST>   (tag: v1)", en.stdout)
        self.assertIn("docker buildx build --platform linux/amd64", th.stdout)

    def test_deploy_dry_run_placeholder_digest_both_languages(self):
        for lang, ph in (("en", "<DIGEST_FROM_BUILD>"), ("th", "<DIGEST_FROM_BUILD>")):
            out = self.kit("--lang", lang, "--dry-run", "deploy", "--skip-migrate").stdout
            self.assertIn(ph, out)

    def test_dry_run_replace_env_prompt_label(self):
        en = self.kit("--lang", "en", "--dry-run", "deploy", "--skip-migrate", "--replace-env").stdout
        th = self.kit("--lang", "th", "--dry-run", "deploy", "--skip-migrate", "--replace-env").stdout
        self.assertIn("(would ask for confirmation) --replace-env will REPLACE", en)
        self.assertIn("(จะถามยืนยัน) --replace-env จะ", th)

    def test_replace_env_real_run_no_tty_refuses_both_languages(self):
        for lang, text in (("en", "a manual confirmation is needed but there is no terminal"), ("th", "ต้องยืนยันด้วยตนเองแต่ไม่มี terminal")):
            r = self.kit("--lang", lang, "--yes", "deploy", "--skip-migrate", "--replace-env", "--image", IMG)
            self.assertEqual(r.returncode, 1)
            self.assertIn(text, r.stderr)
        self.assertNotIn("services update", self.stub_calls())

    def test_logs_rollback_status_messages(self):
        self.assertIn("latest log of service (newest first):", self.kit("--lang", "en", "--dry-run", "logs").stdout)
        self.assertIn("log ล่าสุดของ service (ใหม่สุดอยู่บน):", self.kit("--lang", "th", "--dry-run", "logs").stdout)
        self.assertIn("--follow would poll every 5 seconds", self.kit("--lang", "en", "--dry-run", "logs", "-f").stdout)
        self.assertIn("--follow จะวนอ่านทุก 5 วินาที", self.kit("--lang", "th", "--dry-run", "logs", "-f").stdout)
        self.assertIn("<REVISION_PREVIOUS>", self.kit_all("--lang", "en", "--dry-run", "rollback"))
        self.assertIn("<REVISION_PREVIOUS>", self.kit_all("--lang", "th", "--dry-run", "rollback"))
        self.assertIn("will move 100% of traffic", self.kit("--lang", "en", "--dry-run", "rollback", "--to", "grp01-001").stdout)
        self.assertIn("จะย้าย traffic 100% ไป revision", self.kit("--lang", "th", "--dry-run", "rollback", "--to", "grp01-001").stdout)

    def test_secrets_map_and_add_messages(self):
        out = self.kit("--lang", "en", "secrets", "map", "NEW_KEY", "4").stdout
        self.assertIn("added to", out)
        self.assertIn("so the app can see the value", out)
        out = self.kit("--lang", "th", "secrets", "map", "OTHER_KEY", "5").stdout
        self.assertIn("เพิ่มใน", out)
        r = self.kit("--lang", "th", "secrets", "map", "OTHER_KEY", "5")
        self.assertIn("มี OTHER_KEY อยู่แล้ว", r.stderr)
        r = self.kit("--lang", "en", "secrets", "map", "OTHER_KEY", "5")
        self.assertIn("already has OTHER_KEY", r.stderr)
        (self.dir / "k.txt").write_text("v")
        self.assertIn("added a new version to grp01-app-secret-1", self.kit("--lang", "en", "secrets", "add", "1", "--from-file", "k.txt").stdout)
        self.assertIn("เพิ่ม version ใหม่ให้ grp01-app-secret-1", self.kit("--lang", "th", "secrets", "add", "1", "--from-file", "k.txt").stdout)

    def test_lang_env_variants_on_a_real_flow(self):
        for env, thai in (({"LANG": "C"}, False), ({"LANG": "th_TH.UTF-8"}, True), ({"KIT_LANG": "th"}, True), ({"KIT_LANG": "en", "LANG": "th_TH.UTF-8"}, False)):
            r = self.kit("--dry-run", "deploy", env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(bool(THAI.search(r.stdout + r.stderr)), thai, env)
            self.assertIn("gcloud run services update grp01 ", r.stdout)


class ConfirmationPrompts(Base):
    def env_for(self, lang):
        e = dict(os.environ)
        for k in ("LC_ALL", "LC_MESSAGES", "LANG", "KIT_LANG"):
            e.pop(k, None)
        e.update(self.env); e["LANG"] = "C"
        return e

    def test_replace_env_typed_word_is_the_same_in_both_languages(self):
        prompts = {"en": 'Type "replace" to confirm', "th": 'พิมพ์ "replace" เพื่อยืนยัน'}
        for lang in ("en", "th"):
            self.log.write_text("")
            out, code, sent = pty_run(["--lang", lang, "deploy", "--skip-migrate", "--replace-env", "--image", IMG], self.env_for(lang), self.dir, prompts[lang], "replace")
            self.assertTrue(sent, (lang, out))
            self.assertEqual(code, 0, (lang, out))
            self.assertIn("--set-env-vars", self.stub_calls(), lang)
            self.assertIn("--set-secrets", self.stub_calls(), lang)
            self.assertNotIn(SECRET_VALUE, out)

    def test_replace_env_wrong_word_cancels_in_both_languages(self):
        for lang, text in (("en", "cancelled (you did not type replace)"), ("th", "ยกเลิก (ไม่ได้พิมพ์ replace)")):
            self.log.write_text("")
            out, code, sent = pty_run(["--lang", lang, "deploy", "--skip-migrate", "--replace-env", "--image", IMG], self.env_for(lang), self.dir, "replace", "yes")
            self.assertTrue(sent, (lang, out))
            self.assertEqual(code, 1, (lang, out))
            self.assertIn(text, out)
            self.assertNotIn("services update", self.stub_calls())

    def test_yes_no_prompt_accepts_yes_in_both_languages(self):
        for lang, ans, ok in (("en", "yes", True), ("th", "yes", True), ("th", "y", True), ("en", "no", False), ("th", "", False)):
            self.log.write_text("")
            out, code, sent = pty_run(["--lang", lang, "env", "unset", "FOO"], self.env_for(lang), self.dir, "[y/N]", ans)
            self.assertTrue(sent, (lang, out))
            self.assertEqual(code, 0 if ok else 1, (lang, ans, out))
            self.assertEqual("--remove-env-vars FOO" in self.stub_calls(), ok, (lang, ans))
            if not ok:
                self.assertIn("cancelled" if lang == "en" else "ยกเลิก", out)
        self.assertIn("will remove env: FOO from the service", out if False else self.kit("--lang", "en", "--dry-run", "env", "unset", "FOO").stdout)
        self.assertIn("จะลบ env: FOO ออกจาก service", self.kit("--lang", "th", "--dry-run", "env", "unset", "FOO").stdout)

    def test_hidden_secret_prompt_text_both_languages(self):
        for lang, marker in (("en", "is not shown"), ("th", "พิมพ์แล้วไม่แสดงบนจอ")):
            self.stdin_file.write_text("")
            out, code, sent = pty_run(["--lang", lang, "secrets", "add", "3"], self.env_for(lang), self.dir, marker, "tty-secret-VALUE")
            self.assertTrue(sent, (lang, out))
            self.assertEqual(code, 0, out)
            self.assertNotIn("tty-secret-VALUE", out)
            self.assertEqual(self.stdin_file.read_text(), "tty-secret-VALUE")


class MessageCatalog(unittest.TestCase):
    SCRIPTS = (KITSH, CONVERT)

    def listing(self, script):
        r = sh(["bash", script, "--list-messages"], KIT)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [l.split() for l in r.stdout.splitlines() if l.strip()]
        self.assertGreater(len(rows), 20)
        return {k: dict(p.split("=") for p in rest) for k, *rest in rows}

    def test_every_key_exists_in_both_languages(self):
        for script in self.SCRIPTS:
            for key, langs in self.listing(script).items():
                self.assertEqual(langs, {"en": "1", "th": "1"}, (script, key))

    def test_keys_used_in_code_are_all_cataloged(self):
        for script in self.SCRIPTS:
            text = Path(script).read_text(encoding="utf-8")
            used = set(re.findall(r"\bM_[A-Z0-9_]+\b", text))
            self.assertEqual(used, set(self.listing(script)), script)

    def test_catalog_entries_are_defined_per_language(self):
        # case labels in msg_en and msg_th must be the same set
        for script in self.SCRIPTS:
            text = Path(script).read_text(encoding="utf-8")
            en = text.split("msg_en() {")[1].split("\nmsg_th() {")[0]
            th = text.split("msg_th() {")[1].split("\nT() {")[0] if "\nT() {" in text else text.split("msg_th() {")[1]
            lab = lambda t: set(re.findall(r"^    (M_[A-Z0-9_]+)\)", t, re.M))
            self.assertEqual(lab(en), lab(th), script)
            self.assertEqual(lab(en), set(self.listing(script)), script)

    def test_no_thai_outside_catalog_in_scripts(self):
        # all Thai user text must live inside msg_th (and the fixed bilingual file comments of from-portal-json.sh)
        for script in self.SCRIPTS:
            text = Path(script).read_text(encoding="utf-8")
            before, rest = text.split("msg_th() {", 1)
            after = rest.split("\n}\n", 1)[1]
            for part in (before, after):
                for line in part.splitlines():
                    if THAI.search(line):
                        self.assertTrue(script == CONVERT and ('"# ' in line or line.lstrip().startswith('#')), (script, line))

    def test_format_strings_match_argument_counts_between_languages(self):
        for script in self.SCRIPTS:
            text = Path(script).read_text(encoding="utf-8")
            en = text.split("msg_en() {")[1].split("\nmsg_th() {")[0]
            th = text.split("msg_th() {")[1].split("\nT() {")[0] if "\nT() {" in text else text.split("msg_th() {")[1]
            grab = lambda t: {m.group(1): m.group(2) for m in re.finditer(r"^    (M_[A-Z0-9_]+)\) printf '%s' '(.*?)' ;;$", t, re.M | re.S)}
            ge, gt = grab(en), grab(th)
            self.assertEqual(set(ge), set(gt), script)
            count = lambda s: len(re.findall(r"%s", s.replace("%%", "")))
            for k in ge:
                self.assertEqual(count(ge[k]), count(gt[k]), (script, k))


class FromPortalJsonLanguages(FromPortalJson):
    def conv(self, lang, data, *extra, raw=None, env=None):
        f = self.dir / "in.json"
        f.write_text(raw if raw is not None else json.dumps(data))
        return sh(["bash", CONVERT, str(f), *extra], self.dir, {**(env or {}), **({"KIT_LANG": lang} if lang else {})})

    def test_errors_in_both_languages(self):
        d = json.loads(json.dumps(SAMPLE)); del d["resources"]["migration_job"]; del d["prefix"]
        en, th = self.conv("en", d), self.conv("th", d)
        self.assertIn("Error: the JSON is missing required keys: prefix, resources.migration_job", en.stderr)
        self.assertIn("ผิดพลาด: ใน JSON ไม่มี key ที่จำเป็น: prefix, resources.migration_job", th.stderr)
        self.assertEqual((en.returncode, th.returncode), (1, 1))
        self.assertIn("If your team is not activated yet", en.stderr)
        self.assertIn("ถ้ากลุ่มยังไม่ถูก activate", th.stderr)
        self.assertIn("cannot read the JSON file", self.conv("en", None, raw="{bad").stderr)
        self.assertIn("อ่านไฟล์ JSON ไม่ได้", self.conv("th", None, raw="{bad").stderr)
        self.assertIn("the key 'resources' is not in the JSON", self.conv("en", {"prefix": "grp01"}).stderr)
        self.assertIn("ไม่พบ key 'resources'", self.conv("th", {"prefix": "grp01"}).stderr)
        d = json.loads(json.dumps(SAMPLE)); d["resources"]["cloud_run_service"] = "grp01; rm"
        self.assertIn("has unexpected characters", self.conv("en", d).stderr)
        self.assertIn("มีอักขระที่ไม่คาดคิด", self.conv("th", d).stderr)

    def test_usage_errors_exit_2_in_both_languages(self):
        for lang, text in (("en", "file not found"), ("th", "ไม่พบไฟล์")):
            r = sh(["bash", CONVERT, str(self.dir / "nope.json")], self.dir, {"KIT_LANG": lang})
            self.assertEqual(r.returncode, 2)
            self.assertIn(text, r.stderr)
        self.assertIn("usage:", sh(["bash", CONVERT], self.dir).stderr)
        self.assertIn("ใช้:", sh(["bash", CONVERT, "--lang", "th"], self.dir).stderr)
        self.assertEqual(sh(["bash", CONVERT, "--lang", "xx", "a.json"], self.dir).returncode, 2)

    def test_exists_and_created_messages(self):
        r = self.conv("en", SAMPLE)
        self.assertIn("created resources.env - check STACK", r.stderr)
        self.assertIn("already exists (use --force", self.conv("en", SAMPLE).stderr)
        self.assertIn("มี resources.env อยู่แล้ว", self.conv("th", SAMPLE).stderr)
        self.assertIn("สร้าง resources.env แล้ว", self.conv("th", SAMPLE, "--force").stderr)

    def test_preview_warning_and_help(self):
        d = dict(SAMPLE, created_in_google_cloud=False, mode="preview")
        self.assertIn("Warning: this JSON is a plan (preview)", self.conv("en", d, "-o", "-").stderr)
        self.assertIn("คำเตือน: JSON นี้เป็นแผน (preview)", self.conv("th", d, "-o", "-").stderr)
        self.assertIn("usage:", sh(["bash", CONVERT, "--help"], self.dir).stdout)
        self.assertIn("ใช้:", sh(["bash", CONVERT, "--help", "--lang", "th"], self.dir).stdout)
        self.assertIn("ใช้:", sh(["bash", CONVERT, "--help"], self.dir, {"LANG": "th_TH.UTF-8"}).stdout)

    def test_values_are_identical_in_both_languages(self):
        a = self.conv("en", SAMPLE, "-o", "-").stdout
        b = self.conv("th", SAMPLE, "-o", "-").stdout
        values = lambda t: [l for l in t.splitlines() if l and not l.startswith("#")]
        self.assertEqual(values(a), values(b))
        self.assertIn("PREFIX=grp01", values(a))


class DocsAndExamples(unittest.TestCase):
    def test_readmes_are_cross_linked(self):
        en = (KIT / "README.md").read_text(encoding="utf-8")
        th = (KIT / "README.th.md").read_text(encoding="utf-8")
        self.assertIn("(README.th.md)", en.split("\n\n", 2)[1])
        self.assertIn("ภาษาไทย", en.split("\n\n", 2)[1])
        self.assertIn("(README.md)", th.split("\n\n", 2)[1])
        self.assertIn("English", th.split("\n\n", 2)[1])
        self.assertFalse(THAI.search(en.replace("ภาษาไทย", "")), "README.md must be English")
        for needle in ("Troubleshooting", "--lang", "KIT_LANG", "replace", "amd64", "PERMISSION_DENIED", "terminal"):
            self.assertIn(needle, en, needle)
        for needle in ("--lang", "KIT_LANG", "replace", "amd64", "PERMISSION_DENIED", "terminal"):
            self.assertIn(needle, th, needle)

    def test_example_files_and_templates_are_english(self):
        files = [KIT / n for n in ("resources.example.env", "app.env.example", "secrets.map.example")] + sorted((KIT / "templates").iterdir())
        for f in files:
            self.assertFalse(THAI.search(f.read_text(encoding="utf-8")), f"{f.name} should have English comments")

    def test_readme_lists_all_subcommands(self):
        en = (KIT / "README.md").read_text(encoding="utf-8")
        for cmd in ("doctor", "init", "build", "migrate", "deploy", "env list", "secrets", "logs", "status", "open", "rollback"):
            self.assertIn("`" + cmd, en, cmd)
        for slot in ("app-secret-1", "1-5"):
            self.assertIn(slot, en)


if __name__ == "__main__":
    unittest.main()
