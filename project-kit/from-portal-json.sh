#!/usr/bin/env bash
if grep -q $'\r' "${BASH_SOURCE[0]}" 2>/dev/null; then printf 'Error: this file has Windows line endings (CRLF). Fix: dos2unix kit.sh from-portal-json.sh   or   sed -i "s/\\r$//" kit.sh from-portal-json.sh   (see README, Windows section)\n' >&2; exit 1; fi #
# from-portal-json.sh - convert the resources JSON downloaded from the portal into resources.env
# usage:  ./from-portal-json.sh <prefix>-resources.json [-o resources.env] [--force] [--lang en|th]
#         (older name: lab5-<prefix>-handoff.json - both work; the portal zip already has a filled resources.env)
#         -o -   print to stdout   (uses the python3 on your computer, no jq needed)
# Language of messages: --lang en|th, else env KIT_LANG, else Thai if LC_ALL / LC_MESSAGES / LANG
# starts with "th", else English (default). Same rules as kit.sh.
set -eo pipefail

KIT_LANG_ACTIVE=en

# =============================================================== message catalog
# printf format strings; %s = argument, \n = new line, \047 = single quote.
# Every key must exist in BOTH msg_en and msg_th (see ./from-portal-json.sh --list-messages).
MSG_KEYS="M_ERR M_WARN M_NEEDS_VALUE M_BAD_LANG M_UNKNOWN_OPT M_USAGE M_ONE_FILE M_NO_FILE M_NO_PYTHON M_PY_STUB M_EXISTS M_CREATED M_HELP
M_PY_JSON_READ M_PY_NOT_OBJECT M_PY_NO_RESOURCES M_PY_MISSING M_PY_UNSAFE M_PY_BAD_PREFIX M_PY_BAD_IMAGE_REPO M_PY_REGISTRY_MISMATCH M_PY_PREVIEW"

msg_en() {
  case "$1" in
    M_ERR) printf '%s' 'Error:' ;;
    M_WARN) printf '%s' 'Warning:' ;;
    M_NEEDS_VALUE) printf '%s' '%s needs a value' ;;
    M_BAD_LANG) printf '%s' '--lang must be en or th (got \047%s\047)' ;;
    M_UNKNOWN_OPT) printf '%s' 'unknown option %s' ;;
    M_USAGE) printf '%s' 'usage: %s <prefix>-resources.json [-o resources.env]  (or lab5-<prefix>-handoff.json)' ;;
    M_ONE_FILE) printf '%s' 'give only one file' ;;
    M_NO_FILE) printf '%s' 'file not found: %s' ;;
    M_NO_PYTHON) printf '%s' 'python3 is required (install Python 3 from https://www.python.org/downloads/ , or fill in resources.env yourself from resources.example.env)' ;;
    M_PY_STUB) printf '%s' 'python3 was found but it does not run (on Windows this is usually the Microsoft Store shortcut). Fix: install Python 3 from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), or turn off the python.exe / python3.exe entries in Windows Settings > Apps > Advanced app settings > App execution aliases, then open a new terminal. Or fill in resources.env yourself from resources.example.env' ;;
    M_EXISTS) printf '%s' '%s already exists (use --force to overwrite, or -o another-name)' ;;
    M_CREATED) printf '%s' 'created %s - check STACK / PORT / MIGRATE_COMMAND, then run ./kit.sh doctor' ;;
    M_HELP) printf '%s' 'from-portal-json.sh - convert the resources JSON downloaded from the portal into resources.env\nusage:  ./from-portal-json.sh <prefix>-resources.json [-o resources.env] [--force] [--lang en|th]\n        (the file from the portal Team resources button is named <prefix>-resources.json; the older name lab5-<prefix>-handoff.json works too)\n        -o -   print to stdout   (uses the python3 on your computer, no jq needed)' ;;
    M_PY_JSON_READ) printf '%s' 'cannot read the JSON file (%s) - it must be the file downloaded from the Team resources tab' ;;
    M_PY_NOT_OBJECT) printf '%s' 'the JSON structure is not valid (it must be an object)' ;;
    M_PY_NO_RESOURCES) printf '%s' 'the key \047resources\047 is not in the JSON - this file may not be a resources handoff from the portal' ;;
    M_PY_MISSING) printf '%s' 'the JSON is missing required keys: %s\n  If your team is not activated yet, activate it in the portal first, or ask the TA' ;;
    M_PY_UNSAFE) printf '%s' 'the value of %s has unexpected characters, so it was not converted (for safety)' ;;
    M_PY_BAD_PREFIX) printf '%s' 'prefix \047%s\047 is not valid' ;;
    M_PY_BAD_IMAGE_REPO) printf '%s' 'the format of resources.image_repository is not valid: %s' ;;
    M_PY_REGISTRY_MISMATCH) printf '%s' 'the registry in image_repository (%s) does not match resources.registry (%s)' ;;
    M_PY_PREVIEW) printf '%s' 'this JSON is a plan (preview); the resources are not really created yet - wait until the activation is finished before you use the kit' ;;
    *) return 1 ;;
  esac
}

msg_th() {
  case "$1" in
    M_ERR) printf '%s' 'ผิดพลาด:' ;;
    M_WARN) printf '%s' 'คำเตือน:' ;;
    M_NEEDS_VALUE) printf '%s' '%s ต้องมีค่า' ;;
    M_BAD_LANG) printf '%s' '--lang ต้องเป็น en หรือ th (ได้ \047%s\047)' ;;
    M_UNKNOWN_OPT) printf '%s' 'ไม่รู้จักตัวเลือก %s' ;;
    M_USAGE) printf '%s' 'ใช้: %s <prefix>-resources.json [-o resources.env]  (หรือ lab5-<prefix>-handoff.json)' ;;
    M_ONE_FILE) printf '%s' 'ระบุไฟล์ได้ไฟล์เดียว' ;;
    M_NO_FILE) printf '%s' 'ไม่พบไฟล์ %s' ;;
    M_NO_PYTHON) printf '%s' 'ต้องมี python3 (ติดตั้ง Python 3 จาก https://www.python.org/downloads/ หรือกรอก resources.env เองจาก resources.example.env)' ;;
    M_PY_STUB) printf '%s' 'พบ python3 แต่รันไม่ได้ (บน Windows มักเป็นทางลัด Microsoft Store) วิธีแก้: ติดตั้ง Python 3 จาก https://www.python.org/downloads/ (ติ๊ก "Add python.exe to PATH") หรือปิดรายการ python.exe / python3.exe ใน Windows Settings > Apps > Advanced app settings > App execution aliases แล้วเปิด terminal ใหม่ หรือกรอก resources.env เองจาก resources.example.env' ;;
    M_EXISTS) printf '%s' 'มี %s อยู่แล้ว (ใช้ --force เพื่อเขียนทับ หรือ -o ชื่ออื่น)' ;;
    M_CREATED) printf '%s' 'สร้าง %s แล้ว — ตรวจค่า STACK/PORT/MIGRATE_COMMAND แล้วรัน ./kit.sh doctor' ;;
    M_HELP) printf '%s' 'from-portal-json.sh — แปลงไฟล์ resources JSON ที่โหลดจาก portal เป็น resources.env\nใช้:  ./from-portal-json.sh <prefix>-resources.json [-o resources.env] [--force] [--lang en|th]\n      (ไฟล์จากปุ่ม Team resources ของ portal ชื่อ <prefix>-resources.json ส่วนชื่อเก่า lab5-<prefix>-handoff.json ก็ใช้ได้)\n      -o -   พิมพ์ลง stdout     (ใช้ python3 ที่มีอยู่ในเครื่อง ไม่ต้องใช้ jq)' ;;
    M_PY_JSON_READ) printf '%s' 'อ่านไฟล์ JSON ไม่ได้ (%s) — ต้องเป็นไฟล์ที่โหลดจากแท็บ Team resources' ;;
    M_PY_NOT_OBJECT) printf '%s' 'โครงสร้าง JSON ไม่ถูกต้อง (ต้องเป็น object)' ;;
    M_PY_NO_RESOURCES) printf '%s' 'ไม่พบ key \047resources\047 ใน JSON — ไฟล์นี้อาจไม่ใช่ resources handoff ของ portal' ;;
    M_PY_MISSING) printf '%s' 'ใน JSON ไม่มี key ที่จำเป็น: %s\n  ถ้ากลุ่มยังไม่ถูก activate ให้ activate ที่ portal ก่อน หรือแจ้ง TA' ;;
    M_PY_UNSAFE) printf '%s' 'ค่าของ %s มีอักขระที่ไม่คาดคิด จึงไม่แปลงให้เพื่อความปลอดภัย' ;;
    M_PY_BAD_PREFIX) printf '%s' 'prefix \047%s\047 ไม่ถูกต้อง' ;;
    M_PY_BAD_IMAGE_REPO) printf '%s' 'รูปแบบ resources.image_repository ไม่ถูกต้อง: %s' ;;
    M_PY_REGISTRY_MISMATCH) printf '%s' 'registry ใน image_repository (%s) ไม่ตรงกับ resources.registry (%s)' ;;
    M_PY_PREVIEW) printf '%s' 'JSON นี้เป็นแผน (preview) ทรัพยากรยังไม่ถูกสร้างจริง — รอ activate ให้เสร็จก่อนใช้ kit' ;;
    *) return 1 ;;
  esac
}

T() {
  local key="$1" fmt; shift
  if [ "$KIT_LANG_ACTIVE" = th ]; then fmt="$(msg_th "$key")" || fmt=""; else fmt="$(msg_en "$key")" || fmt=""; fi
  [ -n "$fmt" ] || fmt="$key"
  # shellcheck disable=SC2059
  printf -- "$fmt" "$@"
}
die2() { printf '%s %s\n' "$(T M_ERR)" "$(T "$@")" >&2; exit 2; }   # usage / input errors: exit 2

list_messages() {
  local k en th
  for k in $MSG_KEYS; do
    en=0; th=0
    [ -n "$(msg_en "$k" 2>/dev/null)" ] && en=1
    [ -n "$(msg_th "$k" 2>/dev/null)" ] && th=1
    printf '%s en=%s th=%s\n' "$k" "$en" "$th"
  done
}

# language: --lang, else KIT_LANG, else locale (th*), else English
detect_lang() {
  local want="" prev="" a l
  for a in "$@"; do
    if [ "$prev" = "--lang" ]; then want="$a"; break; fi
    case "$a" in --lang=*) want="${a#--lang=}"; break ;; esac
    prev="$a"
  done
  if [ -n "$want" ]; then
    case "$want" in en|th) KIT_LANG_ACTIVE="$want"; return 0 ;; *) die2 M_BAD_LANG "$want" ;; esac
  fi
  l="$(printf '%s' "${KIT_LANG:-}" | tr '[:upper:]' '[:lower:]')"
  case "$l" in en|th) KIT_LANG_ACTIVE="$l"; return 0 ;; esac
  l="${LC_ALL:-}"; [ -n "$l" ] || l="${LC_MESSAGES:-}"; [ -n "$l" ] || l="${LANG:-}"
  case "$l" in th*|TH*) KIT_LANG_ACTIVE=th ;; *) KIT_LANG_ACTIVE=en ;; esac
}
detect_lang "$@"

IN=""; OUT="resources.env"; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    -o|--output) [ $# -ge 2 ] || die2 M_NEEDS_VALUE -o; OUT="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --lang) [ $# -ge 2 ] || die2 M_NEEDS_VALUE --lang; shift 2 ;;
    --lang=*) shift ;;
    --list-messages) list_messages; exit 0 ;;
    -h|--help) T M_HELP; printf '\n'; exit 0 ;;
    -*) die2 M_UNKNOWN_OPT "$1" ;;
    *) [ -z "$IN" ] || die2 M_ONE_FILE; IN="$1"; shift ;;
  esac
done
[ -n "$IN" ] || { T M_USAGE "$0" >&2; printf '\n' >&2; exit 2; }
[ -f "$IN" ] || die2 M_NO_FILE "$IN"
# find a working Python 3 (the Windows Store "python3" stub exists but fails to run)
PY=""; PY_FOUND=0
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then
    PY_FOUND=1
    if "$cand" -c 'import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)' >/dev/null 2>&1; then PY="$cand"; break; fi
  fi
done
if [ -z "$PY" ]; then if [ "$PY_FOUND" = 1 ]; then die2 M_PY_STUB; else die2 M_NO_PYTHON; fi; fi
if [ "$OUT" != "-" ] && [ -e "$OUT" ] && [ "$FORCE" != 1 ]; then
  die2 M_EXISTS "$OUT"
fi

# messages for the python part: raw printf formats passed in the environment (FP_<KEY>)
for k in M_ERR M_WARN M_PY_JSON_READ M_PY_NOT_OBJECT M_PY_NO_RESOURCES M_PY_MISSING M_PY_UNSAFE M_PY_BAD_PREFIX M_PY_BAD_IMAGE_REPO M_PY_REGISTRY_MISMATCH M_PY_PREVIEW; do
  if [ "$KIT_LANG_ACTIVE" = th ]; then v="$(msg_th "$k")"; else v="$(msg_en "$k")"; fi
  export "FP_$k=$v"
done

TMP="$(mktemp "${TMPDIR:-/tmp}/kit-env.XXXXXX")"
trap 'rm -f "$TMP"' EXIT
"$PY" -I - "$IN" "$TMP" <<'PY'
import json, os, re, sys

def M(key, *args):
    text = os.environ["FP_" + key].replace("\\047", "'").replace("\\n", "\n")
    return text % args if args else text

def fail(msg):
    sys.stderr.write(M("M_ERR") + " " + msg + "\n")
    sys.exit(1)

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    fail(M("M_PY_JSON_READ", e))
if not isinstance(data, dict):
    fail(M("M_PY_NOT_OBJECT"))
res = data.get("resources")
if not isinstance(res, dict):
    fail(M("M_PY_NO_RESOURCES"))

missing = [k for k in ("project_id", "region", "prefix") if not data.get(k)]
missing += ["resources." + k for k in ("cloud_run_service", "migration_job", "registry",
            "image_repository", "runtime_service_account", "sql_connection_name") if not res.get(k)]
if missing:
    fail(M("M_PY_MISSING", ", ".join(missing)))

safe = re.compile(r"^[A-Za-z0-9._:/@-]+$")
for k, v in [("project_id", data["project_id"]), ("region", data["region"]), ("prefix", data["prefix"])] + \
            [("resources." + k, v) for k, v in res.items() if isinstance(v, str)]:
    if not isinstance(v, str) or not safe.match(v):
        fail(M("M_PY_UNSAFE", k))

prefix = data["prefix"]
if not re.fullmatch(r"[a-z][a-z0-9]{2,9}", prefix):
    fail(M("M_PY_BAD_PREFIX", prefix))
m = re.fullmatch(r"([a-z0-9-]+)-docker\.pkg\.dev/([^/]+)/([^/]+)/(.+)", res["image_repository"])
if not m:
    fail(M("M_PY_BAD_IMAGE_REPO", res["image_repository"]))
registry, image_name = m.group(3), m.group(4)
if registry != res["registry"]:
    fail(M("M_PY_REGISTRY_MISMATCH", registry, res["registry"]))

if data.get("created_in_google_cloud") is False or data.get("mode") == "preview":
    sys.stderr.write(M("M_WARN") + " " + M("M_PY_PREVIEW") + "\n")

# Comments written into resources.env are bilingual (English first, Thai second).
lines = [
    "# Generated from the portal JSON by from-portal-json.sh (no secrets)",
    "# สร้างจาก portal JSON โดย from-portal-json.sh (ไม่มีความลับ)",
    "PROJECT_ID=" + data["project_id"],
    "REGION=" + data["region"],
    "PREFIX=" + prefix,
    "SERVICE_NAME=" + res["cloud_run_service"],
    "MIGRATE_JOB_NAME=" + res["migration_job"],
    "REGISTRY=" + registry,
    "IMAGE_NAME=" + image_name,
    "RUNTIME_SA=" + res["runtime_service_account"],
    "SQL_CONNECTION_NAME=" + res["sql_connection_name"],
    "# Set these for your own app",
    "# ตั้งตามแอปของคุณ",
    "STACK=custom",
    "PORT=8080",
    "#MIGRATE_COMMAND=",
]
if res.get("database_secret"):
    lines.append("# Secrets prepared by the portal (use them in secrets.map) / secret ที่ portal เตรียมไว้: " + res["database_secret"] +
                 ", " + str(res.get("admin_password_secret", "")) + ", " + str(res.get("demo_password_secret", "")))
# Python writes the file itself (UTF-8, LF): nothing is printed to the console, so a non-UTF-8
# Windows console cannot break it.
with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as out:
    out.write("\n".join(lines) + "\n")
PY

if [ "$OUT" = "-" ]; then cat "$TMP"; else cp "$TMP" "$OUT"; T M_CREATED "$OUT" >&2; printf '\n' >&2; fi
