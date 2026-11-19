#!/usr/bin/env bash
if grep -q $'\r' "${BASH_SOURCE[0]}" 2>/dev/null; then printf 'Error: this file has Windows line endings (CRLF). Fix: dos2unix kit.sh from-portal-json.sh   or   sed -i "s/\\r$//" kit.sh from-portal-json.sh   (see README, Windows section)\n' >&2; exit 1; fi #
# ==============================================================================
# kit.sh - deploy tool for student projects (build / migrate / deploy / ...)
# Works with any stack as long as you have a Dockerfile. No GitHub needed.
# Needs only: bash, gcloud, docker (docker only for the build command)
# Help:  ./kit.sh help     and read README.md (English) or README.th.md (Thai)
#
# Language of messages: --lang en|th, else env KIT_LANG, else Thai if
# LC_ALL / LC_MESSAGES / LANG starts with "th", else English (default).
# All user-facing text is in the message catalog (msg_en / msg_th) below.
# ==============================================================================
set -eo pipefail

KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=0
ASSUME_YES=0
ENV_FILE=""
APP_ENV_FILE=""
SECRETS_MAP_FILE=""
STACK_ARG=""
ALLOW_MIN=0
KV_ARR=()         # checked KEY=VALUE lines of the last file read (set by kv_lines)
KV_LNO=()         # the line numbers of KV_ARR
KV_ERR=""         # error text when kv_lines fails
STATE_DIR="${KIT_STATE_DIR:-.kit-state}"
ALLOW_PLAIN_FLAGS=""   # names given with --allow-plain (space separated)
APP_ALLOW_PLAIN=""     # names from an ALLOW_PLAIN= line in app.env
# How the user started this script (shown in messages instead of a fixed "./kit.sh"):
# ./project-kit/kit.sh, project-kit/kit.sh -> ./project-kit/kit.sh ; kit.sh from PATH stays kit.sh. KIT_CMD overrides (tests).
if [ -z "${KIT_CMD:-}" ]; then
  case "$0" in
    /*|./*|../*) KIT_CMD="$0" ;;
    */*) KIT_CMD="./$0" ;;
    *) if [ -f "./$0" ]; then KIT_CMD="./$0"; else KIT_CMD="$0"; fi ;;
  esac
fi
KIT_LANG_ACTIVE=en

# =============================================================== message catalog
# Placeholders inside commands (the PH keys) are the same in both languages on purpose.
# Format strings for printf. Use %s for arguments, %% for a literal percent sign,
# \n for a new line and \047 for a single quote. No associative arrays (bash 3.2).
# Every key must exist in BOTH msg_en and msg_th (checked by the tests with
# ./kit.sh --list-messages).
MSG_KEYS="M_ERR M_WARN M_TAG_PASS M_TAG_FAIL M_TAG_WARN
M_DRY_NOTICE M_DRY_CONFIRM M_DRY_CHECK M_DRY_CHECK_SECRET M_DRY_FILE_ADD M_DRY_DIGEST M_DRY_DISCARDED M_DRY_DONE M_DRY_ASK_HIDDEN
M_NEEDS_VALUE M_BAD_LANG M_UNKNOWN_CMD
M_NEED_TTY_CONFIRM M_CONFIRM_TYPE M_CANCELLED_WORD M_CONFIRM_YN M_CANCELLED
M_KV_NOEQ M_KV_BADNAME M_FILE_NOT_FOUND
M_NO_RESOURCES_ENV M_UNKNOWN_VAR M_BAD_STACK M_NEED_PREFIX M_BAD_PREFIX M_BAD_PROJECT M_BAD_REGION
M_GUARD M_RUNTIME_SA_PROJECT M_SQL_FORMAT M_BAD_IMAGE_NAME M_BAD_PORT M_BAD_CPU M_BAD_MEMORY M_BAD_MIN M_BAD_MAX M_MIN_GT_MAX
M_CPU_TOO_HIGH M_MEMORY_TOO_HIGH M_MIN_NOT_ZERO M_MIN_CONFIRM
M_SECRETISH M_SECRETISH_VALUE M_ALLOW_PLAIN_BAD M_PORT_RESERVED M_URL_PASSWORD M_DELIM M_DELIM_MIGRATE M_SECRETS_MAP_FORMAT M_SECRETS_MAP_GUARD
M_PH_DIGEST M_PH_LASTTIME M_PH_PREV_REV M_NO_IMAGE M_IMAGE_NOT_IN_REGISTRY M_JOB_LOGS_HINT
M_HELP
M_INIT_NEED_STACK M_INIT_CUSTOM M_INIT_BAD_STACK M_INIT_NO_TEMPLATE M_INIT_DOCKERFILE_EXISTS M_INIT_DOCKERFILE_CREATED M_INIT_IGNORE_EXISTS M_INIT_IGNORE_CREATED M_INIT_GITIGNORE_CREATED M_INIT_GITIGNORE_UPDATED
M_HINT_HEADER M_HINT_NODE M_HINT_PYTHON M_HINT_JAVA M_HINT_GO M_HINT_STATIC M_HINT_OTHER
M_DR_TITLE M_DR_GCLOUD_OK M_DR_GCLOUD_MISSING M_DR_DOCKER_OK M_DR_BUILDX_MISSING M_DR_DAEMON_DOWN M_DR_DOCKER_MISSING M_DR_STOP_NO_GCLOUD
M_DR_LOGIN_OK M_DR_LOGIN_NO M_DR_REGISTRY_OK M_DR_REGISTRY_NO
M_DR_SVC M_DR_SVC_HINT M_DR_JOB M_DR_JOB_HINT M_DR_REPO M_DR_REPO_HINT M_DR_SECRET_OK M_DR_SECRET_WARN
M_DR_DOCKERFILE_OK M_DR_DOCKERFILE_WARN M_DR_PROBLEMS M_DR_READY
M_BUILD_IGNORE_TRAP M_BUILD_BAD_OPT M_BAD_TAG M_BUILD_NO_DOCKERFILE_WARN M_BUILD_NO_DOCKERFILE M_NO_DOCKER M_NO_DIGEST M_BUILD_IMAGE M_BUILD_NEXT
M_MIG_NO_CMD M_MIG_SKIP M_MIG_FAILED M_MIG_BAD_OPT M_MIG_DONE
M_DEP_BAD_OPT M_DEP_REPLACE_EMPTY M_DEP_REPLACE_CONFIRM M_DEP_SKIP M_DEP_DONE M_DEP_NEXT
M_ENV_LIST_SVC M_ENV_LIST_JOB M_ENV_SET_USAGE M_ENV_NEED_KV M_ENV_BAD_NAME M_ENV_UNSET_USAGE M_ENV_UNSET_CONFIRM M_ENV_UNSET_CONFIRM_JOB M_TRAFFIC_PINNED M_ENV_BAD_SUB
M_SLOT_BAD M_SL_TITLE M_SL_HAS M_SL_EMPTY M_SL_NONE M_SL_DISABLED M_SL_UNKNOWN M_SL_HOW_ADD M_SL_HOW_MAP
M_ADD_FILE_NEEDS_NAME M_ADD_UNKNOWN M_ADD_NO_FILE M_ADD_STDIN_TTY M_ADD_NO_TTY M_ADD_PROMPT M_ADD_EMPTY M_ADD_DONE
M_MAP_BAD_ENV M_MAP_EXISTS M_MAP_SLOT_LABEL M_MAP_DONE
M_SEC_BAD_SUB M_SEC_MAPPED M_SEC_EMPTY M_SEC_CHECK M_SEC_READABLE M_SEC_UNREADABLE M_SEC_ATTACHED M_SECRETS_NOTE
M_LOGS_BAD_OPT M_LOGS_BAD_SEV M_LOGS_BAD_LIMIT M_LOGS_BAD_SINCE M_LOGS_LATEST M_LOGS_FOLLOWING M_LOGS_FOLLOW_DRY M_LOGS_FOLLOW_FAIL M_LOGS_FOLLOW_GIVEUP
M_ST_URL M_ST_REV M_ST_IMAGE M_ST_ENV M_ST_EXEC M_ST_EXEC_NONE M_ST_SVC M_ST_JOB M_UNREADABLE
M_OPEN_NO_URL
M_RB_BAD_OPT M_RB_NO_PREV M_RB_UNKNOWN M_RB_NOT_YOURS M_RB_CONFIRM M_RB_DONE"

msg_en() {
  case "$1" in
    M_ERR) printf '%s' 'Error:' ;;
    M_WARN) printf '%s' 'Warning:' ;;
    M_TAG_PASS) printf '%s' '[PASS]' ;;
    M_TAG_FAIL) printf '%s' '[FAIL]' ;;
    M_TAG_WARN) printf '%s' '[WARN]' ;;
    M_DRY_NOTICE) printf '%s' 'No real command is run. Only what would be done is shown.' ;;
    M_DRY_CONFIRM) printf '%s' '(would ask for confirmation) %s' ;;
    M_DRY_CHECK) printf '%s' 'check %s: ' ;;
    M_DRY_CHECK_SECRET) printf '%s' 'check read of secret %s: gcloud secrets versions access latest --secret=%s (output is discarded, not shown)' ;;
    M_DRY_FILE_ADD) printf '%s' 'would add this line to %s: %s' ;;
    M_DRY_DIGEST) printf '%s' 'would read the digest from the buildx metadata (fallback: gcloud artifacts docker images describe %s --project %s --format=\047value(image_summary.digest)\047)' ;;
    M_DRY_DISCARDED) printf '%s' 'output discarded' ;;
    M_DRY_DONE) printf '%s' '(dry-run: nothing was really checked)' ;;
    M_DRY_ASK_HIDDEN) printf '%s' '(would ask for the value with hidden input)' ;;
    M_NEEDS_VALUE) printf '%s' '%s needs a value' ;;
    M_BAD_LANG) printf '%s' '--lang must be en or th (got \047%s\047)' ;;
    M_UNKNOWN_CMD) printf '%s' 'unknown command \047%s\047 - see ./kit.sh help' ;;
    M_NEED_TTY_CONFIRM) printf '%s' 'a manual confirmation is needed but there is no terminal: %s' ;;
    M_CONFIRM_TYPE) printf '%s' '%s\nType "%s" to confirm: ' ;;
    M_CANCELLED_WORD) printf '%s' 'cancelled (you did not type %s)' ;;
    M_CONFIRM_YN) printf '%s' '%s [y/N] ' ;;
    M_CANCELLED) printf '%s' 'cancelled' ;;
    M_KV_NOEQ) printf '%s' 'missing "=" sign (the line itself is not shown)' ;;
    M_KV_BADNAME) printf '%s' 'invalid variable name (the line itself is not shown)' ;;
    M_NO_RESOURCES_ENV) printf '%s' 'resources.env not found (looked in the current folder and in the kit folder %s). The zip from the portal already contains project-kit/resources.env - run kit.sh from that zip, or copy resources.example.env to resources.env and fill in PREFIX (or convert the downloaded <prefix>-resources.json / lab5-<prefix>-handoff.json with ./project-kit/from-portal-json.sh), or give --env-file FILE' ;;
    M_UNKNOWN_VAR) printf '%s' 'unknown variable %s in %s (skipped)' ;;
    M_BAD_STACK) printf '%s' '--stack must be node|python|java|go|static|custom' ;;
    M_NEED_PREFIX) printf '%s' 'PREFIX is required in %s (see the Team resources tab of the portal)' ;;
    M_BAD_PREFIX) printf '%s' 'PREFIX \047%s\047 is not valid (3-10 lowercase letters or digits, must start with a letter)' ;;
    M_BAD_PROJECT) printf '%s' 'PROJECT_ID \047%s\047 is not valid' ;;
    M_BAD_REGION) printf '%s' 'REGION \047%s\047 is not valid' ;;
    M_GUARD) printf '%s' '%s = \047%s\047 does not belong to your team (it must be \047%s\047 or start with \047%s-\047). For safety, kit.sh never touches resources of other teams.' ;;
    M_RUNTIME_SA_PROJECT) printf '%s' 'RUNTIME_SA must be in project %s' ;;
    M_SQL_FORMAT) printf '%s' 'SQL_CONNECTION_NAME \047%s\047 must look like %s:%s:%s-pg' ;;
    M_BAD_IMAGE_NAME) printf '%s' 'IMAGE_NAME \047%s\047 is not valid (use lowercase letters, digits and . _ - /)' ;;
    M_BAD_PORT) printf '%s' 'PORT \047%s\047 is not valid' ;;
    M_BAD_CPU) printf '%s' 'CPU \047%s\047 is not valid (for example 1)' ;;
    M_BAD_MEMORY) printf '%s' 'MEMORY \047%s\047 is not valid (for example 512Mi or 1Gi)' ;;
    M_BAD_MIN) printf '%s' 'MIN_INSTANCES must be a number' ;;
    M_BAD_MAX) printf '%s' 'MAX_INSTANCES must be 1-3 (credit is shared; the default is 1)' ;;
    M_MIN_GT_MAX) printf '%s' 'MIN_INSTANCES must not be greater than MAX_INSTANCES' ;;
    M_SECRETISH) printf '%s' '\047%s\047 looks like a secret - do not put it in env / app.env / git. Store the value with ./kit.sh secrets add <1-5>, then reference it with ./kit.sh secrets map %s <1-5> (see the README, secrets section). If this is a false alarm (an ordinary value), allow it explicitly: --allow-plain %s, or ALLOW_PLAIN=%s in app.env / resources.env' ;;
    M_PORT_RESERVED) printf '%s' '\047%s\047 is set by Cloud Run itself (set the port with PORT in resources.env)' ;;
    M_URL_PASSWORD) printf '%s' 'the value of \047%s\047 has a password inside a URL - do not put it in a file or env, use a secret' ;;
    M_DELIM) printf '%s' 'the values in app.env contain too many special characters, so the command cannot be built' ;;
    M_SECRETS_MAP_FORMAT) printf '%s' 'secrets.map line %s: the value of %s must look like secret-name:latest (the value is not shown; never write a real secret value here)' ;;
    M_PH_DIGEST) printf '%s' '<DIGEST_FROM_BUILD>' ;;
    M_PH_LASTTIME) printf '%s' '<LAST_TIME>' ;;
    M_PH_PREV_REV) printf '%s' '<REVISION_PREVIOUS>' ;;
    M_NO_IMAGE) printf '%s' 'no image yet - run \047./kit.sh build\047 first, or give --image %s@sha256:...' ;;
    M_IMAGE_NOT_IN_REGISTRY) printf '%s' 'image \047%s\047 is not in your team registry (%s)' ;;
    M_JOB_LOGS_HINT) printf '%s' '  ./kit.sh logs job --severity ERROR --limit 50\n  (or: gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=%s" --project %s --bucket=_Default --location=global --view=%s --limit 50)' ;;
    M_HELP) printf '%s' 'kit.sh - deploy your project to the Cloud Run of your team (no GitHub needed)

Usage:  ./kit.sh [flags] <command> [options]

Commands
  doctor                  check your computer, permissions and resources, and say how to fix problems
  init                    create an example Dockerfile for --stack (if none exists) and .dockerignore
  build [--tag T] [--dockerfile F] [--context DIR] [-- <docker args>]
                          build (linux/amd64) -> push to your team registry -> save the digest
  migrate [--image REF]   run the migration job with the image (MIGRATE_COMMAND must be set)
  deploy [--image REF] [--skip-migrate] [--replace-env]
                          migrate (if set), then deploy the service with the latest built image
  env list|set K=V ...|unset K ... [--job]
                          show / set / remove env variables (names only, values are not shown)
  secrets                 show the secrets that are readable / mapped (values are not shown)
  secrets list|add <1-5> [--from-stdin|--from-file F]|map <ENV_NAME> <1-5>
                          manage the slots for your own API keys (<prefix>-app-secret-1..5); list probes with 'versions access latest' (values never printed)
  logs [service|job] [--severity LEVEL] [--limit N] [--since 1h] [--follow]
  status                  URL, latest revision, image, env names, last job run
  open                    open the URL of the service
  rollback [--to REVISION] move traffic to the previous revision

Global flags (before or after the command)
  --dry-run               print the commands that would run, but run nothing
  --yes, -y               answer yes to questions (except --replace-env, which always needs typing)
  --env-file F            use another resources.env (default ./resources.env)
  --app-env F             use another app.env      --secrets-map F  use another secrets.map
  --stack node|python|java|go|static|custom   sets defaults for PORT / migrate example / Dockerfile
  --allow-min-instances   allow MIN_INSTANCES > 0 (otherwise it must be 0; credit is shared)
  --allow-plain NAME      let an env name/value through the secret filter (false positive only; repeatable; value still masked)
  --lang en|th            language of messages (else env KIT_LANG, else Thai if LANG starts with th, else English)

Confirmation: answer y or yes to [y/N] questions; type the English word replace for --replace-env.' ;;
    M_INIT_NEED_STACK) printf '%s' 'no stack given: kit.sh does not guess. Choose one of node|python|java|go|static (--stack X, or STACK=X in resources.env), for example: ./kit.sh --stack python init' ;;
    M_INIT_CUSTOM) printf '%s' 'for stack custom you must write the Dockerfile yourself' ;;
    M_INIT_BAD_STACK) printf '%s' 'invalid stack: %s' ;;
    M_INIT_NO_TEMPLATE) printf '%s' 'template not found: %s' ;;
    M_INIT_DOCKERFILE_EXISTS) printf '%s' 'Dockerfile already exists - init never overwrites it. To start over: delete it (rm Dockerfile) and run ./kit.sh --stack <stack> init again' ;;
    M_INIT_DOCKERFILE_CREATED) printf '%s' 'created ./Dockerfile from the %s template - check it and change it to fit your project' ;;
    M_INIT_IGNORE_EXISTS) printf '%s' '.dockerignore already exists, not overwritten' ;;
    M_INIT_IGNORE_CREATED) printf '%s' 'created ./.dockerignore' ;;
    M_HINT_HEADER) printf '%s' 'Example MIGRATE_COMMAND for %s (put it in resources.env if your project has a database to migrate):' ;;
    M_HINT_NODE) printf '%s' '  MIGRATE_COMMAND=npx prisma migrate deploy        (or: npm run migrate)\n  NOTE: \047npm prune --omit=dev\047 in the Dockerfile removes devDependencies (the prisma CLI too): keep prisma in dependencies, or delete the prune line' ;;
    M_HINT_PYTHON) printf '%s' '  MIGRATE_COMMAND=alembic upgrade head              (Django: python manage.py migrate / Flask: flask db upgrade)' ;;
    M_HINT_JAVA) printf '%s' '  MIGRATE_COMMAND=java -jar /app/app.jar --migrate  (or leave it empty if Flyway/Liquibase runs when the app starts)' ;;
    M_HINT_GO) printf '%s' '  MIGRATE_COMMAND=/app/server migrate               (write a migrate subcommand yourself, or use goose/migrate)' ;;
    M_HINT_STATIC) printf '%s' '  (a static website needs no migration - leave MIGRATE_COMMAND empty)' ;;
    M_HINT_OTHER) printf '%s' '  MIGRATE_COMMAND=<a command that migrates your database>' ;;
    M_DR_TITLE) printf '%s' '== Checking the setup for team \047%s\047 (project %s, region %s) ==' ;;
    M_DR_GCLOUD_OK) printf '%s' 'gcloud found' ;;
    M_DR_GCLOUD_MISSING) printf '%s' 'gcloud not found -> install it from https://cloud.google.com/sdk/docs/install' ;;
    M_DR_DOCKER_OK) printf '%s' 'docker found' ;;
    M_DR_BUILDX_MISSING) printf '%s' 'docker buildx not found -> update Docker Desktop' ;;
    M_DR_DAEMON_DOWN) printf '%s' 'docker daemon is not running -> open Docker Desktop first' ;;
    M_DR_DOCKER_MISSING) printf '%s' 'docker not found (needed for the build command) -> install Docker Desktop' ;;
    M_DR_STOP_NO_GCLOUD) printf '%s' 'stopping the checks because gcloud is missing' ;;
    M_DR_LOGIN_OK) printf '%s' 'logged in to gcloud as: %s  (it must be the Gmail you registered in the portal)' ;;
    M_DR_LOGIN_NO) printf '%s' 'not logged in -> run: gcloud auth login' ;;
    M_DR_REGISTRY_OK) printf '%s' 'docker is configured to log in to the registry' ;;
    M_DR_REGISTRY_NO) printf '%s' 'docker is not configured for the registry -> run: gcloud auth configure-docker %s-docker.pkg.dev (the build command does it automatically)' ;;
    M_DR_SVC) printf '%s' 'can see Cloud Run service \047%s\047' ;;
    M_DR_SVC_HINT) printf '%s' 'check SERVICE_NAME / PREFIX in resources.env, and that your gcloud email is the registered one; if it still fails, ask the TA' ;;
    M_DR_JOB) printf '%s' 'can see Cloud Run job \047%s\047' ;;
    M_DR_JOB_HINT) printf '%s' 'check MIGRATE_JOB_NAME; if you have no permission, tell the TA' ;;
    M_DR_REPO) printf '%s' 'can see Artifact Registry repo \047%s\047' ;;
    M_DR_REPO_HINT) printf '%s' 'check REGISTRY; if you have no permission, tell the TA' ;;
    M_DR_SECRET_OK) printf '%s' 'can read secret \047%s\047 (value not shown)' ;;
    M_DR_SECRET_WARN) printf '%s' 'cannot read secret \047%s\047 (a secret attached to the service, such as DATABASE_URL, normally cannot be read directly) -> if you need it, ask the TA' ;;
    M_DR_DOCKERFILE_OK) printf '%s' 'found %s' ;;
    M_DR_DOCKERFILE_WARN) printf '%s' '%s not found -> ./kit.sh --stack <stack> init' ;;
    M_DR_PROBLEMS) printf '%s' 'found %s problem(s), see the advice above (if you are still stuck, ask the TA and attach this output, but never attach passwords)' ;;
    M_DR_READY) printf '%s' 'ready to use (%s warning(s))' ;;
    M_BUILD_BAD_OPT) printf '%s' 'build: unknown option %s' ;;
    M_BAD_TAG) printf '%s' 'tag \047%s\047 is not valid' ;;
    M_BUILD_NO_DOCKERFILE_WARN) printf '%s' '%s not found' ;;
    M_BUILD_NO_DOCKERFILE) printf '%s' 'Dockerfile \047%s\047 not found - use ./kit.sh --stack <stack> init or give --dockerfile' ;;
    M_NO_DOCKER) printf '%s' 'docker not found' ;;
    M_NO_DIGEST) printf '%s' 'cannot read the digest of the image' ;;
    M_BUILD_IMAGE) printf '%s' 'image: %s@%s   (tag: %s)' ;;
    M_BUILD_NEXT) printf '%s' 'next step: ./kit.sh deploy' ;;
    M_MIG_NO_CMD) printf '%s' 'MIGRATE_COMMAND is not set in resources.env' ;;
    M_MIG_SKIP) printf '%s' 'no MIGRATE_COMMAND -> skipping the migration' ;;
    M_MIG_FAILED) printf '%s' 'migration job "%s" failed - stopping, not deploying\nSee the log with:' ;;
    M_MIG_BAD_OPT) printf '%s' 'migrate: unknown option %s' ;;
    M_MIG_DONE) printf '%s' 'migration finished' ;;
    M_DEP_BAD_OPT) printf '%s' 'deploy: unknown option %s' ;;
    M_DEP_REPLACE_EMPTY) printf '%s' '--replace-env but app.env and secrets.map are empty (it would remove all env) - not allowed' ;;
    M_DEP_REPLACE_CONFIRM) printf '%s' '--replace-env will REPLACE all env variables and secrets of the service with the values in app.env / secrets.map. Other variables, including DATABASE_URL / ADMIN_PASSWORD set by the portal, will be lost unless you list them in secrets.map.' ;;
    M_DEP_SKIP) printf '%s' 'skipping the migration (--skip-migrate)' ;;
    M_DEP_DONE) printf '%s' 'deploy finished: %s' ;;
    M_DEP_NEXT) printf '%s' 'check the result: ./kit.sh status   read the log: ./kit.sh logs' ;;
    M_ENV_LIST_SVC) printf '%s' 'env names of service %s (values are not shown):' ;;
    M_ENV_LIST_JOB) printf '%s' 'env names of job %s (values are not shown):' ;;
    M_ENV_SET_USAGE) printf '%s' 'usage: ./kit.sh env set KEY=VALUE [KEY2=VALUE2 ...] [--job]' ;;
    M_ENV_NEED_KV) printf '%s' '\047%s\047 must look like KEY=VALUE' ;;
    M_ENV_BAD_NAME) printf '%s' 'invalid env name: %s' ;;
    M_ENV_UNSET_USAGE) printf '%s' 'usage: ./kit.sh env unset KEY [KEY2 ...] [--job]' ;;
    M_ENV_UNSET_CONFIRM) printf '%s' 'will remove env: %s from the service' ;;
    M_ENV_BAD_SUB) printf '%s' 'env: the subcommand must be list | set | unset' ;;
    M_SLOT_BAD) printf '%s' 'the slot number must be 1-5 (got \047%s\047)' ;;
    M_SL_TITLE) printf '%s' 'slots for your own secrets (API keys and so on) - status comes from an access probe (versions access latest), values are never printed:' ;;
    M_SL_HAS) printf '%s' '  [%s] %s  — has a value' ;;
    M_SL_EMPTY) printf '%s' '  [%s] %s  — READY / EMPTY (no value yet; secrets add works)' ;;
    M_SL_NONE) printf '%s' '  [%s] %s  — NO ACCESS or NOT CREATED FOR YOUR TEAM (ask the TA)' ;;
    M_SL_DISABLED) printf '%s' '  [%s] %s  — latest version is DISABLED/DESTROYED - add a new value with ./kit.sh secrets add %s (a new version becomes the latest)' ;;
    M_SL_UNKNOWN) printf '%s' '  [%s] %s  — UNKNOWN error: %s' ;;
    M_SL_HOW_ADD) printf '%s' 'add a value:  ./kit.sh secrets add <1-5>        (hidden input, or --from-stdin / --from-file F)' ;;
    M_SL_HOW_MAP) printf '%s' 'use in app:   ./kit.sh secrets map <ENV_NAME> <1-5>   then run ./kit.sh deploy' ;;
    M_ADD_FILE_NEEDS_NAME) printf '%s' '--from-file needs a file name' ;;
    M_ADD_UNKNOWN) printf '%s' 'secrets add: unknown \047%s\047 (never put a secret value as an argument; use the prompt, --from-stdin or --from-file)' ;;
    M_ADD_NO_FILE) printf '%s' 'file not found: %s' ;;
    M_ADD_STDIN_TTY) printf '%s' '--from-stdin needs the value to be piped in; to type it yourself, do not use this flag' ;;
    M_ADD_NO_TTY) printf '%s' 'there is no terminal for hidden input - use --from-stdin or --from-file instead' ;;
    M_ADD_PROMPT) printf '%s' 'value of %s (what you type is not shown): ' ;;
    M_ADD_EMPTY) printf '%s' 'empty value, cancelled' ;;
    M_ADD_DONE) printf '%s' 'added a new version to %s (the old value is not deleted; an app that uses :latest gets the new value at the next deploy / revision)' ;;
    M_MAP_BAD_ENV) printf '%s' 'ENV_NAME must be uppercase letters / digits / _ and start with a letter (for example OPENAI_API_KEY)' ;;
    M_MAP_EXISTS) printf '%s' '%s already has %s (edit the file yourself if you want to change the slot)' ;;
    M_MAP_SLOT_LABEL) printf '%s' 'slot' ;;
    M_MAP_DONE) printf '%s' 'added to %s: %s  - run ./kit.sh deploy so the app can see the value' ;;
    M_SEC_BAD_SUB) printf '%s' 'secrets: the subcommand must be list | add <1-5> | map <ENV_NAME> <1-5>' ;;
    M_SEC_MAPPED) printf '%s' 'secrets mapped in secrets.map (names only, values are not shown):' ;;
    M_SEC_EMPTY) printf '%s' '  (empty)' ;;
    M_SEC_CHECK) printf '%s' 'check whether they can be read (read and discard, values are not shown):' ;;
    M_SEC_READABLE) printf '%s' '  [readable]     %s' ;;
    M_SEC_UNREADABLE) printf '%s' '  [not readable] %s' ;;
    M_SEC_ATTACHED) printf '%s' 'secret names attached to the service now:' ;;
    M_SECRETS_NOTE) printf '%s' 'Notes\n - You cannot read or change system secrets (database-url and so on). For your own API keys, use the slots %s-app-secret-1..5:\n     ./kit.sh secrets list | ./kit.sh secrets add <1-5> | ./kit.sh secrets map <ENV_NAME> <1-5>\n - After you add a value you cannot read it back from the web / Console. To change a value (rotate), add a new version.\n - The DATABASE_URL that the portal set is already attached to the service / job and works as it is (a normal deploy does not remove it)' ;;
    M_LOGS_BAD_OPT) printf '%s' 'logs: unknown option %s' ;;
    M_LOGS_BAD_SEV) printf '%s' '--severity must be DEFAULT|DEBUG|INFO|NOTICE|WARNING|ERROR|CRITICAL|ALERT|EMERGENCY' ;;
    M_LOGS_BAD_LIMIT) printf '%s' '--limit must be a number' ;;
    M_LOGS_BAD_SINCE) printf '%s' '--since must look like 30m, 2h, 1d' ;;
    M_LOGS_LATEST) printf '%s' 'latest log of %s (newest first):' ;;
    M_LOGS_FOLLOWING) printf '%s' 'following the log of %s (press Ctrl-C to stop; it stops by itself after 15 minutes)' ;;
    M_LOGS_FOLLOW_DRY) printf '%s' '--follow would poll every 5 seconds, for at most 15 minutes' ;;
    M_ST_URL) printf '%s' 'URL:               %s' ;;
    M_ST_REV) printf '%s' 'latest revision:   %s' ;;
    M_ST_IMAGE) printf '%s' 'image:             %s' ;;
    M_ST_ENV) printf '%s' 'env names (values are not shown):' ;;
    M_ST_EXEC) printf '%s' 'last execution:    %s  (name, end time, succeeded, failed)' ;;
    M_ST_EXEC_NONE) printf '%s' '(never ran / cannot read)' ;;
    M_ST_SVC) printf '%s' '== service: %s ==' ;;
    M_ST_JOB) printf '%s' '== job: %s ==' ;;
    M_UNREADABLE) printf '%s' '(cannot read)' ;;
    M_OPEN_NO_URL) printf '%s' 'cannot read the URL - try ./kit.sh doctor' ;;
    M_RB_BAD_OPT) printf '%s' 'rollback: unknown option %s' ;;
    M_RB_NO_PREV) printf '%s' 'cannot find the previous revision (current revision: %s) - give it yourself with --to REVISION' ;;
    M_RB_UNKNOWN) printf '%s' 'unknown' ;;
    M_RB_NOT_YOURS) printf '%s' 'revision \047%s\047 does not belong to service %s' ;;
    M_RB_CONFIRM) printf '%s' 'will move 100%% of traffic to revision %s (the database data and migrations are NOT rolled back)' ;;
    M_RB_DONE) printf '%s' 'rolled back. Traffic is now pinned to this revision: new revisions (including from env set / env unset) get 0%% traffic until you run ./kit.sh deploy, which routes traffic to the latest revision again' ;;
    M_FILE_NOT_FOUND) printf '%s' 'file not found: %s (given with %s)' ;;
    M_CPU_TOO_HIGH) printf '%s' 'CPU \047%s\047 is above the limit (max 2; credit is shared by all teams)' ;;
    M_MEMORY_TOO_HIGH) printf '%s' 'MEMORY \047%s\047 is above the limit (max 2Gi; credit is shared by all teams)' ;;
    M_MIN_NOT_ZERO) printf '%s' 'MIN_INSTANCES=%s keeps instances running (and costing credit) all the time; it must be 0. If your TA agreed, add the flag --allow-min-instances' ;;
    M_MIN_CONFIRM) printf '%s' 'MIN_INSTANCES=%s will keep instances running all the time and use the shared credit' ;;
    M_SECRETISH_VALUE) printf '%s' 'the value of \047%s\047 looks like a secret (API key, token, private key or a long random string) - it is not shown here. Do not put it in env / app.env / git. Store it with ./kit.sh secrets add <1-5>, then ./kit.sh secrets map %s <1-5>. If this is a false alarm, allow it explicitly: --allow-plain %s, or ALLOW_PLAIN=%s in app.env / resources.env' ;;
    M_ALLOW_PLAIN_BAD) printf '%s' 'ALLOW_PLAIN / --allow-plain needs variable names (letters, digits, _), separated by commas; got \047%s\047' ;;
    M_DELIM_MIGRATE) printf '%s' 'MIGRATE_COMMAND contains too many special characters, so the command cannot be built' ;;
    M_SECRETS_MAP_GUARD) printf '%s' 'secrets.map line %s: the secret of %s must be \047%s\047 or start with \047%s-\047 (the value is not shown). Never write a real secret value here' ;;
    M_INIT_GITIGNORE_CREATED) printf '%s' 'created ./.gitignore (it keeps .kit-state/, resources.env, app.env and secrets.map out of git)' ;;
    M_INIT_GITIGNORE_UPDATED) printf '%s' 'added to ./.gitignore: %s' ;;
    M_BUILD_IGNORE_TRAP) printf '%s' 'the Dockerfile copies \047%s\047 but .dockerignore excludes it - the docker build will fail. Remove the line \047%s\047 from .dockerignore' ;;
    M_ENV_UNSET_CONFIRM_JOB) printf '%s' 'will remove env: %s from the service AND from the migrate job' ;;
    M_TRAFFIC_PINNED) printf '%s' 'traffic of service %s is pinned to one revision (after a rollback), so the new revision gets 0%% of the traffic and your change is not live yet. Route traffic to the latest revision with ./kit.sh deploy, or: gcloud run services update-traffic %s --to-latest --project %s --region %s' ;;
    M_LOGS_FOLLOW_FAIL) printf '%s' 'gcloud logging read failed (will retry): %s' ;;
    M_LOGS_FOLLOW_GIVEUP) printf '%s' 'stopped: gcloud logging read failed 3 times in a row (see the error above; try ./kit.sh doctor)' ;;
    *) return 1 ;;
  esac
}

msg_th() {
  case "$1" in
    M_ERR) printf '%s' 'ผิดพลาด:' ;;
    M_WARN) printf '%s' 'คำเตือน:' ;;
    M_TAG_PASS) printf '%s' '[ผ่าน]' ;;
    M_TAG_FAIL) printf '%s' '[ไม่ผ่าน]' ;;
    M_TAG_WARN) printf '%s' '[แจ้งเตือน]' ;;
    M_DRY_NOTICE) printf '%s' 'ไม่รันคำสั่งจริง แสดงเฉพาะสิ่งที่จะทำ' ;;
    M_DRY_CONFIRM) printf '%s' '(จะถามยืนยัน) %s' ;;
    M_DRY_CHECK) printf '%s' 'ตรวจ %s: ' ;;
    M_DRY_CHECK_SECRET) printf '%s' 'ตรวจอ่าน secret %s: gcloud secrets versions access latest --secret=%s (ผลลัพธ์ทิ้ง ไม่แสดง)' ;;
    M_DRY_FILE_ADD) printf '%s' 'จะเพิ่มบรรทัดใน %s: %s' ;;
    M_DRY_DIGEST) printf '%s' 'จะอ่าน digest จาก metadata ของ buildx (สำรอง: gcloud artifacts docker images describe %s --project %s --format=\047value(image_summary.digest)\047)' ;;
    M_DRY_DISCARDED) printf '%s' 'ผลลัพธ์ทิ้ง' ;;
    M_DRY_DONE) printf '%s' '(dry-run: ไม่ได้ตรวจจริง)' ;;
    M_DRY_ASK_HIDDEN) printf '%s' '(จะถามค่าแบบซ่อน)' ;;
    M_NEEDS_VALUE) printf '%s' '%s ต้องมีค่า' ;;
    M_BAD_LANG) printf '%s' '--lang ต้องเป็น en หรือ th (ได้ \047%s\047)' ;;
    M_UNKNOWN_CMD) printf '%s' 'ไม่รู้จักคำสั่ง \047%s\047 — ดู ./kit.sh help' ;;
    M_NEED_TTY_CONFIRM) printf '%s' 'ต้องยืนยันด้วยตนเองแต่ไม่มี terminal: %s' ;;
    M_CONFIRM_TYPE) printf '%s' '%s\nพิมพ์ "%s" เพื่อยืนยัน: ' ;;
    M_CANCELLED_WORD) printf '%s' 'ยกเลิก (ไม่ได้พิมพ์ %s)' ;;
    M_CONFIRM_YN) printf '%s' '%s [y/N] ' ;;
    M_CANCELLED) printf '%s' 'ยกเลิก' ;;
    M_KV_NOEQ) printf '%s' 'ไม่มีเครื่องหมาย = (ไม่แสดงบรรทัดนั้น)' ;;
    M_KV_BADNAME) printf '%s' 'ชื่อตัวแปรไม่ถูกต้อง (ไม่แสดงบรรทัดนั้น)' ;;
    M_NO_RESOURCES_ENV) printf '%s' 'ไม่พบ resources.env (หาในโฟลเดอร์ปัจจุบันและในโฟลเดอร์ของ kit %s) zip ที่โหลดจาก portal มี project-kit/resources.env ให้อยู่แล้ว — ใช้ kit.sh จาก zip นั้น หรือคัดลอก resources.example.env เป็น resources.env แล้วกรอก PREFIX (หรือแปลงไฟล์ที่โหลดมา <prefix>-resources.json / lab5-<prefix>-handoff.json ด้วย ./project-kit/from-portal-json.sh) หรือระบุ --env-file ไฟล์' ;;
    M_UNKNOWN_VAR) printf '%s' 'ไม่รู้จักตัวแปร %s ใน %s (ข้ามไป)' ;;
    M_BAD_STACK) printf '%s' '--stack ต้องเป็น node|python|java|go|static|custom' ;;
    M_NEED_PREFIX) printf '%s' 'ต้องกรอก PREFIX ใน %s (ดูได้จากแท็บ Team resources ของ portal)' ;;
    M_BAD_PREFIX) printf '%s' 'PREFIX \047%s\047 ไม่ถูกต้อง (ตัวพิมพ์เล็ก/ตัวเลข 3-10 ตัว ขึ้นต้นด้วยตัวอักษร)' ;;
    M_BAD_PROJECT) printf '%s' 'PROJECT_ID \047%s\047 ไม่ถูกต้อง' ;;
    M_BAD_REGION) printf '%s' 'REGION \047%s\047 ไม่ถูกต้อง' ;;
    M_GUARD) printf '%s' '%s = \047%s\047 ไม่ใช่ของกลุ่มคุณ (ต้องเป็น \047%s\047 หรือขึ้นต้นด้วย \047%s-\047) เพื่อความปลอดภัย kit.sh จะไม่แตะ resource ของกลุ่มอื่น' ;;
    M_RUNTIME_SA_PROJECT) printf '%s' 'RUNTIME_SA ต้องอยู่ในโปรเจกต์ %s' ;;
    M_SQL_FORMAT) printf '%s' 'SQL_CONNECTION_NAME \047%s\047 ต้องอยู่ในรูป %s:%s:%s-pg' ;;
    M_BAD_IMAGE_NAME) printf '%s' 'IMAGE_NAME \047%s\047 ไม่ถูกต้อง (ใช้ตัวพิมพ์เล็ก ตัวเลข . _ - /)' ;;
    M_BAD_PORT) printf '%s' 'PORT \047%s\047 ไม่ถูกต้อง' ;;
    M_BAD_CPU) printf '%s' 'CPU \047%s\047 ไม่ถูกต้อง (เช่น 1)' ;;
    M_BAD_MEMORY) printf '%s' 'MEMORY \047%s\047 ไม่ถูกต้อง (เช่น 512Mi หรือ 1Gi)' ;;
    M_BAD_MIN) printf '%s' 'MIN_INSTANCES ต้องเป็นตัวเลข' ;;
    M_BAD_MAX) printf '%s' 'MAX_INSTANCES ต้องเป็น 1-3 (เครดิตใช้ร่วมกัน ค่าเริ่มต้น 1)' ;;
    M_MIN_GT_MAX) printf '%s' 'MIN_INSTANCES ต้องไม่เกิน MAX_INSTANCES' ;;
    M_SECRETISH) printf '%s' '\047%s\047 ดูเหมือนความลับ — ห้ามใส่ใน env/ไฟล์ app.env/git ให้เก็บค่าด้วย ./kit.sh secrets add <1-5> แล้วอ้างถึงด้วย ./kit.sh secrets map %s <1-5> (ดู README หัวข้อ secrets) ถ้าเตือนผิด (เป็นค่าธรรมดา) ให้อนุญาตเอง: --allow-plain %s หรือ ALLOW_PLAIN=%s ใน app.env / resources.env' ;;
    M_PORT_RESERVED) printf '%s' '\047%s\047 เป็นตัวแปรที่ Cloud Run กำหนดเอง (ตั้งพอร์ตด้วย PORT ใน resources.env)' ;;
    M_URL_PASSWORD) printf '%s' 'ค่าของ \047%s\047 มีรหัสผ่านฝังใน URL — ห้ามใส่ในไฟล์/env ให้ใช้ secret' ;;
    M_DELIM) printf '%s' 'ค่าใน app.env มีอักขระพิเศษมากเกินไป ไม่สามารถสร้างคำสั่งได้' ;;
    M_SECRETS_MAP_FORMAT) printf '%s' 'secrets.map บรรทัดที่ %s: ค่าของ %s ต้องอยู่ในรูป ชื่อ-secret:latest (ไม่แสดงค่า; ห้ามใส่ค่าความลับจริง)' ;;
    M_PH_DIGEST) printf '%s' '<DIGEST_FROM_BUILD>' ;;
    M_PH_LASTTIME) printf '%s' '<LAST_TIME>' ;;
    M_PH_PREV_REV) printf '%s' '<REVISION_PREVIOUS>' ;;
    M_NO_IMAGE) printf '%s' 'ยังไม่มี image — รัน \047./kit.sh build\047 ก่อน หรือระบุ --image %s@sha256:...' ;;
    M_IMAGE_NOT_IN_REGISTRY) printf '%s' 'image \047%s\047 ไม่ได้อยู่ใน registry ของกลุ่ม (%s)' ;;
    M_JOB_LOGS_HINT) printf '%s' '  ./kit.sh logs job --severity ERROR --limit 50\n  (หรือ gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=%s" --project %s --bucket=_Default --location=global --view=%s --limit 50)' ;;
    M_HELP) printf '%s' 'kit.sh — เครื่องมือ deploy โปรเจกต์ไป Cloud Run ของกลุ่ม (ไม่ต้องใช้ GitHub)

ใช้:  ./kit.sh [flags] <คำสั่ง> [ตัวเลือก]

คำสั่ง
  doctor                  ตรวจเครื่อง/สิทธิ์/ทรัพยากร พร้อมบอกวิธีแก้
  init                    สร้าง Dockerfile ตัวอย่างตาม --stack (ถ้ายังไม่มี) และ .dockerignore
  build [--tag T] [--dockerfile F] [--context DIR] [-- <args ของ docker>]
                          build (linux/amd64) -> push เข้า registry ของกลุ่ม -> เก็บ digest
  migrate [--image REF]   รัน migration job ด้วย image (ต้องตั้ง MIGRATE_COMMAND)
  deploy [--image REF] [--skip-migrate] [--replace-env]
                          migrate (ถ้ามี) แล้ว deploy service ใช้ image ล่าสุดจาก build
  env list|set K=V ...|unset K ... [--job]
                          ดู/ตั้ง/ลบ env (แสดงเฉพาะชื่อ ไม่แสดงค่า)
  secrets                 ดู secret ที่อ่านได้/ที่ map ไว้ (ไม่แสดงค่า)
  secrets list|add <1-5> [--from-stdin|--from-file F]|map <ENV_NAME> <1-5>
                          จัดการ slot ใส่ API key ของกลุ่ม (<prefix>-app-secret-1..5); list ลองเข้าถึงด้วย 'versions access latest' (ไม่แสดงค่า)
  logs [service|job] [--severity LEVEL] [--limit N] [--since 1h] [--follow]
  status                  URL, revision ล่าสุด, image, ชื่อ env, job ครั้งล่าสุด
  open                    เปิด URL ของ service
  rollback [--to REVISION] ย้าย traffic ไป revision ก่อนหน้า

flags ทั่วไป (ใส่ก่อนหรือหลังคำสั่งก็ได้)
  --dry-run               พิมพ์คำสั่งที่จะรัน แต่ไม่รันอะไรเลย
  --yes, -y               ตอบยืนยันอัตโนมัติ (ยกเว้น --replace-env ที่ต้องพิมพ์ยืนยันเสมอ)
  --env-file F            ใช้ resources.env ไฟล์อื่น (ค่าเริ่มต้น ./resources.env)
  --app-env F             ใช้ app.env ไฟล์อื่น      --secrets-map F  ใช้ secrets.map ไฟล์อื่น
  --stack node|python|java|go|static|custom   ตั้งค่าเริ่มต้นของ PORT/ตัวอย่าง migrate/Dockerfile
  --allow-min-instances   อนุญาต MIN_INSTANCES > 0 (ปกติต้องเป็น 0 เพราะเครดิตใช้ร่วมกัน)
  --allow-plain NAME      ให้ชื่อ/ค่า env ผ่านตัวกรอง secret (เฉพาะกรณีเตือนผิด ใส่ซ้ำได้ ค่ายังถูกปิดบัง)
  --lang en|th            ภาษาของข้อความ (ไม่ใส่: ดู env KIT_LANG ถ้าไม่มี LANG ขึ้นต้น th ใช้ไทย ไม่งั้นอังกฤษ)

การยืนยัน: ตอบ y หรือ yes กับคำถาม [y/N]; ใช้ --replace-env ให้พิมพ์คำอังกฤษ replace' ;;
    M_INIT_NEED_STACK) printf '%s' 'ยังไม่ได้ระบุ stack: kit.sh ไม่เดาให้ เลือกหนึ่งอย่าง node|python|java|go|static (--stack X หรือ STACK=X ใน resources.env) เช่น ./kit.sh --stack python init' ;;
    M_INIT_CUSTOM) printf '%s' 'stack custom ต้องเขียน Dockerfile เอง' ;;
    M_INIT_BAD_STACK) printf '%s' 'stack ไม่ถูกต้อง: %s' ;;
    M_INIT_NO_TEMPLATE) printf '%s' 'ไม่พบ template %s' ;;
    M_INIT_DOCKERFILE_EXISTS) printf '%s' 'มี Dockerfile อยู่แล้ว — init ไม่เขียนทับเด็ดขาด ถ้าอยากเริ่มใหม่: ลบไฟล์ (rm Dockerfile) แล้วรัน ./kit.sh --stack <stack> init อีกครั้ง' ;;
    M_INIT_DOCKERFILE_CREATED) printf '%s' 'สร้าง ./Dockerfile จาก template %s แล้ว — ตรวจ/แก้ให้ตรงกับโปรเจกต์ของคุณ' ;;
    M_INIT_IGNORE_EXISTS) printf '%s' 'มี .dockerignore อยู่แล้ว ไม่เขียนทับ' ;;
    M_INIT_IGNORE_CREATED) printf '%s' 'สร้าง ./.dockerignore แล้ว' ;;
    M_HINT_HEADER) printf '%s' 'ตัวอย่าง MIGRATE_COMMAND สำหรับ %s (ใส่ใน resources.env ถ้าโปรเจกต์มีฐานข้อมูลที่ต้อง migrate):' ;;
    M_HINT_NODE) printf '%s' '  MIGRATE_COMMAND=npx prisma migrate deploy        (หรือ: npm run migrate)\n  หมายเหตุ: \047npm prune --omit=dev\047 ใน Dockerfile ลบ devDependencies (รวมถึง prisma CLI): ให้ย้าย prisma ไปไว้ใน dependencies หรือลบบรรทัด prune ออก' ;;
    M_HINT_PYTHON) printf '%s' '  MIGRATE_COMMAND=alembic upgrade head              (Django: python manage.py migrate / Flask: flask db upgrade)' ;;
    M_HINT_JAVA) printf '%s' '  MIGRATE_COMMAND=java -jar /app/app.jar --migrate  (หรือใช้ Flyway/Liquibase ที่รันตอนสตาร์ตแอป ก็ไม่ต้องมี)' ;;
    M_HINT_GO) printf '%s' '  MIGRATE_COMMAND=/app/server migrate               (เขียน subcommand migrate เอง หรือใช้ goose/migrate)' ;;
    M_HINT_STATIC) printf '%s' '  (เว็บ static ไม่ต้อง migrate — เว้น MIGRATE_COMMAND ว่าง)' ;;
    M_HINT_OTHER) printf '%s' '  MIGRATE_COMMAND=<คำสั่งที่รันแล้ว migrate ฐานข้อมูล>' ;;
    M_DR_TITLE) printf '%s' '== ตรวจระบบสำหรับกลุ่ม \047%s\047 (project %s, region %s) ==' ;;
    M_DR_GCLOUD_OK) printf '%s' 'พบ gcloud' ;;
    M_DR_GCLOUD_MISSING) printf '%s' 'ไม่พบ gcloud -> ติดตั้งจาก https://cloud.google.com/sdk/docs/install' ;;
    M_DR_DOCKER_OK) printf '%s' 'พบ docker' ;;
    M_DR_BUILDX_MISSING) printf '%s' 'ไม่พบ docker buildx -> อัปเดต Docker Desktop' ;;
    M_DR_DAEMON_DOWN) printf '%s' 'docker daemon ไม่ทำงาน -> เปิด Docker Desktop ก่อน' ;;
    M_DR_DOCKER_MISSING) printf '%s' 'ไม่พบ docker (ต้องใช้กับคำสั่ง build) -> ติดตั้ง Docker Desktop' ;;
    M_DR_STOP_NO_GCLOUD) printf '%s' 'หยุดตรวจต่อเพราะไม่มี gcloud' ;;
    M_DR_LOGIN_OK) printf '%s' 'ล็อกอิน gcloud แล้วด้วย: %s  (ต้องเป็น Gmail ที่ลงทะเบียนไว้ใน portal)' ;;
    M_DR_LOGIN_NO) printf '%s' 'ยังไม่ได้ล็อกอิน -> รัน: gcloud auth login' ;;
    M_DR_REGISTRY_OK) printf '%s' 'docker ตั้งค่า login registry แล้ว' ;;
    M_DR_REGISTRY_NO) printf '%s' 'docker ยังไม่ตั้งค่า registry -> รัน: gcloud auth configure-docker %s-docker.pkg.dev (คำสั่ง build จะทำให้อัตโนมัติ)' ;;
    M_DR_SVC) printf '%s' 'เห็น Cloud Run service \047%s\047' ;;
    M_DR_SVC_HINT) printf '%s' 'ตรวจ SERVICE_NAME/PREFIX ใน resources.env และว่าอีเมล gcloud ตรงกับที่ลงทะเบียน; ถ้ายังไม่ได้ ติดต่อ TA' ;;
    M_DR_JOB) printf '%s' 'เห็น Cloud Run job \047%s\047' ;;
    M_DR_JOB_HINT) printf '%s' 'ตรวจ MIGRATE_JOB_NAME; ถ้าไม่มีสิทธิ์ แจ้ง TA' ;;
    M_DR_REPO) printf '%s' 'เห็น Artifact Registry repo \047%s\047' ;;
    M_DR_REPO_HINT) printf '%s' 'ตรวจ REGISTRY; ถ้าไม่มีสิทธิ์ แจ้ง TA' ;;
    M_DR_SECRET_OK) printf '%s' 'อ่าน secret \047%s\047 ได้ (ไม่แสดงค่า)' ;;
    M_DR_SECRET_WARN) printf '%s' 'อ่าน secret \047%s\047 ไม่ได้ (secret ที่แนบกับ service เช่น DATABASE_URL อ่านโดยตรงไม่ได้เป็นปกติ) -> ถ้าต้องใช้ ขอ TA' ;;
    M_DR_DOCKERFILE_OK) printf '%s' 'พบ %s' ;;
    M_DR_DOCKERFILE_WARN) printf '%s' 'ไม่พบ %s -> ./kit.sh --stack <stack> init' ;;
    M_DR_PROBLEMS) printf '%s' 'พบปัญหา %s รายการ ตามคำแนะนำด้านบน (ยังติดให้ถาม TA พร้อมแนบผลลัพธ์นี้ ห้ามแนบรหัสผ่าน)' ;;
    M_DR_READY) printf '%s' 'พร้อมใช้งาน (แจ้งเตือน %s รายการ)' ;;
    M_BUILD_BAD_OPT) printf '%s' 'build: ไม่รู้จักตัวเลือก %s' ;;
    M_BAD_TAG) printf '%s' 'tag \047%s\047 ไม่ถูกต้อง' ;;
    M_BUILD_NO_DOCKERFILE_WARN) printf '%s' 'ไม่พบ %s' ;;
    M_BUILD_NO_DOCKERFILE) printf '%s' 'ไม่พบ Dockerfile \047%s\047 — ใช้ ./kit.sh --stack <stack> init หรือระบุ --dockerfile' ;;
    M_NO_DOCKER) printf '%s' 'ไม่พบ docker' ;;
    M_NO_DIGEST) printf '%s' 'อ่าน digest ของ image ไม่ได้' ;;
    M_BUILD_IMAGE) printf '%s' 'image: %s@%s   (tag: %s)' ;;
    M_BUILD_NEXT) printf '%s' 'ขั้นต่อไป: ./kit.sh deploy' ;;
    M_MIG_NO_CMD) printf '%s' 'ยังไม่ได้ตั้ง MIGRATE_COMMAND ใน resources.env' ;;
    M_MIG_SKIP) printf '%s' 'ไม่มี MIGRATE_COMMAND -> ข้าม migration' ;;
    M_MIG_FAILED) printf '%s' 'migration job "%s" ล้มเหลว — หยุด ไม่ deploy ต่อ\nดู log ด้วย:' ;;
    M_MIG_BAD_OPT) printf '%s' 'migrate: ไม่รู้จักตัวเลือก %s' ;;
    M_MIG_DONE) printf '%s' 'migration เสร็จแล้ว' ;;
    M_DEP_BAD_OPT) printf '%s' 'deploy: ไม่รู้จักตัวเลือก %s' ;;
    M_DEP_REPLACE_EMPTY) printf '%s' '--replace-env แต่ app.env/secrets.map ว่าง (จะลบ env ทั้งหมด) — ไม่อนุญาต' ;;
    M_DEP_REPLACE_CONFIRM) printf '%s' '--replace-env จะ "แทนที่" env และ secret ทั้งหมดของ service ด้วยค่าใน app.env/secrets.map ตัวแปรอื่นรวมถึง DATABASE_URL / ADMIN_PASSWORD ที่ portal ตั้งไว้จะหายไปถ้าไม่ได้ใส่ใน secrets.map' ;;
    M_DEP_SKIP) printf '%s' 'ข้าม migration (--skip-migrate)' ;;
    M_DEP_DONE) printf '%s' 'deploy เสร็จแล้ว: %s' ;;
    M_DEP_NEXT) printf '%s' 'ตรวจผล: ./kit.sh status   ดู log: ./kit.sh logs' ;;
    M_ENV_LIST_SVC) printf '%s' 'ชื่อ env ของ service %s (ไม่แสดงค่า):' ;;
    M_ENV_LIST_JOB) printf '%s' 'ชื่อ env ของ job %s (ไม่แสดงค่า):' ;;
    M_ENV_SET_USAGE) printf '%s' 'ใช้: ./kit.sh env set KEY=VALUE [KEY2=VALUE2 ...] [--job]' ;;
    M_ENV_NEED_KV) printf '%s' '\047%s\047 ต้องอยู่ในรูป KEY=VALUE' ;;
    M_ENV_BAD_NAME) printf '%s' 'ชื่อ env ไม่ถูกต้อง: %s' ;;
    M_ENV_UNSET_USAGE) printf '%s' 'ใช้: ./kit.sh env unset KEY [KEY2 ...] [--job]' ;;
    M_ENV_UNSET_CONFIRM) printf '%s' 'จะลบ env: %s ออกจาก service' ;;
    M_ENV_BAD_SUB) printf '%s' 'env: คำสั่งย่อยต้องเป็น list | set | unset' ;;
    M_SLOT_BAD) printf '%s' 'เลข slot ต้องเป็น 1-5 (ได้ \047%s\047)' ;;
    M_SL_TITLE) printf '%s' 'slot สำหรับ secret ของคุณเอง (API key ฯลฯ) — สถานะมาจากการลองเข้าถึง (versions access latest) ไม่แสดงค่าเด็ดขาด:' ;;
    M_SL_HAS) printf '%s' '  [%s] %s  — มีค่าแล้ว' ;;
    M_SL_EMPTY) printf '%s' '  [%s] %s  — พร้อมใช้/ว่าง (ยังไม่มีค่า ใช้ secrets add ได้)' ;;
    M_SL_NONE) printf '%s' '  [%s] %s  — ไม่มีสิทธิ์ หรือยังไม่ได้สร้างให้กลุ่มคุณ (ถาม TA)' ;;
    M_SL_DISABLED) printf '%s' '  [%s] %s  — version ล่าสุดถูกปิด/ทำลายแล้ว (DISABLED/DESTROYED) - เพิ่มค่าใหม่ด้วย ./kit.sh secrets add %s (version ใหม่จะกลายเป็นตัวล่าสุด)' ;;
    M_SL_UNKNOWN) printf '%s' '  [%s] %s  — ข้อผิดพลาดที่ไม่รู้จัก: %s' ;;
    M_SL_HOW_ADD) printf '%s' 'ใส่ค่า:   ./kit.sh secrets add <1-5>        (พิมพ์ค่าแบบซ่อน หรือ --from-stdin / --from-file F)' ;;
    M_SL_HOW_MAP) printf '%s' 'ผูกกับแอป: ./kit.sh secrets map <ENV_NAME> <1-5>   แล้วรัน ./kit.sh deploy' ;;
    M_ADD_FILE_NEEDS_NAME) printf '%s' '--from-file ต้องมีชื่อไฟล์' ;;
    M_ADD_UNKNOWN) printf '%s' 'secrets add: ไม่รู้จัก \047%s\047 (ห้ามใส่ค่าความลับเป็นอาร์กิวเมนต์ ใช้ prompt, --from-stdin หรือ --from-file)' ;;
    M_ADD_NO_FILE) printf '%s' 'ไม่พบไฟล์ %s' ;;
    M_ADD_STDIN_TTY) printf '%s' '--from-stdin ต้อง pipe ค่าเข้ามา ถ้าจะพิมพ์เองให้ไม่ใส่ flag นี้' ;;
    M_ADD_NO_TTY) printf '%s' 'ไม่มี terminal สำหรับพิมพ์ค่าแบบซ่อน — ใช้ --from-stdin หรือ --from-file แทน' ;;
    M_ADD_PROMPT) printf '%s' 'ค่าของ %s (พิมพ์แล้วไม่แสดงบนจอ): ' ;;
    M_ADD_EMPTY) printf '%s' 'ค่าว่าง ยกเลิก' ;;
    M_ADD_DONE) printf '%s' 'เพิ่ม version ใหม่ให้ %s แล้ว (ค่าเดิมไม่ถูกลบ; แอปที่ใช้ :latest จะได้ค่าใหม่ตอน deploy/revision ถัดไป)' ;;
    M_MAP_BAD_ENV) printf '%s' 'ENV_NAME ต้องเป็นตัวพิมพ์ใหญ่/ตัวเลข/_ ขึ้นต้นด้วยตัวอักษร (เช่น OPENAI_API_KEY)' ;;
    M_MAP_EXISTS) printf '%s' '%s มี %s อยู่แล้ว (แก้ไฟล์เองถ้าต้องการเปลี่ยน slot)' ;;
    M_MAP_SLOT_LABEL) printf '%s' 'slot' ;;
    M_MAP_DONE) printf '%s' 'เพิ่มใน %s: %s  — รัน ./kit.sh deploy เพื่อให้แอปเห็นค่า' ;;
    M_SEC_BAD_SUB) printf '%s' 'secrets: คำสั่งย่อยต้องเป็น list | add <1-5> | map <ENV_NAME> <1-5>' ;;
    M_SEC_MAPPED) printf '%s' 'secret ที่ map ไว้ใน secrets.map (ชื่อเท่านั้น ไม่แสดงค่า):' ;;
    M_SEC_EMPTY) printf '%s' '  (ว่าง)' ;;
    M_SEC_CHECK) printf '%s' 'ตรวจว่าอ่านได้หรือไม่ (อ่านแล้วทิ้ง ไม่แสดงค่า):' ;;
    M_SEC_READABLE) printf '%s' '  [อ่านได้]   %s' ;;
    M_SEC_UNREADABLE) printf '%s' '  [อ่านไม่ได้] %s' ;;
    M_SEC_ATTACHED) printf '%s' 'ชื่อ secret ที่แนบกับ service ตอนนี้:' ;;
    M_SECRETS_NOTE) printf '%s' 'หมายเหตุ\n - secret ของระบบ (database-url ฯลฯ) คุณอ่าน/แก้ไม่ได้ ส่วน API key ของคุณเองให้ใช้ slot %s-app-secret-1..5:\n     ./kit.sh secrets list | ./kit.sh secrets add <1-5> | ./kit.sh secrets map <ENV_NAME> <1-5>\n - ใส่ค่าแล้วอ่านกลับจากเว็บ/Console ไม่ได้ ถ้าจะเปลี่ยนค่า (rotate) ให้ add version ใหม่\n - DATABASE_URL ที่ portal ตั้งไว้ผูกกับ service/job อยู่แล้ว ใช้ได้เลย (deploy แบบปกติไม่ลบ)' ;;
    M_LOGS_BAD_OPT) printf '%s' 'logs: ไม่รู้จักตัวเลือก %s' ;;
    M_LOGS_BAD_SEV) printf '%s' '--severity ต้องเป็น DEFAULT|DEBUG|INFO|NOTICE|WARNING|ERROR|CRITICAL|ALERT|EMERGENCY' ;;
    M_LOGS_BAD_LIMIT) printf '%s' '--limit ต้องเป็นตัวเลข' ;;
    M_LOGS_BAD_SINCE) printf '%s' '--since เช่น 30m, 2h, 1d' ;;
    M_LOGS_LATEST) printf '%s' 'log ล่าสุดของ %s (ใหม่สุดอยู่บน):' ;;
    M_LOGS_FOLLOWING) printf '%s' 'ติดตาม log ของ %s (กด Ctrl-C เพื่อหยุด, หยุดเองใน 15 นาที)' ;;
    M_LOGS_FOLLOW_DRY) printf '%s' '--follow จะวนอ่านทุก 5 วินาที สูงสุด 15 นาที' ;;
    M_ST_URL) printf '%s' 'URL:               %s' ;;
    M_ST_REV) printf '%s' 'revision ล่าสุด:    %s' ;;
    M_ST_IMAGE) printf '%s' 'image:             %s' ;;
    M_ST_ENV) printf '%s' 'ชื่อ env (ไม่แสดงค่า):' ;;
    M_ST_EXEC) printf '%s' 'execution ล่าสุด:   %s  (ชื่อ, เวลาจบ, สำเร็จ, ล้มเหลว)' ;;
    M_ST_EXEC_NONE) printf '%s' '(ยังไม่เคยรัน/อ่านไม่ได้)' ;;
    M_ST_SVC) printf '%s' '== service: %s ==' ;;
    M_ST_JOB) printf '%s' '== job: %s ==' ;;
    M_UNREADABLE) printf '%s' '(อ่านไม่ได้)' ;;
    M_OPEN_NO_URL) printf '%s' 'อ่าน URL ไม่ได้ — ลอง ./kit.sh doctor' ;;
    M_RB_BAD_OPT) printf '%s' 'rollback: ไม่รู้จักตัวเลือก %s' ;;
    M_RB_NO_PREV) printf '%s' 'หา revision ก่อนหน้าไม่ได้ (revision ปัจจุบัน: %s) ระบุเองด้วย --to REVISION' ;;
    M_RB_UNKNOWN) printf '%s' 'ไม่ทราบ' ;;
    M_RB_NOT_YOURS) printf '%s' 'revision \047%s\047 ไม่ใช่ของ service %s' ;;
    M_RB_CONFIRM) printf '%s' 'จะย้าย traffic 100%% ไป revision %s (ข้อมูลในฐานข้อมูลและ migration ไม่ถูกย้อนกลับ)' ;;
    M_RB_DONE) printf '%s' 'rollback แล้ว traffic ถูกตรึงไว้ที่ revision นี้ revision ใหม่ (รวมถึงจาก env set / env unset) จะได้ traffic 0%% จนกว่าจะรัน ./kit.sh deploy ซึ่งจะย้าย traffic กลับไป revision ล่าสุด' ;;
    M_FILE_NOT_FOUND) printf '%s' 'ไม่พบไฟล์ %s (ที่ระบุด้วย %s)' ;;
    M_CPU_TOO_HIGH) printf '%s' 'CPU \047%s\047 เกินเพดาน (สูงสุด 2 เครดิตใช้ร่วมกันทุกกลุ่ม)' ;;
    M_MEMORY_TOO_HIGH) printf '%s' 'MEMORY \047%s\047 เกินเพดาน (สูงสุด 2Gi เครดิตใช้ร่วมกันทุกกลุ่ม)' ;;
    M_MIN_NOT_ZERO) printf '%s' 'MIN_INSTANCES=%s ทำให้มี instance รันค้าง (เสียเครดิตตลอดเวลา) ต้องเป็น 0 ถ้า TA อนุญาตแล้ว ให้เพิ่ม flag --allow-min-instances' ;;
    M_MIN_CONFIRM) printf '%s' 'MIN_INSTANCES=%s จะทำให้มี instance รันค้างตลอดและใช้เครดิตส่วนกลาง' ;;
    M_SECRETISH_VALUE) printf '%s' 'ค่าของ \047%s\047 ดูเหมือนความลับ (API key, token, private key หรือสตริงสุ่มยาว) — จึงไม่แสดงที่นี่ ห้ามใส่ใน env/app.env/git ให้เก็บด้วย ./kit.sh secrets add <1-5> แล้ว ./kit.sh secrets map %s <1-5> ถ้าเตือนผิด ให้อนุญาตเอง: --allow-plain %s หรือ ALLOW_PLAIN=%s ใน app.env / resources.env' ;;
    M_ALLOW_PLAIN_BAD) printf '%s' 'ALLOW_PLAIN / --allow-plain ต้องเป็นชื่อตัวแปร (ตัวอักษร ตัวเลข _) คั่นด้วยจุลภาค แต่ได้ \047%s\047' ;;
    M_DELIM_MIGRATE) printf '%s' 'MIGRATE_COMMAND มีอักขระพิเศษมากเกินไป ไม่สามารถสร้างคำสั่งได้' ;;
    M_SECRETS_MAP_GUARD) printf '%s' 'secrets.map บรรทัดที่ %s: secret ของ %s ต้องเป็น \047%s\047 หรือขึ้นต้นด้วย \047%s-\047 (ไม่แสดงค่า) ห้ามใส่ค่าความลับจริง' ;;
    M_INIT_GITIGNORE_CREATED) printf '%s' 'สร้าง ./.gitignore แล้ว (กัน .kit-state/, resources.env, app.env และ secrets.map ออกจาก git)' ;;
    M_INIT_GITIGNORE_UPDATED) printf '%s' 'เพิ่มใน ./.gitignore: %s' ;;
    M_BUILD_IGNORE_TRAP) printf '%s' 'Dockerfile คัดลอก \047%s\047 แต่ .dockerignore ตัดทิ้ง — docker build จะล้มเหลว ให้ลบบรรทัด \047%s\047 ออกจาก .dockerignore' ;;
    M_ENV_UNSET_CONFIRM_JOB) printf '%s' 'จะลบ env: %s ออกจาก service และออกจาก migrate job ด้วย' ;;
    M_TRAFFIC_PINNED) printf '%s' 'traffic ของ service %s ถูกตรึงไว้ที่ revision เดียว (หลัง rollback) revision ใหม่จึงได้ traffic 0%% และการแก้ไขของคุณยังไม่มีผลจริง ให้ย้าย traffic ไป revision ล่าสุดด้วย ./kit.sh deploy หรือ: gcloud run services update-traffic %s --to-latest --project %s --region %s' ;;
    M_LOGS_FOLLOW_FAIL) printf '%s' 'gcloud logging read ล้มเหลว (จะลองใหม่): %s' ;;
    M_LOGS_FOLLOW_GIVEUP) printf '%s' 'หยุด: gcloud logging read ล้มเหลว 3 ครั้งติดกัน (ดู error ด้านบน ลอง ./kit.sh doctor)' ;;
    *) return 1 ;;
  esac
}

# T KEY [args...]  -> formatted message in the active language (no new line)
T() {
  local key="$1" fmt; shift
  if [ "$KIT_LANG_ACTIVE" = th ]; then fmt="$(msg_th "$key")" || fmt=""; else fmt="$(msg_en "$key")" || fmt=""; fi
  [ -n "$fmt" ] || fmt="$(msg_en "$key")" || fmt="$key"
  # shellcheck disable=SC2059
  local out; printf -v out -- "$fmt" "$@"
  [ "$KIT_CMD" = "./kit.sh" ] || out=${out//\.\/kit.sh/$KIT_CMD}
  printf '%s' "$out"
}

# Hidden debug flag: ./kit.sh --list-messages  -> "KEY en=1 th=1" for each key
list_messages() {
  local k en th
  for k in $MSG_KEYS; do
    en=0; th=0
    [ -n "$(msg_en "$k" 2>/dev/null)" ] && en=1
    [ -n "$(msg_th "$k" 2>/dev/null)" ] && th=1
    printf '%s en=%s th=%s\n' "$k" "$en" "$th"
  done
}

# ----------------------------------------------------------------- language choice
# 1) --lang en|th  2) env KIT_LANG  3) LC_ALL / LC_MESSAGES / LANG starts with th  4) English
detect_lang() {
  local want="" prev="" a l
  for a in "$@"; do
    [ "$a" = "--" ] && break
    if [ "$prev" = "--lang" ]; then want="$a"; break; fi
    case "$a" in --lang=*) want="${a#--lang=}"; break ;; esac
    prev="$a"
  done
  if [ -n "$want" ]; then
    case "$want" in
      en|th) KIT_LANG_ACTIVE="$want"; return 0 ;;
      *) die M_BAD_LANG "$want" ;;
    esac
  fi
  l="$(printf '%s' "${KIT_LANG:-}" | tr '[:upper:]' '[:lower:]')"
  case "$l" in en|th) KIT_LANG_ACTIVE="$l"; return 0 ;; esac
  l="${LC_ALL:-}"; [ -n "$l" ] || l="${LC_MESSAGES:-}"; [ -n "$l" ] || l="${LANG:-}"
  case "$l" in th*|TH*) KIT_LANG_ACTIVE=th ;; *) KIT_LANG_ACTIVE=en ;; esac
}

# ----------------------------------------------------------------- output helpers
err_out() { printf '%s %s\n' "$(T M_ERR)" "$(T "$@")" >&2; }       # KEY args -> stderr, no exit
die()  { err_out "$@"; exit 1; }                                    # KEY args
die_raw() { printf '%s %s\n' "$(T M_ERR)" "$*" >&2; exit 1; }       # already-formatted text
info() { printf '%s\n' "$*"; }                                      # raw text
say()  { printf '%s\n' "$(T "$@")"; }                               # KEY args -> stdout
warn() { printf '%s %s\n' "$(T M_WARN)" "$(T "$@")" >&2; }          # KEY args -> stderr
need() { [ -n "${2:-}" ] || die M_NEEDS_VALUE "$1"; }               # flag, value

# quote an argument for display (only names / non-secret values are shown)
q() {
  case "$1" in
    ''|*[!A-Za-z0-9_./:=@%+,^~-]*) printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")" ;;
    *) printf '%s' "$1" ;;
  esac
}
# mask the values of an --update-env-vars / --set-env-vars argument: ^@^K=V@K2=V2 -> ^@^K=***@K2=***
mask_env_arg() {
  local arg="$1" d="," head="" rest part out="" i=0 parts
  case "$arg" in
    \^?^*) d="${arg:1:1}"; head="^$d^"; rest="${arg:3}" ;;
    *) rest="$arg" ;;
  esac
  IFS="$d" read -r -a parts <<< "$rest" || true
  for part in ${parts[@]+"${parts[@]}"}; do
    [ "$i" = 0 ] || out="$out$d"
    out="$out${part%%=*}=***"
    i=$((i + 1))
  done
  printf '%s%s' "$head" "$out"
}
show_cmd() {
  local first=1 a prev=""
  for a in "$@"; do
    if [ "$first" = 1 ]; then first=0; else printf ' '; fi
    case "$prev" in
      --update-env-vars|--set-env-vars) q "$(mask_env_arg "$a")" ;;
      *) q "$a" ;;
    esac
    prev="$a"
  done
  printf '\n'
}
# run a command (or only print it with --dry-run)
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; show_cmd "$@"; return 0; fi
  printf '+ '; show_cmd "$@"
  "$@"
}
# read-only command: with --dry-run only print it, otherwise run it and return the output (may fail, does not stop the script)
read_cmd() {
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] ' >&2; show_cmd "$@" >&2; return 0; fi
  "$@" 2>/dev/null || true
}
confirm() {
  # $1 = message (already formatted)  $2 = word the user must type (if empty, y is enough)
  local msg="$1" word="${2:-}" ans
  if [ "$DRY_RUN" = 1 ]; then info "[dry-run] $(T M_DRY_CONFIRM "$msg")"; return 0; fi
  if [ "$ASSUME_YES" = 1 ] && [ -z "$word" ]; then return 0; fi
  [ -t 0 ] || die M_NEED_TTY_CONFIRM "$msg"
  if [ -n "$word" ]; then
    T M_CONFIRM_TYPE "$msg" "$word"
    read -r ans
    [ "$ans" = "$word" ] || die M_CANCELLED_WORD "$word"
  else
    T M_CONFIRM_YN "$msg"
    read -r ans
    case "$ans" in y|Y|yes|YES) ;; *) die M_CANCELLED ;; esac
  fi
}

# ----------------------------------------------------------------- read KEY=VALUE files (never source)
# fills KV_ARR (KEY=VALUE) and KV_LNO (line numbers); on a bad line sets KV_ERR and returns 1.
# Handles a BOM, CRLF, trailing spaces, "export ", quotes and "# comment" tails. The text of a bad line is never shown.
kv_lines() {
  local f="$1" line key val rest n=0
  KV_ARR=(); KV_LNO=(); KV_ERR=""
  [ -f "$f" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    n=$((n + 1))
    [ "$n" != 1 ] || line="${line#$'\xEF\xBB\xBF'}"
    line="${line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in export\ *) line="${line#export }"; line="${line#"${line%%[![:space:]]*}"}" ;; esac
    case "$line" in *=*) ;; *) KV_ERR="$f:$n: $(T M_KV_NOEQ)"; return 1 ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    val="${val#"${val%%[![:space:]]*}"}"
    if ! [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      KV_ERR="$f:$n: $(T M_KV_BADNAME)"; return 1
    fi
    case "$val" in
      \"*) rest="${val#\"}"; case "$rest" in *\"*) val="${rest%%\"*}" ;; esac ;;
      \'*) rest="${val#\'}"; case "$rest" in *\'*) val="${rest%%\'*}" ;; esac ;;
      *) case "$val" in *[[:space:]]\#*) val="${val%%[[:space:]]\#*}"; val="${val%"${val##*[![:space:]]}"}" ;; esac ;;
    esac
    KV_ARR+=("$key=$val"); KV_LNO+=("$n")
  done < "$f"
}
read_kv() { # stop if a line is wrong; result in KV_ARR / KV_LNO
  kv_lines "$1" || die_raw "$KV_ERR"
}

find_file() { # $1=value given by the user $2=file name -> prints the path (or nothing)
  if [ -n "$1" ]; then printf '%s' "$1"; return; fi
  if [ -f "./$2" ]; then printf './%s' "$2"; return; fi
  if [ -f "$KIT_DIR/$2" ]; then printf '%s' "$KIT_DIR/$2"; return; fi
}

explicit_file_must_exist() { # $1=value given by the user $2=flag name
  [ -z "$1" ] || [ -f "$1" ] || die M_FILE_NOT_FOUND "$1" "$2"
}

# ----------------------------------------------------------------- load and check config
KNOWN_KEYS="PROJECT_ID REGION PREFIX SERVICE_NAME MIGRATE_JOB_NAME REGISTRY IMAGE_NAME RUNTIME_SA SQL_CONNECTION_NAME PORT CPU MEMORY MIN_INSTANCES MAX_INSTANCES DOCKERFILE BUILD_CONTEXT MIGRATE_COMMAND STACK LOG_VIEW ALLOW_PLAIN"

guard() { # $1=label $2=value : must be PREFIX or start with PREFIX-
  case "$2" in
    "$PREFIX"|"$PREFIX"-*) ;;
    *) die M_GUARD "$1" "$2" "$PREFIX" "$PREFIX" ;;
  esac
}

stack_default_port() {
  case "$1" in node|python|java|go|static|custom|'') echo 8080 ;; esac
}

load_config() {
  local f k v line
  for k in $KNOWN_KEYS; do unset "$k"; done
  f="$(find_file "$ENV_FILE" resources.env)"
  [ -n "$f" ] && [ -f "$f" ] || die M_NO_RESOURCES_ENV "$KIT_DIR"
  read_kv "$f"
  for line in ${KV_ARR[@]+"${KV_ARR[@]}"}; do
    k="${line%%=*}"; v="${line#*=}"
    case " $KNOWN_KEYS " in
      *" $k "*) printf -v "$k" '%s' "$v" ;;
      *) warn M_UNKNOWN_VAR "$k" "$f" ;;
    esac
  done

  check_allow_plain_list "${ALLOW_PLAIN:-}"
  [ -n "$STACK_ARG" ] && STACK="$STACK_ARG"
  case "${STACK:-}" in ''|node|python|java|go|static|custom) ;; *) die M_BAD_STACK ;; esac

  PROJECT_ID="${PROJECT_ID:-cpe-se-course-2026}"
  REGION="${REGION:-asia-southeast1}"
  [ -n "${PREFIX:-}" ] || die M_NEED_PREFIX "$f"
  [[ "$PREFIX" =~ ^[a-z][a-z0-9]{2,9}$ ]] || die M_BAD_PREFIX "$PREFIX"
  [[ "$PROJECT_ID" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || die M_BAD_PROJECT "$PROJECT_ID"
  [[ "$REGION" =~ ^[a-z]+-[a-z]+[0-9]+$ ]] || die M_BAD_REGION "$REGION"

  SERVICE_NAME="${SERVICE_NAME:-$PREFIX}"
  MIGRATE_JOB_NAME="${MIGRATE_JOB_NAME:-$PREFIX-migrate}"
  REGISTRY="${REGISTRY:-$PREFIX}"
  IMAGE_NAME="${IMAGE_NAME:-$PREFIX}"
  RUNTIME_SA="${RUNTIME_SA:-$PREFIX-runner@$PROJECT_ID.iam.gserviceaccount.com}"
  SQL_CONNECTION_NAME="${SQL_CONNECTION_NAME:-$PROJECT_ID:$REGION:$PREFIX-pg}"
  PORT="${PORT:-$(stack_default_port "${STACK:-}")}"
  CPU="${CPU:-1}"
  MEMORY="${MEMORY:-512Mi}"
  MIN_INSTANCES="${MIN_INSTANCES:-0}"
  MAX_INSTANCES="${MAX_INSTANCES:-1}"
  DOCKERFILE="${DOCKERFILE:-Dockerfile}"
  BUILD_CONTEXT="${BUILD_CONTEXT:-.}"
  MIGRATE_COMMAND="${MIGRATE_COMMAND:-}"
  LOG_VIEW="${LOG_VIEW:-$PREFIX}"

  # --- safety guard: every resource must belong to this team
  guard SERVICE_NAME "$SERVICE_NAME"
  guard MIGRATE_JOB_NAME "$MIGRATE_JOB_NAME"
  guard REGISTRY "$REGISTRY"
  guard LOG_VIEW "$LOG_VIEW"
  guard RUNTIME_SA "${RUNTIME_SA%%@*}"
  [ "${RUNTIME_SA#*@}" = "$PROJECT_ID.iam.gserviceaccount.com" ] || die M_RUNTIME_SA_PROJECT "$PROJECT_ID"
  case "$SQL_CONNECTION_NAME" in
    "$PROJECT_ID:$REGION:"*) guard SQL_CONNECTION_NAME "${SQL_CONNECTION_NAME##*:}" ;;
    *) die M_SQL_FORMAT "$SQL_CONNECTION_NAME" "$PROJECT_ID" "$REGION" "$PREFIX" ;;
  esac
  [[ "$IMAGE_NAME" =~ ^[a-z0-9][a-z0-9._/-]*$ ]] || die M_BAD_IMAGE_NAME "$IMAGE_NAME"

  [[ "$PORT" =~ ^[0-9]+$ ]] && [ "$PORT" -ge 1 ] && [ "$PORT" -le 65535 ] || die M_BAD_PORT "$PORT"
  [[ "$CPU" =~ ^[0-9]+(\.[0-9]+)?$ ]] || die M_BAD_CPU "$CPU"
  awk "BEGIN{exit !($CPU <= 2)}" || die M_CPU_TOO_HIGH "$CPU"      # CPU was checked as a plain number above
  [[ "$MEMORY" =~ ^[0-9]+(Mi|Gi)$ ]] || die M_BAD_MEMORY "$MEMORY"
  local mem_mi="${MEMORY%??}"; case "$MEMORY" in *Gi) mem_mi=$((10#$mem_mi * 1024)) ;; *) mem_mi=$((10#$mem_mi)) ;; esac
  [ "$mem_mi" -le 2048 ] || die M_MEMORY_TOO_HIGH "$MEMORY"
  [[ "$MIN_INSTANCES" =~ ^[0-9]+$ ]] || die M_BAD_MIN
  [ "$((10#$MIN_INSTANCES))" -eq 0 ] || [ "$ALLOW_MIN" = 1 ] || die M_MIN_NOT_ZERO "$MIN_INSTANCES"
  [[ "$MAX_INSTANCES" =~ ^[0-9]+$ ]] && [ "$MAX_INSTANCES" -ge 1 ] && [ "$MAX_INSTANCES" -le 3 ] || die M_BAD_MAX
  [ "$MIN_INSTANCES" -le "$MAX_INSTANCES" ] || die M_MIN_GT_MAX

  IMAGE_REPO="$REGION-docker.pkg.dev/$PROJECT_ID/$REGISTRY/$IMAGE_NAME"
}

# ----------------------------------------------------------------- env / secrets
# ---- the secret filter (documented in the README). A NAME is refused when, after splitting it on "_",
# it has a whole-word token that means "credential": SECRET, PASSWORD, PASSWD, PWD, PASS, CREDENTIAL(S), SIGNATURE, DSN,
# TOKEN (unless followed by EXPIRE*/TTL/MINUTES/SECONDS/HOURS/DAYS/ROUNDS/TYPE/URL/HOST/NAME), PRIVATE_KEY,
# DATABASE_URL, CONNECTION_STRING, KEY as the last token or in API_KEY / SECRET_KEY / ACCESS_KEY / AUTH_KEY, and AUTH alone.
# There is no substring matching (AUTHOR, PASSPORT, MONKEY, NEXTAUTH_URL, AUTH_TRUST_HOST pass).
# A name that ends in URL/HOST/PORT/ROUNDS/MINUTES/SECONDS/TTL/NAME/ID/ENABLED/MODE/LABEL/DIR/PATH skips the KEY/AUTH rules
# (GOOGLE_CLIENT_ID, AWS_ACCESS_KEY_ID, PUBLIC_KEY_URL pass) but is still refused for SECRET/PASSWORD/PRIVATE_KEY/... above.
secretish_key() {
  local up toks i n t nx pv sfx=0
  up="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
  IFS=_ read -r -a toks <<< "$up"
  n=${#toks[@]}
  case "${toks[$((n - 1))]}" in URL|HOST|PORT|ROUNDS|MINUTES|SECONDS|TTL|NAME|ID|ENABLED|MODE|LABEL|DIR|PATH) sfx=1 ;; esac
  [ "$n" -ne 1 ] || [ "${toks[0]}" != AUTH ] || return 0
  i=0
  while [ "$i" -lt "$n" ]; do
    t="${toks[$i]}"; nx=""; pv=""
    [ $((i + 1)) -ge "$n" ] || nx="${toks[$((i + 1))]}"
    [ "$i" -eq 0 ] || pv="${toks[$((i - 1))]}"
    case "$t" in
      SECRET|PASSWORD|PASSWD|PWD|PASS|CREDENTIAL|CREDENTIALS|SIGNATURE|DSN) return 0 ;;
      TOKEN) case "$nx" in EXPIRE*|TTL|MINUTES|SECONDS|HOURS|DAYS|ROUNDS|TYPE|URL|HOST|NAME) ;; *) return 0 ;; esac ;;
      PRIVATE) [ "$nx" != KEY ] || return 0 ;;
      DATABASE) [ "$nx" != URL ] || return 0 ;;
      CONNECTION) [ "$nx" != STRING ] || return 0 ;;
      KEY)
        if [ "$sfx" = 0 ]; then
          [ "$nx" != "" ] || return 0
          case "$pv" in API|SECRET|ACCESS|AUTH) return 0 ;; esac
        fi ;;
    esac
    i=$((i + 1))
  done
  return 1
}
# true if the VALUE has a strong secret signal: a well-known prefix (sk-, sk_live_, sk_test_, AIza, ghp_/gho_/ghu_/ghs_/ghr_,
# github_pat_, xox?-, AKIA/ASIA + 16 chars), a PEM block, a JWT, or a high-entropy blob (see the README for the exact rule)
secretish_value() {
  local v="$1"
  case "$v" in
    sk-*|sk_live_*|sk_test_*|AIza*|ghp_*|gho_*|ghu_*|ghs_*|ghr_*|github_pat_*|xox[abeoprs]-*|*"-----BEGIN"*) return 0 ;;
  esac
  [[ "$v" =~ ^(AKIA|ASIA)[0-9A-Z]{16} ]] && return 0
  [[ "$v" =~ eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\. ]] && return 0
  [[ "$v" =~ ^[A-Za-z0-9+/=_-]{32,}$ ]] || return 1
  # looks like a blob; now remove the things that are clearly not secrets
  [[ "$v" =~ ^[0-9a-fA-F]{40}$ ]] && return 1                                  # a git SHA
  case "$v" in /*) return 1 ;; esac                                           # a path
  [[ "$v" =~ ^[a-z0-9._-]*(/[a-z0-9._-]*)+$ ]] && return 1                    # a lowercase relative path
  [[ "$v" =~ ^[a-z0-9]+([-_][a-z0-9]+){2,}$ ]] && return 1                    # a slug: 3+ lowercase words joined by - or _
  [[ "$v" =~ [0-9] ]] || return 1
  [[ "$v" =~ [A-Za-z] ]] || return 1
  if [[ "$v" =~ [a-z] ]] && [[ "$v" =~ [A-Z] ]]; then return 0; fi          # mixed case
  [ "${#v}" -ge 40 ]
}
# --allow-plain NAME / ALLOW_PLAIN=A,B in resources.env or app.env: skip the name and value checks (the value is still masked in output)
allow_plain_has() {
  local up list; up="$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')"
  list="$ALLOW_PLAIN_FLAGS ${ALLOW_PLAIN:-} $APP_ALLOW_PLAIN"
  list="$(printf '%s' "$list" | tr '[:lower:],' '[:upper:] ')"
  case " $list " in *" $up "*) return 0 ;; esac
  return 1
}
check_allow_plain_list() { # $1=comma list -> validates; prints the list with spaces
  local x
  for x in $(printf '%s' "$1" | tr ',' ' '); do [[ "$x" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die M_ALLOW_PLAIN_BAD "$x"; done
}
check_plain_env() { # $1=KEY $2=VALUE   (the value is never printed)
  local allowed=0
  allow_plain_has "$1" && allowed=1
  if [ "$allowed" = 0 ] && secretish_key "$1"; then
    die M_SECRETISH "$1" "$1" "$1" "$1"
  fi
  case "$1" in PORT|K_SERVICE|K_REVISION|K_CONFIGURATION) die M_PORT_RESERVED "$1" ;; esac
  if [ "$allowed" = 0 ] && secretish_value "$2"; then
    die M_SECRETISH_VALUE "$1" "$1" "$1" "$1"
  fi
  if printf '%s' "$2" | grep -Eq '://[^/ ]*:[^@/ ]+@'; then
    die M_URL_PASSWORD "$1"
  fi
}

ENV_PAIRS=()      # KEY=VALUE from app.env
SECRET_PAIRS=()   # ENV=secret:version from secrets.map
ENV_DELIM="@"

pick_delim() { # choose a separator that does not appear in the data
  local d all="$*"
  for d in '@' '|' '~' '!' ';' '%'; do
    case "$all" in *"$d"*) ;; *) ENV_DELIM="$d"; return 0 ;; esac
  done
  die M_DELIM
}

load_app_env() {
  local f line k v
  ENV_PAIRS=()
  explicit_file_must_exist "$APP_ENV_FILE" --app-env
  f="$(find_file "$APP_ENV_FILE" app.env)"
  [ -n "$f" ] && [ -f "$f" ] || return 0
  read_kv "$f"
  APP_ALLOW_PLAIN=""
  for line in ${KV_ARR[@]+"${KV_ARR[@]}"}; do   # first the ALLOW_PLAIN= directive (it applies to the whole file)
    case "$line" in ALLOW_PLAIN=*) check_allow_plain_list "${line#*=}"; APP_ALLOW_PLAIN="$APP_ALLOW_PLAIN ${line#*=}" ;; esac
  done
  for line in ${KV_ARR[@]+"${KV_ARR[@]}"}; do
    k="${line%%=*}"; v="${line#*=}"
    [ "$k" != ALLOW_PLAIN ] || continue
    check_plain_env "$k" "$v"
    ENV_PAIRS+=("$k=$v")
  done
  [ "${#ENV_PAIRS[@]}" -eq 0 ] || pick_delim "${ENV_PAIRS[@]}"
}
load_secrets_map() {
  local f line k v name i=0
  SECRET_PAIRS=()
  explicit_file_must_exist "$SECRETS_MAP_FILE" --secrets-map
  f="$(find_file "$SECRETS_MAP_FILE" secrets.map)"
  [ -n "$f" ] && [ -f "$f" ] || return 0
  read_kv "$f"
  for line in ${KV_ARR[@]+"${KV_ARR[@]}"}; do
    k="${line%%=*}"; v="${line#*=}"
    # never print the value: a real secret may have been pasted here by mistake
    [[ "$v" =~ ^[A-Za-z0-9_-]+(:[A-Za-z0-9]+)?$ ]] || die M_SECRETS_MAP_FORMAT "${KV_LNO[$i]}" "$k"
    name="${v%%:*}"
    case "$name" in "$PREFIX"|"$PREFIX"-*) ;; *) die M_SECRETS_MAP_GUARD "${KV_LNO[$i]}" "$k" "$PREFIX" "$PREFIX" ;; esac
    case "$v" in *:*) ;; *) v="$v:latest" ;; esac
    SECRET_PAIRS+=("$k=$v")
    i=$((i + 1))
  done
}
join_by() { local IFS="$1"; shift; printf '%s' "$*"; }

# build the env / secret arguments into EXTRA_ARGS ; $1=update|set
env_flags() {
  local mode="$1"
  EXTRA_ARGS=()
  if [ "${#ENV_PAIRS[@]}" -gt 0 ]; then
    if [ "$mode" = set ]; then EXTRA_ARGS+=(--set-env-vars); else EXTRA_ARGS+=(--update-env-vars); fi
    EXTRA_ARGS+=("^${ENV_DELIM}^$(join_by "$ENV_DELIM" "${ENV_PAIRS[@]}")")
  fi
  if [ "${#SECRET_PAIRS[@]}" -gt 0 ]; then
    if [ "$mode" = set ]; then EXTRA_ARGS+=(--set-secrets); else EXTRA_ARGS+=(--update-secrets); fi
    EXTRA_ARGS+=("$(join_by , "${SECRET_PAIRS[@]}")")
  fi
}

# ----------------------------------------------------------------- image state
state_file() { printf '%s/last-image' "$STATE_DIR"; }
resolve_image() { # $1 = --image given by the user (if any) -> IMAGE_REF
  local img="$1"
  if [ -z "$img" ] && [ -f "$(state_file)" ]; then img="$(head -1 "$(state_file)")"; fi
  if [ -z "$img" ]; then
    if [ "$DRY_RUN" = 1 ]; then img="$IMAGE_REPO@sha256:$(T M_PH_DIGEST)"
    else die M_NO_IMAGE "$IMAGE_REPO"; fi
  fi
  case "$img" in "$IMAGE_REPO"@sha256:*|"$IMAGE_REPO":*) ;;
    *) die M_IMAGE_NOT_IN_REGISTRY "$img" "$IMAGE_REPO" ;; esac
  IMAGE_REF="$img"
}

gflags() { GF=(--project "$PROJECT_ID" --region "$REGION"); }

job_logs_hint() {
  T M_JOB_LOGS_HINT "$MIGRATE_JOB_NAME" "$PROJECT_ID" "$LOG_VIEW" >&2
  printf '\n' >&2
}

# ================================================================= commands
cmd_help() { T M_HELP; printf '\n'; }

# ---------------------------------------------------------------- init
cmd_init() {
  local stack="${STACK_ARG:-}" t
  if [ -z "$stack" ]; then
    local f; f="$(find_file "$ENV_FILE" resources.env)"
    if [ -n "$f" ] && [ -f "$f" ]; then
      read_kv "$f"
      local l; for l in ${KV_ARR[@]+"${KV_ARR[@]}"}; do case "$l" in STACK=*) stack="${l#STACK=}"; break ;; esac; done
    fi
  fi
  [ -n "$stack" ] || die M_INIT_NEED_STACK
  case "$stack" in node|python|java|go|static) ;; custom) die M_INIT_CUSTOM ;; *) die M_INIT_BAD_STACK "$stack" ;; esac
  t="$KIT_DIR/templates/Dockerfile.$stack"
  [ -f "$t" ] || die M_INIT_NO_TEMPLATE "$t"
  if [ -e Dockerfile ]; then say M_INIT_DOCKERFILE_EXISTS
  else run cp "$t" Dockerfile; [ "$DRY_RUN" = 1 ] || say M_INIT_DOCKERFILE_CREATED "$stack"; fi
  if [ -e .dockerignore ]; then say M_INIT_IGNORE_EXISTS
  elif [ "$stack" = static ]; then
    # the static Dockerfile copies dist/ (or build/): those folders must not be excluded
    if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] grep -vx -e dist -e build templates/dockerignore.example > .dockerignore\n'
    else grep -vx -e dist -e build "$KIT_DIR/templates/dockerignore.example" > .dockerignore; say M_INIT_IGNORE_CREATED; fi
  else run cp "$KIT_DIR/templates/dockerignore.example" .dockerignore; [ "$DRY_RUN" = 1 ] || say M_INIT_IGNORE_CREATED; fi
  ensure_gitignore
  stack_hints "$stack"
}
# keep the kit state and the config files out of git (so they do not make the image tag "-dirty" and are never pushed)
ensure_gitignore() {
  local entry added="" existed=0
  [ -f .gitignore ] && existed=1
  for entry in .kit-state/ resources.env app.env secrets.map; do
    if [ "$existed" = 1 ] && grep -Eqx "[[:space:]]*/?${entry//./\\.}[[:space:]]*" .gitignore; then continue; fi
    added="$added $entry"
  done
  [ -n "$added" ] || return 0
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; say M_DRY_FILE_ADD ".gitignore" "${added# }"; return 0; fi
  if [ "$existed" = 1 ]; then
    if [ -n "$(tail -c1 .gitignore)" ]; then printf '\n' >> .gitignore; fi
    printf '# project-kit (local state and config, do not commit)\n' >> .gitignore
    for entry in $added; do printf '%s\n' "$entry" >> .gitignore; done
    say M_INIT_GITIGNORE_UPDATED "${added# }"
  else
    { printf '# project-kit (local state and config, do not commit)\n'; for entry in $added; do printf '%s\n' "$entry"; done; } > .gitignore
    say M_INIT_GITIGNORE_CREATED
  fi
}
stack_hints() {
  info ""
  say M_HINT_HEADER "$1"
  case "$1" in
    node)   say M_HINT_NODE ;;
    python) say M_HINT_PYTHON ;;
    java)   say M_HINT_JAVA ;;
    go)     say M_HINT_GO ;;
    static) say M_HINT_STATIC ;;
    *)      say M_HINT_OTHER ;;
  esac
}

# ---------------------------------------------------------------- doctor
FAILS=0; WARNS=0
row() { # $1=tag key $2=message key ; rest = message args
  local tag="$1" key="$2"; shift 2
  printf '  %s %s\n' "$(T "$tag")" "$(T "$key" "$@")"
}
chk() { # $1=label  $2=hint ; $3.. = command
  local label="$1" hint="$2"; shift 2
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; T M_DRY_CHECK "$label"; show_cmd "$@"; return 0; fi
  if "$@" >/dev/null 2>&1; then info "  $(T M_TAG_PASS) $label"
  else info "  $(T M_TAG_FAIL) $label"; info "      -> $hint"; FAILS=$((FAILS + 1)); fi
}
cmd_doctor() {
  gflags; load_app_env; load_secrets_map
  say M_DR_TITLE "$PREFIX" "$PROJECT_ID" "$REGION"
  if [ "$DRY_RUN" != 1 ]; then
    if command -v gcloud >/dev/null 2>&1; then row M_TAG_PASS M_DR_GCLOUD_OK; else row M_TAG_FAIL M_DR_GCLOUD_MISSING; FAILS=$((FAILS+1)); fi
    if command -v docker >/dev/null 2>&1; then
      row M_TAG_PASS M_DR_DOCKER_OK
      docker buildx version >/dev/null 2>&1 || { row M_TAG_FAIL M_DR_BUILDX_MISSING; FAILS=$((FAILS+1)); }
      docker info >/dev/null 2>&1 || { row M_TAG_FAIL M_DR_DAEMON_DOWN; FAILS=$((FAILS+1)); }
    else row M_TAG_FAIL M_DR_DOCKER_MISSING; FAILS=$((FAILS+1)); fi
    command -v gcloud >/dev/null 2>&1 || { say M_DR_STOP_NO_GCLOUD; exit 1; }
    local acct; acct="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -1 || true)"
    if [ -n "$acct" ]; then row M_TAG_PASS M_DR_LOGIN_OK "$acct"
    else row M_TAG_FAIL M_DR_LOGIN_NO; FAILS=$((FAILS+1)); fi
    if grep -qs "$REGION-docker.pkg.dev" "$HOME/.docker/config.json" 2>/dev/null; then row M_TAG_PASS M_DR_REGISTRY_OK
    else row M_TAG_WARN M_DR_REGISTRY_NO "$REGION"; WARNS=$((WARNS+1)); fi
  fi
  chk "$(T M_DR_SVC "$SERVICE_NAME")" "$(T M_DR_SVC_HINT)" \
      gcloud run services describe "$SERVICE_NAME" "${GF[@]}"
  chk "$(T M_DR_JOB "$MIGRATE_JOB_NAME")" "$(T M_DR_JOB_HINT)" \
      gcloud run jobs describe "$MIGRATE_JOB_NAME" "${GF[@]}"
  chk "$(T M_DR_REPO "$REGISTRY")" "$(T M_DR_REPO_HINT)" \
      gcloud artifacts repositories describe "$REGISTRY" --location "$REGION" --project "$PROJECT_ID"
  local s
  for s in ${SECRET_PAIRS[@]+"${SECRET_PAIRS[@]}"}; do
    s="${s#*=}"; s="${s%%:*}"
    if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; say M_DRY_CHECK_SECRET "$s" "$s"
    elif gcloud secrets versions access latest --secret="$s" --project "$PROJECT_ID" >/dev/null 2>&1; then row M_TAG_PASS M_DR_SECRET_OK "$s"
    else row M_TAG_WARN M_DR_SECRET_WARN "$s"; WARNS=$((WARNS+1)); fi
  done
  if [ -f "$DOCKERFILE" ]; then row M_TAG_PASS M_DR_DOCKERFILE_OK "$DOCKERFILE"; else row M_TAG_WARN M_DR_DOCKERFILE_WARN "$DOCKERFILE"; WARNS=$((WARNS+1)); fi
  if [ "$DRY_RUN" = 1 ]; then say M_DRY_DONE; return 0; fi
  info ""
  if [ "$FAILS" -gt 0 ]; then say M_DR_PROBLEMS "$FAILS"; exit 1; fi
  say M_DR_READY "$WARNS"
}

# ---------------------------------------------------------------- build
make_tag() {
  local sha
  if command -v git >/dev/null 2>&1 && sha="$(git rev-parse --short=12 HEAD 2>/dev/null)"; then
    # the kit state and its config files do not make the tree "dirty"
    if [ -n "$(git status --porcelain -- . ":(exclude,glob)**/$STATE_DIR/**" ":(exclude,glob)**/resources.env" ":(exclude,glob)**/app.env" ":(exclude,glob)**/secrets.map" 2>/dev/null)" ]; then sha="$sha-dirty-$(date -u +%H%M%S)"; fi
    printf 'git-%s' "$sha"
  else
    printf 'ts-%s' "$(date -u +%Y%m%d-%H%M%S)"
  fi
}
# warn when the Dockerfile copies dist/ or build/ from the context but .dockerignore excludes it
check_dockerignore_trap() { # $1=Dockerfile $2=context
  local df="$1" ctx="$2" d ign="$2/.dockerignore"
  [ -f "$df" ] && [ -f "$ign" ] || return 0
  for d in dist build; do
    if grep -E "^[[:space:]]*COPY[[:space:]]" "$df" | grep -v -- '--from=' | grep -Eq "[[:space:]]$d/?([[:space:]]|$)" \
       && grep -Eqx "[[:space:]]*/?$d/?[[:space:]]*" "$ign"; then
      warn M_BUILD_IGNORE_TRAP "$d/" "$d"
    fi
  done
}
cmd_build() {
  local tag="" dfile="$DOCKERFILE" ctx="$BUILD_CONTEXT" extra=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --tag) need "$1" "${2:-}"; tag="$2"; shift 2 ;;
      --dockerfile) need "$1" "${2:-}"; dfile="$2"; shift 2 ;;
      --context) need "$1" "${2:-}"; ctx="$2"; shift 2 ;;
      --) shift; extra=("$@"); break ;;
      *) die M_BUILD_BAD_OPT "$1" ;;
    esac
  done
  [ -n "$tag" ] || tag="$(make_tag)"
  [[ "$tag" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || die M_BAD_TAG "$tag"
  if [ ! -f "$dfile" ]; then
    if [ "$DRY_RUN" = 1 ]; then warn M_BUILD_NO_DOCKERFILE_WARN "$dfile"; else die M_BUILD_NO_DOCKERFILE "$dfile"; fi
  fi
  if [ "$DRY_RUN" != 1 ]; then command -v docker >/dev/null 2>&1 || die M_NO_DOCKER; fi
  check_dockerignore_trap "$dfile" "$ctx"
  local image="$IMAGE_REPO:$tag" meta
  if [ "$DRY_RUN" = 1 ]; then meta="${TMPDIR:-/tmp}/kit-build-meta.XXXXXX"; else meta="$(mktemp "${TMPDIR:-/tmp}/kit-build-meta.XXXXXX")"; fi
  run gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet || { rm -f "$meta"; exit 1; }
  if ! run docker buildx build --platform linux/amd64 -f "$dfile" -t "$image" --metadata-file "$meta" ${extra[@]+"${extra[@]}"} --push "$ctx"; then
    rm -f "$meta"; exit 1
  fi
  local digest=""
  if [ "$DRY_RUN" = 1 ]; then
    digest="sha256:<DIGEST>"
    printf '[dry-run] '; say M_DRY_DIGEST "$image" "$PROJECT_ID"
  else
    [ -f "$meta" ] && digest="$(sed -n 's/.*"containerimage.digest"[: ]*"\(sha256:[0-9a-f]*\)".*/\1/p' "$meta" | head -1)"
    rm -f "$meta"
    [ -n "$digest" ] || digest="$(gcloud artifacts docker images describe "$image" --project "$PROJECT_ID" --format='value(image_summary.digest)')"
    [[ "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die M_NO_DIGEST
    mkdir -p "$STATE_DIR"
    printf '%s@%s\n' "$IMAGE_REPO" "$digest" > "$(state_file)"
  fi
  say M_BUILD_IMAGE "$IMAGE_REPO" "$digest" "$tag"
  say M_BUILD_NEXT
}

# ---------------------------------------------------------------- migrate
# true when MIGRATE_COMMAND has no shell syntax (no quotes, $, ;, &, |, <, >, (), {}, [], *, ?, ~, #, !, backslash, backtick, newline,
# and the first word is not VAR=value): then it can be run directly without "sh -c"
migrate_is_plain() {
  local c="$MIGRATE_COMMAND" first
  case "$c" in
    *\;*|*\&*|*\|*|*\<*|*\>*|*\(*|*\)*|*\{*|*\}*|*\[*|*\]*|*\**|*\?*|*\~*|*\#*|*\!*|*\$*|*\\*|*\`*|*\"*|*\'*|*$'\n'*|*$'\t'*|*$'\r'*) return 1 ;;
  esac
  first="${c%%[[:space:]]*}"
  case "$first" in *=*) return 1 ;; esac
  [ -n "$first" ]
}
do_migrate() { # $1=image given $2=strict(1)/soft(0)
  resolve_image "$1"; gflags; load_app_env; load_secrets_map
  if [ -z "$MIGRATE_COMMAND" ]; then
    if [ "$2" = 1 ]; then stack_hints "${STACK:-custom}"; die M_MIG_NO_CMD; fi
    say M_MIG_SKIP; return 0
  fi
  env_flags update
  local cd="" cand
  for cand in '|' '@' '~' '!' ';' '%'; do case "$MIGRATE_COMMAND" in *"$cand"*) ;; *) cd="$cand"; break ;; esac; done
  [ -n "$cd" ] || die M_DELIM_MIGRATE
  local mig=(--command sh --args "^${cd}^-c${cd}$MIGRATE_COMMAND")
  if migrate_is_plain; then
    # no shell syntax: run it exec-style (works in images without a shell, e.g. distroless)
    local w words=($MIGRATE_COMMAND)
    mig=(--command "${words[0]}" --args "")
    if [ "${#words[@]}" -gt 1 ]; then
      local joined=""; for w in "${words[@]:1}"; do joined="$joined$cd$w"; done
      mig=(--command "${words[0]}" --args "^${cd}^${joined#"$cd"}")
    fi
  fi
  run gcloud run jobs update "$MIGRATE_JOB_NAME" --image "$IMAGE_REF" "${GF[@]}" \
      "${mig[@]}" \
      --add-cloudsql-instances "$SQL_CONNECTION_NAME" \
      --max-retries 0 --task-timeout 600s ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} --quiet
  if ! run gcloud run jobs execute "$MIGRATE_JOB_NAME" "${GF[@]}" --wait --quiet; then
    err_out M_MIG_FAILED "$MIGRATE_JOB_NAME"
    job_logs_hint
    exit 1
  fi
}
cmd_migrate() {
  local image=""
  while [ $# -gt 0 ]; do case "$1" in --image) need "$1" "${2:-}"; image="$2"; shift 2 ;; *) die M_MIG_BAD_OPT "$1" ;; esac; done
  do_migrate "$image" 1
  say M_MIG_DONE
}

# ---------------------------------------------------------------- deploy
cmd_deploy() {
  local image="" skip=0 replace=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --image) need "$1" "${2:-}"; image="$2"; shift 2 ;;
      --skip-migrate) skip=1; shift ;;
      --replace-env) replace=1; shift ;;
      *) die M_DEP_BAD_OPT "$1" ;;
    esac
  done
  resolve_image "$image"; gflags; load_app_env; load_secrets_map
  if [ "$replace" = 1 ]; then
    [ "${#ENV_PAIRS[@]}" -gt 0 ] || [ "${#SECRET_PAIRS[@]}" -gt 0 ] || die M_DEP_REPLACE_EMPTY
    confirm "$(T M_DEP_REPLACE_CONFIRM)" "replace"
  fi
  if [ "$((10#$MIN_INSTANCES))" -gt 0 ]; then confirm "$(T M_MIN_CONFIRM "$MIN_INSTANCES")"; fi
  if [ "$skip" = 1 ]; then say M_DEP_SKIP; else do_migrate "$image" 0; fi
  if [ "$replace" = 1 ]; then env_flags set; else env_flags update; fi
  run gcloud run services update "$SERVICE_NAME" --image "$IMAGE_REF" "${GF[@]}" \
      --port "$PORT" --cpu "$CPU" --memory "$MEMORY" \
      --min-instances "$MIN_INSTANCES" --max-instances "$MAX_INSTANCES" \
      --add-cloudsql-instances "$SQL_CONNECTION_NAME" \
      ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} --quiet
  run gcloud run services update-traffic "$SERVICE_NAME" "${GF[@]}" --to-latest --quiet
  local url; url="$(read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(status.url)')"
  [ "$DRY_RUN" = 1 ] || say M_DEP_DONE "$url"
  say M_DEP_NEXT
}

# ---------------------------------------------------------------- env
# After a rollback the traffic is pinned to one revision; "services update" then creates a new revision with 0% traffic.
warn_if_traffic_pinned() {
  [ "$DRY_RUN" != 1 ] || return 0
  local st; st="$(gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(status.traffic[0].latestRevision.yesno(yes=LATEST,no=PINNED))' 2>/dev/null || true)"
  case "$st" in *PINNED*) warn M_TRAFFIC_PINNED "$SERVICE_NAME" "$SERVICE_NAME" "$PROJECT_ID" "$REGION" ;; esac
}
cmd_env() {
  local sub="${1:-list}"; [ $# -gt 0 ] && shift
  gflags
  local also_job=0 items=() a
  for a in "$@"; do if [ "$a" = "--job" ]; then also_job=1; else items+=("$a"); fi; done
  case "$sub" in
    list)
      say M_ENV_LIST_SVC "$SERVICE_NAME"
      read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(spec.template.spec.containers[0].env[].name)' | tr ';' '\n' | sed 's/^/  - /'
      say M_ENV_LIST_JOB "$MIGRATE_JOB_NAME"
      read_cmd gcloud run jobs describe "$MIGRATE_JOB_NAME" "${GF[@]}" --format='value(spec.template.spec.template.spec.containers[0].env[].name)' | tr ';' '\n' | sed 's/^/  - /'
      ;;
    set)
      [ "${#items[@]}" -gt 0 ] || die M_ENV_SET_USAGE
      local pairs=() k v
      for a in "${items[@]}"; do
        case "$a" in *=*) ;; *) die M_ENV_NEED_KV "$a" ;; esac
        k="${a%%=*}"; v="${a#*=}"
        [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die M_ENV_BAD_NAME "$k"
        check_plain_env "$k" "$v"; pairs+=("$k=$v")
      done
      pick_delim "${pairs[@]}"
      local arg; arg="^${ENV_DELIM}^$(join_by "$ENV_DELIM" "${pairs[@]}")"
      run gcloud run services update "$SERVICE_NAME" "${GF[@]}" --update-env-vars "$arg" --quiet
      [ "$also_job" = 0 ] || run gcloud run jobs update "$MIGRATE_JOB_NAME" "${GF[@]}" --update-env-vars "$arg" --quiet
      warn_if_traffic_pinned
      ;;
    unset)
      [ "${#items[@]}" -gt 0 ] || die M_ENV_UNSET_USAGE
      for a in "${items[@]}"; do [[ "$a" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die M_ENV_BAD_NAME "$a"; done
      local keys; keys="$(join_by , "${items[@]}")"
      if [ "$also_job" = 1 ]; then confirm "$(T M_ENV_UNSET_CONFIRM_JOB "$keys")"; else confirm "$(T M_ENV_UNSET_CONFIRM "$keys")"; fi
      run gcloud run services update "$SERVICE_NAME" "${GF[@]}" --remove-env-vars "$keys" --quiet
      [ "$also_job" = 0 ] || run gcloud run jobs update "$MIGRATE_JOB_NAME" "${GF[@]}" --remove-env-vars "$keys" --quiet
      warn_if_traffic_pinned
      ;;
    *) die M_ENV_BAD_SUB ;;
  esac
}

# ---------------------------------------------------------------- secrets
SLOT_COUNT=5
slot_name() { printf '%s-app-secret-%s' "$PREFIX" "$1"; }
slot_arg() { # check slot number 1-5
  [[ "${1:-}" =~ ^[1-5]$ ]] || die M_SLOT_BAD "${1:-}"
  printf '%s' "$1"
}

secrets_list() {
  gflags
  say M_SL_TITLE
  local n name err rc first
  for n in 1 2 3 4 5; do
    name="$(slot_name "$n")"
    if [ "$DRY_RUN" = 1 ]; then
      printf '[dry-run] gcloud secrets versions access latest --secret=%s --project %s  (%s)\n' "$name" "$PROJECT_ID" "$(T M_DRY_DISCARDED)"
      continue
    fi
    # probe only: stdout (the payload, if any) goes to /dev/null, only stderr is captured
    rc=0; err="$(gcloud secrets versions access latest --secret="$name" --project "$PROJECT_ID" 2>&1 >/dev/null)" || rc=$?
    if [ "$rc" -eq 0 ]; then say M_SL_HAS "$n" "$name"
    elif printf '%s' "$err" | grep -q 'PERMISSION_DENIED'; then say M_SL_NONE "$n" "$name"
    elif printf '%s' "$err" | grep 'FAILED_PRECONDITION' | grep -Eq 'DESTROYED|DISABLED'; then say M_SL_DISABLED "$n" "$name" "$n"
    elif printf '%s' "$err" | grep -q 'NOT_FOUND'; then say M_SL_EMPTY "$n" "$name"
    else
      first="$(printf '%s\n' "$err" | sed -n '1p' | sed -E 's/[A-Za-z0-9+\/=_-]{20,}/[redacted]/g' | cut -c1-160)"
      say M_SL_UNKNOWN "$n" "$name" "${first:-exit $rc}"
    fi
  done
  info ""
  say M_SL_HOW_ADD
  say M_SL_HOW_MAP
}

secrets_add() {
  gflags
  local n from="prompt" file="" name value
  n="$(slot_arg "${1:-}")"; shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --from-stdin) from="stdin"; shift ;;
      --from-file) [ $# -ge 2 ] || die M_ADD_FILE_NEEDS_NAME; from="file"; file="$2"; shift 2 ;;
      *) die M_ADD_UNKNOWN "$1" ;;
    esac
  done
  name="$(slot_name "$n")"
  case "$from" in
    file)
      [ "$DRY_RUN" = 1 ] || [ -f "$file" ] || die M_ADD_NO_FILE "$file"
      if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; show_cmd gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-; return 0; fi
      value="$(cat "$file")"                      # command substitution removes the trailing newline(s) of the file
      value="${value%$'\r'}"                       # and a trailing CR (a CRLF file saved by Notepad)
      [ -n "$value" ] || die M_ADD_EMPTY
      printf '+ '; show_cmd gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-
      printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-
      value="" ;;
    stdin)
      if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; show_cmd gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-; return 0; fi
      [ ! -t 0 ] || die M_ADD_STDIN_TTY
      value="$(cat)"                              # trailing newline(s) are removed (echo / editors add one)
      value="${value%$'\r'}"                       # and a trailing CR (CRLF)
      [ -n "$value" ] || die M_ADD_EMPTY
      printf '+ '; show_cmd gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-
      printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-
      value="" ;;
    prompt)
      if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] %s ' "$(T M_DRY_ASK_HIDDEN)"; show_cmd gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-; return 0; fi
      [ -t 0 ] || die M_ADD_NO_TTY
      T M_ADD_PROMPT "$name" >&2
      IFS= read -rs value; printf '\n' >&2
      [ -n "$value" ] || die M_ADD_EMPTY
      printf '+ '; show_cmd gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-
      printf '%s' "$value" | gcloud secrets versions add "$name" --project "$PROJECT_ID" --data-file=-
      value="" ;;
  esac
  say M_ADD_DONE "$name"
}

secrets_map() {
  local env="${1:-}" n name f line
  [[ "$env" =~ ^[A-Z][A-Z0-9_]*$ ]] || die M_MAP_BAD_ENV
  n="$(slot_arg "${2:-}")"; name="$(slot_name "$n")"
  guard "$(T M_MAP_SLOT_LABEL)" "$name"
  f="$(find_file "$SECRETS_MAP_FILE" secrets.map)"; [ -n "$f" ] || f="./secrets.map"
  line="$env=$name:latest"
  if [ -f "$f" ] && grep -Eq "^[[:space:]]*$env[[:space:]]*=" "$f"; then die M_MAP_EXISTS "$f" "$env"; fi
  if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] '; say M_DRY_FILE_ADD "$f" "$line"; return 0; fi
  if [ -s "$f" ] && [ -n "$(tail -c1 "$f")" ]; then printf '\n' >> "$f"; fi
  printf '%s\n' "$line" >> "$f"
  say M_MAP_DONE "$f" "$line"
}

cmd_secrets() {
  case "${1:-}" in
    list) shift; secrets_list; return 0 ;;
    add) shift; secrets_add "$@"; return 0 ;;
    map) shift; secrets_map "$@"; return 0 ;;
    "") ;;
    *) die M_SEC_BAD_SUB ;;
  esac
  gflags; load_secrets_map
  say M_SEC_MAPPED
  if [ "${#SECRET_PAIRS[@]}" -eq 0 ]; then say M_SEC_EMPTY; else printf '  %s\n' "${SECRET_PAIRS[@]}"; fi
  info ""
  say M_SEC_CHECK
  local names=() p n seen
  for n in "$PREFIX-admin-password" "$PREFIX-demo-password"; do names+=("$n"); done
  for p in ${SECRET_PAIRS[@]+"${SECRET_PAIRS[@]}"}; do
    n="${p#*=}"; n="${n%%:*}"; seen=0
    for p in "${names[@]}"; do [ "$p" = "$n" ] && seen=1; done
    [ "$seen" = 1 ] || names+=("$n")
  done
  for n in "${names[@]}"; do
    if [ "$DRY_RUN" = 1 ]; then printf '[dry-run] gcloud secrets versions access latest --secret=%s --project %s  (%s)\n' "$n" "$PROJECT_ID" "$(T M_DRY_DISCARDED)"
    elif gcloud secrets versions access latest --secret="$n" --project "$PROJECT_ID" >/dev/null 2>&1; then say M_SEC_READABLE "$n"
    else say M_SEC_UNREADABLE "$n"; fi
  done
  info ""
  say M_SEC_ATTACHED
  read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(spec.template.spec.containers[0].env[].valueFrom.secretKeyRef.name)' | tr ';' '\n' | sed '/^$/d;s/^/  - /'
  info ""
  say M_SECRETS_NOTE "$PREFIX"
}

# ---------------------------------------------------------------- logs
cmd_logs() {
  local kind="service" sev="" limit=50 since="1d" follow=0
  while [ $# -gt 0 ]; do
    case "$1" in
      service|job) kind="$1"; shift ;;
      --severity) need "$1" "${2:-}"; sev="$(printf '%s' "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
      --limit) need "$1" "${2:-}"; limit="$2"; shift 2 ;;
      --since) need "$1" "${2:-}"; since="$2"; shift 2 ;;
      --follow|-f) follow=1; shift ;;
      *) die M_LOGS_BAD_OPT "$1" ;;
    esac
  done
  case "$sev" in ''|DEFAULT|DEBUG|INFO|NOTICE|WARNING|ERROR|CRITICAL|ALERT|EMERGENCY) ;; *) die M_LOGS_BAD_SEV ;; esac
  [[ "$limit" =~ ^[0-9]+$ ]] || die M_LOGS_BAD_LIMIT
  [[ "$since" =~ ^[0-9]+[smhd]$ ]] || die M_LOGS_BAD_SINCE
  gflags
  local filter
  if [ "$kind" = job ]; then filter="resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$MIGRATE_JOB_NAME\""
  else filter="resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"$SERVICE_NAME\""; fi
  [ -z "$sev" ] || filter="$filter AND severity>=$sev"
  local fmt='value(timestamp,severity,textPayload,jsonPayload.message)'
  local base=(gcloud logging read)
  local tail_args=(--project "$PROJECT_ID" --bucket=_Default --location=global --view="$LOG_VIEW")
  if [ "$follow" = 0 ]; then
    say M_LOGS_LATEST "$kind"
    run "${base[@]}" "$filter" "${tail_args[@]}" --freshness "$since" --limit "$limit" --order desc --format "$fmt"
    return 0
  fi
  if [ "$DRY_RUN" = 1 ]; then
    run "${base[@]}" "$filter AND timestamp>\"$(T M_PH_LASTTIME)\"" "${tail_args[@]}" --order asc --format "$fmt"
    printf '[dry-run] '; say M_LOGS_FOLLOW_DRY; return 0
  fi
  # KIT_FOLLOW_INTERVAL / KIT_FOLLOW_MAX (seconds / number of polls) exist for the tests; defaults are 5 s and 180 polls (15 minutes)
  local ts out new i=0 fails=0 errf interval="${KIT_FOLLOW_INTERVAL:-5}" max="${KIT_FOLLOW_MAX:-180}"
  local ts_re='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(Z|[+-][0-9:]+)'$'\t'
  errf="$(mktemp "${TMPDIR:-/tmp}/kit-logs-err.XXXXXX")"
  FOLLOW_ERRF="$errf"
  trap 'rm -f "$FOLLOW_ERRF"' EXIT
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  say M_LOGS_FOLLOWING "$kind"
  while [ "$i" -lt "$max" ]; do
    if out="$("${base[@]}" "$filter AND timestamp>\"$ts\"" "${tail_args[@]}" --order asc --limit 200 --format "$fmt" 2>"$errf")"; then
      fails=0
      if [ -n "$out" ]; then
        printf '%s\n' "$out"
        # only a line that starts with an RFC3339 timestamp + TAB is an entry; the other lines are continuation lines of a multi-line message
        new="$(printf '%s\n' "$out" | grep -E "$ts_re" | tail -n 1 | cut -f1 || true)"
        [ -z "$new" ] || ts="$new"
      fi
    else
      fails=$((fails + 1))
      warn M_LOGS_FOLLOW_FAIL "$(sed -n '1,3p' "$errf" | cut -c1-300 | tr '\n' ' ')"
      if [ "$fails" -ge 3 ]; then err_out M_LOGS_FOLLOW_GIVEUP; rm -f "$errf"; exit 1; fi
    fi
    sleep "$interval"; i=$((i + 1))
  done
  rm -f "$errf"
}

# ---------------------------------------------------------------- status
cmd_status() {
  gflags
  local v un; un="$(T M_UNREADABLE)"
  say M_ST_SVC "$SERVICE_NAME"
  v="$(read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(status.url)')";                       [ "$DRY_RUN" = 1 ] || say M_ST_URL "${v:-$un}"
  v="$(read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(status.latestReadyRevisionName)')"; [ "$DRY_RUN" = 1 ] || say M_ST_REV "${v:-$un}"
  v="$(read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(spec.template.spec.containers[0].image)')"; [ "$DRY_RUN" = 1 ] || say M_ST_IMAGE "${v:-$un}"
  say M_ST_ENV
  read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(spec.template.spec.containers[0].env[].name)' | tr ';' '\n' | sed '/^$/d;s/^/  - /'
  say M_ST_JOB "$MIGRATE_JOB_NAME"
  v="$(read_cmd gcloud run jobs describe "$MIGRATE_JOB_NAME" "${GF[@]}" --format='value(spec.template.spec.template.spec.containers[0].image)')"; [ "$DRY_RUN" = 1 ] || say M_ST_IMAGE "${v:-$un}"
  v="$(read_cmd gcloud run jobs executions list --job "$MIGRATE_JOB_NAME" "${GF[@]}" --limit 1 --format='value(metadata.name,status.completionTime,status.succeededCount,status.failedCount)')"
  [ "$DRY_RUN" = 1 ] || say M_ST_EXEC "${v:-$(T M_ST_EXEC_NONE)}"
}

# ---------------------------------------------------------------- open
cmd_open() {
  gflags
  local url; url="$(read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(status.url)')"
  [ "$DRY_RUN" = 1 ] && return 0
  [ -n "$url" ] || die M_OPEN_NO_URL
  info "$url"
  if command -v open >/dev/null 2>&1; then open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$url" >/dev/null 2>&1 || true
  elif command -v wslview >/dev/null 2>&1; then wslview "$url" >/dev/null 2>&1 || true
  elif command -v explorer.exe >/dev/null 2>&1; then explorer.exe "$url" >/dev/null 2>&1 || true   # explorer.exe returns 1 even when it works
  elif command -v start >/dev/null 2>&1; then start "$url" >/dev/null 2>&1 || true
  elif command -v cmd.exe >/dev/null 2>&1; then cmd.exe /c start "" "$url" >/dev/null 2>&1 || true
  fi
}

# ---------------------------------------------------------------- rollback
cmd_rollback() {
  local to=""
  while [ $# -gt 0 ]; do case "$1" in --to) need "$1" "${2:-}"; to="$2"; shift 2 ;; *) die M_RB_BAD_OPT "$1" ;; esac; done
  gflags
  if [ -z "$to" ]; then
    local list cur found=0 r
    list="$(read_cmd gcloud run revisions list --service "$SERVICE_NAME" "${GF[@]}" --sort-by='~metadata.creationTimestamp' --limit 10 --format='value(metadata.name,status.conditions[0].type,status.conditions[0].status)')"
    cur="$(read_cmd gcloud run services describe "$SERVICE_NAME" "${GF[@]}" --format='value(status.traffic[0].revisionName)')"
    if [ "$DRY_RUN" = 1 ]; then to="$(T M_PH_PREV_REV)"
    else
      local ctype cstat
      while read -r r ctype cstat; do
        [ -n "$r" ] || continue
        if [ "$found" = 1 ]; then
          # skip revisions that are known not to be ready (failed deploys); an unknown status is accepted
          if [ "$ctype" = Ready ] && [ -n "$cstat" ] && [ "$cstat" != True ]; then continue; fi
          to="$r"; break
        fi
        [ "$r" = "$cur" ] && found=1
      done <<< "$list"
      [ -n "$to" ] || die M_RB_NO_PREV "${cur:-$(T M_RB_UNKNOWN)}"
    fi
  fi
  case "$to" in "$SERVICE_NAME"-*|'<REVISION_'*) ;; *) die M_RB_NOT_YOURS "$to" "$SERVICE_NAME" ;; esac
  confirm "$(T M_RB_CONFIRM "$to")"
  run gcloud run services update-traffic "$SERVICE_NAME" "${GF[@]}" --to-revisions "$to=100" --quiet
  say M_RB_DONE
}

# ================================================================= main
# Language first, so that even argument errors are shown in the right language.
detect_lang "$@"

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --lang) [ $# -ge 2 ] || die M_NEEDS_VALUE --lang; shift 2 ;;
    --lang=*) shift ;;
    --list-messages) list_messages; exit 0 ;;
    --env-file) [ $# -ge 2 ] || die M_NEEDS_VALUE --env-file; ENV_FILE="$2"; shift 2 ;;
    --app-env) [ $# -ge 2 ] || die M_NEEDS_VALUE --app-env; APP_ENV_FILE="$2"; shift 2 ;;
    --secrets-map) [ $# -ge 2 ] || die M_NEEDS_VALUE --secrets-map; SECRETS_MAP_FILE="$2"; shift 2 ;;
    --stack) [ $# -ge 2 ] || die M_NEEDS_VALUE --stack; STACK_ARG="$2"; shift 2 ;;
    --allow-min-instances) ALLOW_MIN=1; shift ;;
    --allow-plain) [ $# -ge 2 ] || die M_NEEDS_VALUE --allow-plain; check_allow_plain_list "$2"; ALLOW_PLAIN_FLAGS="$ALLOW_PLAIN_FLAGS $2"; shift 2 ;;
    --) ARGS+=("$@"); break ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
[ "${#ARGS[@]}" -gt 0 ] || { cmd_help; exit 0; }
CMD="${ARGS[0]}"
REST=("${ARGS[@]:1}")

case "$CMD" in
  help|-h|--help) cmd_help; exit 0 ;;
  init) cmd_init; exit 0 ;;
  doctor|build|migrate|deploy|env|secrets|logs|status|open|rollback) ;;
  *) die M_UNKNOWN_CMD "$CMD" ;;
esac
load_config
[ "$DRY_RUN" = 1 ] && info "[dry-run] $(T M_DRY_NOTICE)"
"cmd_$CMD" ${REST[@]+"${REST[@]}"}
