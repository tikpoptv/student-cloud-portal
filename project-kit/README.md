# Project Kit — Put your team project on Cloud Run

[ภาษาไทย](README.th.md) | **English**

This kit is for the **final project**. It uses the Google Cloud resources that the portal prepared for your team.
It works with **any language or framework** (Node, Python, Java, Go, static web + API, and others). You only need a `Dockerfile`.
**You do not need Lab 5 and you do not need GitHub.** (If you want to connect GitHub later, there is an example workflow. It is optional.)

## What you get from the portal (already created for you)

| Resource | Name (if your team prefix is `grp01`) |
|---|---|
| Cloud Run service (public) | `grp01` |
| Cloud Run job for migrations | `grp01-migrate` |
| PostgreSQL database (Cloud SQL) | instance `grp01-pg` |
| Docker image storage (Artifact Registry) | repo `grp01` |
| Service account that runs your app | `grp01-runner@cpe-se-course-2026.iam.gserviceaccount.com` |
| Secrets in Secret Manager | `grp01-database-url`, `grp01-admin-password`, `grp01-demo-password` |
| Log reading view | view `grp01` |

The Google Cloud project is `cpe-se-course-2026`, region `asia-southeast1`. You can see the real names for your team in the **Team resources** tab of the portal.

## Before you start

1. **gcloud CLI** — install from https://cloud.google.com/sdk/docs/install, then run `gcloud auth login`.
   **Log in with the same Gmail address that you registered in the portal.** If you use another account, you will not have permission.
2. **Docker Desktop** (keep it open before you build), with `docker buildx`.
3. **bash** (macOS and Linux already have it; on Windows use WSL or Git Bash - see [Windows](#windows)).
4. Your project has a `Dockerfile`, and your app **listens on the port in the `PORT` variable** and binds to `0.0.0.0`.
   (You do not have a Dockerfile yet? See step 2.)

## Quickstart in 5 steps

Copy the `project-kit/` folder into your project. You can also run it from another place, but first `cd` to your project folder, because `build` uses the Dockerfile in the current folder. The examples below assume the kit is in `./project-kit/`.

**1) Check your team resource information**
The zip that you download from the portal **already contains a filled `project-kit/resources.env`** for your team. **Do not overwrite it** with `cp resources.example.env resources.env` (that file is only an example with `grp01`). Open `project-kit/resources.env` and set `STACK` (node|python|java|go|static|custom) and `PORT` to match your app.
Only if you do not have a `resources.env` (for example you copied the kit from somewhere else), create one in one of these ways:
```sh
# a) download the JSON from the portal (the Team resources button saves <prefix>-resources.json; the older name was lab5-<prefix>-handoff.json - both work) and convert it:
./project-kit/from-portal-json.sh ~/Downloads/<prefix>-resources.json
# b) or copy the example and edit PREFIX and the other values to match the Team resources tab:
cp project-kit/resources.example.env resources.env
```
If your app has a database that needs migration, set `MIGRATE_COMMAND` (see the FAQ).

**Where does kit.sh look for the config files?** For `resources.env`, `app.env` and `secrets.map` it looks first in the **current folder** (where you run the command), then in the **kit folder** (the folder that contains `kit.sh`, for example `project-kit/`). The first one found is used. `--env-file`, `--app-env` and `--secrets-map` point to a file directly (if you give one of these flags and the file does not exist, kit.sh stops with an error instead of skipping it). `from-portal-json.sh` writes `./resources.env` in the current folder unless you give `-o`. The `Dockerfile` (for `build`) is always taken from the current folder.

**2) Check your Dockerfile** (skip this if you already have one)
```sh
./project-kit/kit.sh --stack python init     # creates an example Dockerfile and .dockerignore if they do not exist
```
`init` never guesses the stack: without `--stack` (and without a `STACK=` line in `resources.env`) it stops and lists the valid stacks `node|python|java|go|static`. `--stack` always wins over `resources.env`. An **existing `Dockerfile` or `.dockerignore` is never overwritten**; to start over, delete the file (`rm Dockerfile`) and run `init` again.
`init` also adds `.kit-state/`, `resources.env`, `app.env` and `secrets.map` to your `.gitignore` (it creates the file if there is none), so these files are never committed and do not make the image tag `-dirty`. For `--stack static`, the `.dockerignore` does not exclude `dist/` and `build/` (the static Dockerfile copies `dist/`). `build` warns if your Dockerfile copies `dist/` or `build/` but `.dockerignore` excludes it. The Node template is multi-stage: it installs all dependencies (`npm ci` if you have a `package-lock.json`, otherwise `npm install`, so yarn / pnpm projects work), runs `npm run build` if you have a build script, then keeps only production dependencies. **Prisma users:** `npm prune --omit=dev` removes devDependencies, including the `prisma` CLI, so either keep `prisma` in `dependencies` or delete the `npm prune` line in the Dockerfile (otherwise `npx prisma migrate deploy` fails). The Python, Node and Java templates give `/app` to the non-root user so your app can write files there; the Go template runs on alpine (it has a shell, so `MIGRATE_COMMAND=/app/server migrate` works) and an app that writes files should use `/tmp`.

**3) Check that everything is ready**
```sh
./project-kit/kit.sh doctor
```
If you see `[FAIL]`, the line below it tells you how to fix it. The most common problem is logging in with the wrong account.

**4) Build and push the image**
```sh
./project-kit/kit.sh build
```
The image is built for `linux/amd64` (this also works on Mac M1/M2/M3). It gets a tag from the git SHA or the time (`-dirty-` is added only when tracked or new project files changed; `.kit-state/`, `resources.env`, `app.env` and `secrets.map` are ignored for this check). The fixed image digest is saved in `.kit-state/`.

**5) Deploy**
```sh
./project-kit/kit.sh deploy
./project-kit/kit.sh status      # shows the URL
./project-kit/kit.sh open        # opens it in the browser
```
`deploy` runs the migration first (if you set `MIGRATE_COMMAND`). If the migration fails, it **stops and does not deploy**, and it tells you how to read the log.

> You can add `--dry-run` to every command. It **shows the commands without running them**. We recommend you try it first, for example `./project-kit/kit.sh --dry-run deploy`.

## All commands

| Command | What it does |
|---|---|
| `doctor` | Checks gcloud, docker, login, permissions and resources |
| `init` | Creates an example Dockerfile for the `--stack` |
| `build [--tag T] [--dockerfile F] [--context DIR]` | Build, push, and save the digest |
| `migrate [--image REF]` | Runs only the migration job |
| `deploy [--skip-migrate] [--image REF] [--replace-env]` | Migrate, then deploy |
| `env list` / `env set K=V [--job]` / `env unset K [--job]` | Show, set or remove env variables (names only) |
| `secrets` | Shows secrets that are mapped and readable (values are never shown) |
| `secrets list` / `secrets add <1-5> [--from-stdin\|--from-file F]` / `secrets map <ENV_NAME> <1-5>` | Manage your team secret slots `<prefix>-app-secret-1..5` for your own API keys |
| `logs [service\|job] [--severity ERROR] [--limit 100] [--since 2h] [--follow]` | Reads logs |
| `status` | URL, revision, image, env names, last job result |
| `open` | Opens the website |
| `rollback [--to REVISION]` | Moves traffic to the previous **ready** revision (traffic is then pinned to it; `deploy` routes to the latest again) |

Global flags: `--dry-run`, `--yes`, `--env-file`, `--app-env`, `--secrets-map`, `--stack`, `--allow-min-instances`, `--allow-plain NAME`, `--lang en|th`

Messages print the command the way you started it (for example `./project-kit/kit.sh deploy`).

### Message language (English / Thai)

`kit.sh` and `from-portal-json.sh` can show messages in English or Thai. The language is chosen in this order:
1. The flag `--lang en` or `--lang th`
2. The variable `KIT_LANG=en` or `KIT_LANG=th`
3. If `LC_ALL`, `LC_MESSAGES` or `LANG` starts with `th`, Thai is used
4. Otherwise **English** is used (the default)

Examples: `./project-kit/kit.sh --lang th doctor`, or `export KIT_LANG=th`.
The words you type to confirm are the same in both languages: answer `y` or `yes` to a [y/N] question, and type the English word `replace` for `deploy --replace-env`.
The gcloud and docker commands shown by `--dry-run` are the same in every language.

## Windows

- **Use WSL (recommended) or Git Bash.** In WSL (Ubuntu), install gcloud and Docker Desktop with WSL integration, and keep your project inside the Linux home folder (for example `~/myproject`), not under `/mnt/c`. Git Bash also works, but WSL has fewer surprises. PowerShell and `cmd` cannot run `kit.sh`.
- **python3 is needed** only for `from-portal-json.sh`. On Windows the `python3` command can be a Microsoft Store shortcut that does nothing; the script detects this and tells you to install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH") or to turn off the App execution aliases.
- **"permission denied"**: the zip can lose the executable bit when it is extracted (for example by Finder on macOS, or by some Windows tools). Either run `chmod +x project-kit/*.sh`, or run the script through bash: `bash project-kit/kit.sh doctor`.
- **Line endings**: `kit.sh` must have LF line endings. If Git or an editor changed them to CRLF, running `./project-kit/kit.sh` fails with `env: bash\r: No such file or directory` or `bad interpreter: /usr/bin/env bash^M` (when run as `bash project-kit/kit.sh` you may see `set: pipefail: invalid option name`, or kit.sh stops with a "Windows line endings" message). Fix: `dos2unix project-kit/*.sh` or `sed -i 's/\r$//' project-kit/*.sh` (on macOS: `sed -i '' 's/\r$//' project-kit/*.sh`), and make sure `.gitattributes` has `*.sh text eol=lf`. The kit ships a `.gitattributes` file (`*.sh text eol=lf`) that prevents Git from converting them; keep it inside `project-kit/` (or copy its line to your repository's `.gitattributes`). Also, in Git for Windows, run `git config core.autocrlf input` before you clone or add the kit.
- **Git Bash path conversion** (unverified tip): Git Bash may rewrite arguments that start with `/` (it turns `/cloudsql/...` into a Windows path). kit.sh does not need such arguments, but if one of your own gcloud commands breaks because of this, run it with `MSYS_NO_PATHCONV=1` in front, for example `MSYS_NO_PATHCONV=1 gcloud ...`.

## FAQ

**How do I change the env variables of my app?**
- For values that are not secret (for example `LOG_LEVEL`, `TZ`): edit the file `app.env` (copy it from `app.env.example`), then run `./project-kit/kit.sh deploy`.
- For a quick change: `./project-kit/kit.sh env set LOG_LEVEL=debug` (add `--job` if the migrate job also needs it) or `./project-kit/kit.sh env unset LOG_LEVEL`.
- A normal deploy uses **add or update only the named variables** mode. Other env variables (including the `DATABASE_URL` that the portal set) are not removed.
- `deploy --replace-env` **replaces everything**, and you must type a confirmation yourself. Use it only when you know what you are doing.
- You cannot set `PORT` in `app.env` (Cloud Run sets it). Set it in `resources.env`.
- Quoted values: use single quotes (`'...'`) or double quotes; backslash escapes such as `\"` inside a quoted value are **not** supported, and a value is read up to the next quote character.
- Files are read tolerantly: a BOM, Windows line endings, trailing spaces and a `# comment` after a value (space + `#`) are ignored. A bad line is reported by file and line number only (the text of the line is never printed).
- **Env values are masked in everything kit.sh prints**: the commands in `--dry-run` and in the normal run show `--update-env-vars '^@^LOG_LEVEL=***'`, never the value.
- **kit.sh refuses secret-looking names and values** in `app.env` and `env set`. The exact rules:
  - **Name**: the name is split on `_` and checked word by word (there is no substring matching, so `AUTHOR_NAME`, `PASSPORT_STRATEGY`, `MONKEY_MODE`, `NEXTAUTH_URL` and `AUTH_TRUST_HOST` are fine). A name is refused when it has one of these whole words: `SECRET`, `PASSWORD`, `PASSWD`, `PWD`, `PASS`, `CREDENTIAL`, `CREDENTIALS`, `SIGNATURE`, `DSN`; `TOKEN` (unless the next word is `EXPIRE...`, `TTL`, `MINUTES`, `SECONDS`, `HOURS`, `DAYS`, `ROUNDS`, `TYPE`, `URL`, `HOST` or `NAME`, so `ACCESS_TOKEN_EXPIRE_MINUTES` is fine); `PRIVATE_KEY`; `DATABASE_URL`; `CONNECTION_STRING`; `KEY` as the last word or in `API_KEY`, `SECRET_KEY`, `ACCESS_KEY`, `AUTH_KEY` (so `STRIPE_KEY`, `OPENAI_API_KEY` are refused but `PUBLIC_KEY_URL` is fine); and `AUTH` alone. A name that ends in `_URL`, `_HOST`, `_PORT`, `_ROUNDS`, `_MINUTES`, `_SECONDS`, `_TTL`, `_NAME`, `_ID`, `_ENABLED`, `_MODE`, `_LABEL`, `_DIR` or `_PATH` skips only the `KEY` / `AUTH` rules (`GOOGLE_CLIENT_ID` and `KEYCLOAK_URL` are fine; `GOOGLE_CLIENT_SECRET` is refused).
  - **Value**: only strong signals are refused: a value that starts with `sk-`, `sk_live_`, `sk_test_`, `AIza`, `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_`, `github_pat_`, `xox?-`, or `AKIA` / `ASIA` followed by 16 letters or digits; a value that contains `-----BEGIN` or a JWT (`eyJ...` `.` `eyJ...` `.`); or a high-entropy blob, which means 32 or more characters from `A-Za-z0-9+/=_-` that contain at least one digit and one letter and are either mixed case or 40+ characters long. These are **not** treated as a blob: a path (starts with `/`, or lowercase segments separated by `/`), a URL, a slug of three or more lowercase words joined by `-` or `_` (for example `cpe-se-course-2026-team-abc-uploads-bucket`), and a 40-character hex git SHA. Ordinary values such as `/var/lib/myapp/uploads/public/images` or `REGION_LABEL=ASIA-SE` pass.
  - The message names the variable only (never the value) and tells you to use `secrets add` and `secrets map`.
  - **False positive? Allow it explicitly.** Use the flag `--allow-plain NAME` (repeat it for more names; for example `./project-kit/kit.sh --allow-plain MY_TOKEN_LABEL env set MY_TOKEN_LABEL=abc`) or put a line `ALLOW_PLAIN=NAME1,NAME2` in `app.env` or `resources.env`. Both skip the name check and the value check for those names only; their values are still masked in everything kit.sh prints. Never use this for a real secret.
- **After a `rollback`, traffic is pinned to one revision.** `env set` / `env unset` then create a new revision that gets 0% of the traffic, and kit.sh prints a warning about it. Run `./project-kit/kit.sh deploy` (it routes traffic to the latest revision), or `gcloud run services update-traffic <service> --to-latest --project <project> --region <region>`.

**How do I use a password or an API key?** Never put it in env, `app.env`, code or git. Use the secret slots of your team.
The portal creates 5 empty slots for your team, named `<prefix>-app-secret-1` to `-5`. You can "add a version" and "read" only these 5 slots. You cannot create a new secret, disable or delete a version, or touch other secrets.
1. `./project-kit/kit.sh secrets list` — shows the status of each slot. The status comes from an access probe (`gcloud secrets versions access latest`, because members cannot list versions); the output of the probe is thrown away, so values are never printed. `has a value` = the probe worked; `READY / EMPTY` = the slot exists but has no version yet (`secrets add` works on empty slots); `NO ACCESS or NOT CREATED FOR YOUR TEAM` = permission denied, ask the TA; `latest version is DISABLED/DESTROYED` = a TA disabled or destroyed the latest version, run `secrets add N` to add a new value (a new version becomes the latest); `UNKNOWN error` = shows the first line of the error.
2. `./project-kit/kit.sh secrets add 1` — type the value with hidden input (nothing is shown on the screen, nothing goes into the shell history, nothing is written to a file). Or send it by pipe: `printf '%s' "$VALUE" | ./project-kit/kit.sh secrets add 1 --from-stdin`, or use `--from-file FILE`. kit.sh never accepts the value as an argument. With `--from-stdin` and `--from-file`, **the trailing newline(s) and one trailing carriage return are removed** (so a value saved by an editor, `echo` or Windows Notepad (CRLF) does not get an invisible character at the end). Spaces at the start or end are kept.
3. `./project-kit/kit.sh secrets map MY_API_KEY 1` — adds the line `MY_API_KEY=grp01-app-secret-1:latest` to `secrets.map`.
4. `./project-kit/kit.sh deploy` — your app can now read it with `process.env.MY_API_KEY` or `os.environ["MY_API_KEY"]`.

Important to know:
- **After you add a value, students cannot read it back from the web or the Cloud Console** (the portal does not show secret values). Always keep the real value in your own place (for example, the API key page of your provider).
- **To change a value (rotate), add a new version** (run `./project-kit/kit.sh secrets add N` again). The old version is not deleted. An app that uses `:latest` gets the new value at the next deploy or new revision.
- **Do not send secret values in team chat or in an AI chat.**
- If `secrets list` says `NO ACCESS or NOT CREATED FOR YOUR TEAM`, the slot for your team was not created yet (or it is not yours). Ask the TA. An empty slot (`READY / EMPTY`) is normal: just run `secrets add`.

`./project-kit/kit.sh secrets` (with no subcommand) shows the secrets that are mapped and readable (values are never shown). kit.sh refuses env names that contain `KEY`, `PASSWORD`, `SECRET`, `TOKEN` and similar words, and secret-looking values (see above).

If `secrets.map` has a wrong line, the error shows only the line number and the ENV name, never the value.

**How do I run a migration?** Set it in `resources.env`, for example
`MIGRATE_COMMAND=npx prisma migrate deploy`, `alembic upgrade head`, `python manage.py migrate`, or `/app/server migrate`.
This command runs **inside your image** and has the same env, secrets and Cloud SQL as the service. If the command has no shell syntax (no quotes, `$`, `;`, `&`, `|`, `<`, `>`, `()`, `{}`, `*`, `?`, `~`, `#`, `!`, backslash, and it does not start with `VAR=value`), it is started directly (exec-style, so it also works in an image without a shell). Otherwise it is run with `sh -c`, so the image needs a shell.
To run it alone: `./project-kit/kit.sh migrate`. If you do not need a migration (for example, a static website), leave it empty and `deploy` will skip it.
(Spring with Flyway, which migrates when the app starts, can also leave it empty.)

**How do I read the logs?** `./project-kit/kit.sh logs` (service), `./project-kit/kit.sh logs job` (migration), `--severity ERROR`, `--since 30m`, `--follow` (live view; it stops by itself after 15 minutes; if gcloud fails, the error is printed and it stops after 3 failures in a row). `--severity` accepts DEFAULT, DEBUG, INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT or EMERGENCY.

**How does my app connect to the database?** The service and the job are connected to Cloud SQL, and the secret `DATABASE_URL` is already attached (through the `/cloudsql/...` socket, not TCP). Your app should read `DATABASE_URL`.
The URL from the portal looks like `postgresql://user:***@localhost/db?host=/cloudsql/...&schema=public&connection_limit=3` (Prisma style). Some libraries (for example SQLAlchemy/psycopg2, JDBC, Go pq) cannot read the `schema` and `connection_limit` parameters. Remove these parameters in your code, or ask the TA for a secret in another format.

**How do I connect to the database from my own computer (Cloud SQL Auth Proxy)?**
```sh
gcloud auth application-default login
# download cloud-sql-proxy: https://cloud.google.com/sql/docs/postgres/sql-proxy
cloud-sql-proxy cpe-se-course-2026:asia-southeast1:grp01-pg --port 5433
psql "host=127.0.0.1 port=5433 user=grp01 dbname=grp01"
```
Your role is Cloud SQL Client (you can connect), but you **cannot read the database password yourself** (the secrets `database-url` and `database-password` can be used only by the app). If you want to connect from your computer, ask the TA how to get the password safely, or run your database work through the migrate job instead.
The user and database name are usually the team prefix (check the Team resources tab).

**How do I go back when a deploy breaks?** `./project-kit/kit.sh rollback` (moves traffic to the previous ready revision; revisions that failed are skipped). Note: it **does not undo migrations or database data**. After a rollback the traffic is **pinned** to that revision: a new revision (also one created by `env set` / `env unset`) gets 0% until you run `./project-kit/kit.sh deploy`, which routes traffic to the latest revision again.

**Can I work without Docker on my computer?** This kit builds with Docker on your computer. If you cannot install it, ask the TA (your role does not include Cloud Build).

**How do I change size or port?** Use `CPU`, `MEMORY`, `MAX_INSTANCES` and `PORT` in `resources.env`. Credit is shared by about 38 teams, so kit.sh enforces limits: `CPU` at most 2, `MEMORY` at most 2Gi, `MAX_INSTANCES` 1-3, and `MIN_INSTANCES` must be 0. To keep instances always running (`MIN_INSTANCES` above 0) you need the TA's agreement, then add the flag `--allow-min-instances` (for example `./project-kit/kit.sh --allow-min-instances deploy`); kit.sh asks you to confirm.

### What you cannot do, and who to ask

| What you need | Can you do it yourself? | Who to ask |
|---|---|---|
| Create, change or delete a new secret | No (read only) | TA / portal |
| Configure, create or grow Cloud SQL (more machines, a 2nd instance, a new tier) | No | TA |
| Change IAM, create a service account, create a new service or project | No | TA |
| See or touch resources of another team | No (and kit.sh refuses) | — |
| Forgot the app password, or need the database password | You can read `admin-password` and `demo-password` with `gcloud secrets versions access` (be careful not to paste the result anywhere) | TA |
| Connect GitHub / use GitHub Actions | Optional | TA enables WIF for you (see `templates/deploy.github-actions.example.yml`) |
| Your own domain, more quota or credit | No | TA |

If you are stuck: run `./project-kit/kit.sh doctor` and send the result to the TA (**do not attach passwords or secret values**).

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| `doctor` says you are not logged in to gcloud | Run `gcloud auth login` and choose the Gmail you registered in the portal. Check with `gcloud auth list`. |
| `doctor` fails, or a resource is not found | Check that `PREFIX`, `PROJECT_ID` and `REGION` in `resources.env` match the Team resources tab. You may be using the wrong project (kit.sh adds `--project` to every command by itself, so do not mix in your own gcloud commands for another project). If it still fails, ask the TA. |
| `permission denied` / `PERMISSION_DENIED` on a list command (for example `gcloud run services list`) | Your permission covers only your team resources. List commands for the whole project do not work, and this is normal. Use `./project-kit/kit.sh status` or `./project-kit/kit.sh doctor`, which only use your team resource names. |
| Docker platform problem on Apple Silicon (M1/M2/M3): the image does not run on Cloud Run, or the platform is wrong | kit.sh already builds with `--platform linux/amd64`. Do not use a plain `docker build`. Docker Desktop must be open and have `docker buildx`. The first build can be slow because amd64 is emulated. |
| `secrets add` says there is no terminal | Hidden input needs a real terminal. If you run it from a script or an IDE without a terminal, use `--from-stdin` (pipe) or `--from-file FILE` instead. |
| Messages are in the wrong language | Use `--lang en` or `--lang th`, or set `KIT_LANG`. |

## Important warnings

- **Never put secrets in env / app.env / code / git / AI chat** (passwords, tokens, API keys, a real DATABASE_URL). Use `secrets.map` only.
  Do not push `resources.env`, `app.env` and `secrets.map` to a public git repository (they are already in the example `.dockerignore`).
- **Database: only 1 instance per team.** Do not ask for or create more. If you need more, use several databases or schemas in the same instance (ask the TA).
- **Credit is shared by the whole course.** The service starts with `min-instances 0` and `max-instances 1` (no users = no cost).
  Do not set min-instances above 0 (kit.sh refuses it unless you add `--allow-min-instances`), do not use high CPU or memory (kit.sh caps them at 2 CPU and 2Gi), and do not run load tests without permission. Cloud SQL costs money all the time, even when nobody uses it.
- **Do not delete any resource** (service, job, instance, repo, secret), even if you think you do not use it. You cannot create it again yourself. You must wait for the TA.
- Images you push take a small amount of space and money. Do not build very often without a reason.
- The service is **public**. Anyone with the URL can open it. Do not expose personal data in an endpoint that has no login.
- kit.sh **refuses every command** whose resource name does not start with your team `PREFIX`, and it never shows secret values.

## File layout

```
project-kit/
  README.md                 this guide (English)
  README.th.md              guide in Thai (ภาษาไทย)
  kit.sh                    main command
  from-portal-json.sh       converts <prefix>-resources.json (or lab5-<prefix>-handoff.json) from the portal -> resources.env
  resources.env             (only in the portal zip) your team resource information, already filled
  resources.example.env     an example of resources.env (only if you need to create one)
  app.env.example           plain env variables (copy to app.env)
  secrets.map.example       maps ENV -> existing secret (copy to secrets.map)
  templates/                example Dockerfiles (node/python/go/java/static), .dockerignore, GitHub Actions (optional)
  .gitattributes            keeps *.sh with LF line endings (Windows)
```

The zip from the portal contains only the files above (plus your filled `resources.env`). The offline test suite lives in the course repository and is **not** shipped in the zip.

Config files (`resources.env`, `app.env`, `secrets.map`) are searched first in the current folder, then in the kit folder (or point to them with `--env-file`, `--app-env`, `--secrets-map`; an explicit path that does not exist is an error).
