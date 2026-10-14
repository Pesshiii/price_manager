#!/usr/bin/env bash
# Autodeploy: brings the production checkout up to origin/main once CI on the
# new commit is green. Run by pm-deploy.timer every two minutes; the whole
# procedure, and what it deliberately leaves to a human, is in deploy/README.md.
#
# Installed as a COPY in /usr/local/bin, never run from the checkout. Bash reads
# a script while running it, so a merge that rewrote this file mid-run would
# execute half of each version. And a merged commit must not be able to change
# what runs with docker-group (root-equivalent) rights unnoticed.
set -euo pipefail

: "${APP_DIR:?APP_DIR is not set (/etc/pm-deploy.env)}"
: "${DOMAIN:?DOMAIN is not set (/etc/pm-deploy.env)}"
WEB_PORT=${WEB_PORT:-8000}
REPO=${REPO:-Pesshiii/price_manager}
CI_CHECK=${CI_CHECK:-Django test suite}
PM_NOTIFY=${PM_NOTIFY:-/usr/local/bin/pm-notify}
STATE_DIR=${STATE_DIRECTORY:-/var/lib/pm-deploy}
# The SHA that must not be deployed automatically (migrations, a rollback). The
# timer skips it until main moves on, or until a human deletes the file.
SKIP_FILE=$STATE_DIR/skipped
# When the current run of failed fetches began (epoch seconds), and whether the
# owner has been told about it.
FETCH_FAILING=$STATE_DIR/fetch-failing
FETCH_ALERTED=$STATE_DIR/fetch-alerted
FETCH_ALERT_AFTER=${FETCH_ALERT_AFTER:-1800}
# db and redis are never touched here: a database restart is never automatic.
APP_SERVICES=(web celery_worker celery_worker_pim celery_beat)

REBUILD=false
APPLIED=false

log() { echo "$*"; }
notify() { log "$*"; if [ -x "$PM_NOTIFY" ]; then "$PM_NOTIFY" "$*" || true; fi; }
dc() { docker compose "$@"; }
subject() { git log -1 --format='%h «%s»' "$1"; }

# The login page is exempt from the login gate and renders base.html, so a 200
# also proves the static manifest. Waits first ($1 seconds): after a HUP the old
# gunicorn workers keep answering while the new ones boot, and a recreated web
# runs collectstatic before gunicorn starts. Three 200s in a row pass.
smoke() {
  local ok=0 code
  sleep "${SMOKE_DELAY:-$1}"
  for _ in $(seq 12); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      -H "Host: $DOMAIN" -H 'X-Forwarded-Proto: https' \
      "http://127.0.0.1:$WEB_PORT/accounts/login/" || true)
    if [ "$code" = 200 ]; then ok=$((ok + 1)); else ok=0; fi
    if [ "$ok" -ge 3 ]; then return 0; fi
    sleep "${SMOKE_INTERVAL:-5}"
  done
  return 1
}

# Django boots on the new code in both environments; the worker's parses extra
# settings at import. This is what keeps a bad commit from taking the site
# down: a gunicorn worker that fails to boot after a HUP halts the whole master
# (HaltServer), and restart: unless-stopped then loops the container on the same
# broken, bind-mounted code. Fresh containers, so a rebuilt image is checked too.
django_check() {
  dc run --rm --no-deps -T web python manage.py check &&
    dc run --rm --no-deps -T celery_worker python manage.py check
}

# Puts $OLD back after a failed step, then exits non-zero, so OnFailure= sends
# the tail of this log. Until APPLIED the running containers never left the old
# code (the image tag is rebuilt only so the next `up` does not pick up the new
# one). After it web is recreated, not HUPed: the master may be dead.
# Never `git clean` here: media/ and staticfiles/ live in the tree, gitignored.
fail() {
  log "Ошибка: $1. Откатываю ${NEW:0:7} → ${OLD:0:7}."
  git reset -q --hard "$OLD"
  echo "$NEW" > "$SKIP_FILE"
  if $REBUILD; then dc build "${APP_SERVICES[@]}" || log "Не удалось пересобрать образ старой версии."; fi
  if $APPLIED; then
    dc up -d --no-deps --force-recreate web
    if smoke 45; then
      log "Откат на ${OLD:0:7} выполнен, сайт отвечает."
    else
      log "Откат на ${OLD:0:7} выполнен, но сайт НЕ отвечает — нужен человек."
    fi
  else
    log "Откат на ${OLD:0:7} выполнен, работающие контейнеры не трогались."
  fi
  exit 1
}

# A failed fetch is retried on the next tick, and a network blip must not send
# a message every two minutes. But while fetch fails, nothing is ever deployed
# and nothing else says so. So the owner is told once per run of failures: at
# once for a permission error, which never heals by itself (git was run in the
# checkout as another user, usually root, and left files in .git that this user
# cannot write), otherwise after FETCH_ALERT_AFTER seconds.
fetch() {
  local err now
  if err=$(git fetch -q origin main 2>&1); then
    if [ -f "$FETCH_ALERTED" ]; then notify "PM: git fetch снова проходит, автодеплой работает."; fi
    rm -f "$FETCH_FAILING" "$FETCH_ALERTED"
    return 0
  fi
  log "git fetch не прошёл: $err"
  now=$(date +%s)
  if [ ! -f "$FETCH_FAILING" ]; then echo "$now" > "$FETCH_FAILING"; fi
  if [ -f "$FETCH_ALERTED" ]; then return 1; fi
  if grep -qiE 'permission denied|insufficient permission' <<<"$err"; then
    touch "$FETCH_ALERTED"
    notify "PM: автодеплой стоит — у $(id -un) нет прав на запись в $APP_DIR/.git. Похоже, git в чекауте запускали от другого пользователя. Исправление: sudo chown -R $(id -un): $APP_DIR/.git (deploy/README.md)."
  elif [ $((now - $(cat "$FETCH_FAILING"))) -ge "$FETCH_ALERT_AFTER" ]; then
    touch "$FETCH_ALERTED"
    notify "PM: автодеплой стоит — git fetch не проходит с $(date -d "@$(cat "$FETCH_FAILING")" '+%d.%m %H:%M' 2>/dev/null || cat "$FETCH_FAILING"): ${err##*$'\n'}"
  fi
  return 1
}

deployed() {
  log "Выкачен main до $(subject HEAD)$1."
  if [ "${NOTIFY_SUCCESS:-0}" = 1 ]; then notify "PM: выкачен main до $(subject HEAD)$1."; fi
}

main() {
  cd "$APP_DIR"
  mkdir -p "$STATE_DIR"
  exec 9>"$STATE_DIR/lock"
  if ! flock -n 9; then log "Предыдущий запуск ещё идёт."; exit 0; fi

  if ! fetch; then exit 0; fi
  OLD=$(git rev-parse HEAD)
  NEW=$(git rev-parse origin/main)
  if [ "$OLD" = "$NEW" ]; then exit 0; fi
  if [ -f "$SKIP_FILE" ] && [ "$(cat "$SKIP_FILE")" = "$NEW" ]; then exit 0; fi

  # Only what CI passed goes out. Pending, or GitHub unreachable: the next tick
  # retries. A red main waits for the next green commit.
  local ci
  ci=$(curl -fsS --max-time 20 \
         "https://api.github.com/repos/$REPO/commits/$NEW/check-runs?check_name=${CI_CHECK// /%20}" \
       | jq -r '.check_runs[0].conclusion // "pending"') || { log "GitHub API недоступен."; exit 0; }
  if [ "$ci" != success ]; then log "CI для ${NEW:0:7}: $ci, жду."; exit 0; fi

  CHANGED=$(git diff --name-only "$OLD" "$NEW")

  # Migrations are deployed by hand (deploy/README.md). Checked before the merge:
  # the code is bind-mounted, so merged code is live at once, and new code on the
  # old schema is exactly what must not happen.
  if grep -qE '^price_manager/[^/]+/migrations/[^/]+\.py$' <<<"$CHANGED"; then
    echo "$NEW" > "$SKIP_FILE"
    notify "PM: в main до $(subject "$NEW") есть миграции — автодеплой остановлен, нужен ручной деплой (deploy/README.md)."
    exit 0
  fi

  if ! git merge -q --ff-only "$NEW"; then
    echo "$NEW" > "$SKIP_FILE"
    log "git merge --ff-only не прошёл: в чекауте локальные правки или он разошёлся с main."
    exit 1
  fi

  if grep -qE '^deploy/(pm-deploy\.sh|pm-notify\.sh|systemd/)' <<<"$CHANGED"; then
    notify "PM: в ${NEW:0:7} изменились скрипты деплоя — установите их заново (deploy/README.md)."
  fi

  # What changes the running app: not docs, tests, .claude/ or .github/.
  local runtime
  runtime=$(grep -E '^(price_manager/|Dockerfile$|docker-compose\.yml$)' <<<"$CHANGED" \
              | grep -vE '(\.md$|/tests/|/tests\.py$)' || true)
  if [ -z "$runtime" ]; then deployed ", перезапуск не нужен"; exit 0; fi

  if grep -qE '^(Dockerfile|docker-compose\.yml|price_manager/requirements\.txt)$' <<<"$runtime"; then
    REBUILD=true
    dc build "${APP_SERVICES[@]}" || fail "docker compose build не прошёл"
  fi

  django_check || fail "manage.py check не прошёл"

  APPLIED=true
  if $REBUILD; then
    dc up -d --no-deps --force-recreate web || fail "не удалось пересоздать web"
    smoke 45 || fail "страница входа не отвечает"
  else
    dc exec -T web python manage.py collectstatic --noinput || fail "collectstatic не прошёл"
    dc kill -s HUP web || fail "не удалось отправить HUP в web"
    smoke 20 || fail "страница входа не отвечает"
  fi

  # Beat and the workers: after a rebuild, or when anything but static changed.
  # Templates count: the exports render tables through them, and with
  # DEBUG=false every worker process caches the templates it has loaded. A
  # worker first finishes its running tasks, up to stop_grace_period; new tasks
  # wait in Redis meanwhile.
  if $REBUILD; then
    dc up -d --no-deps --force-recreate --timeout 3600 celery_beat celery_worker celery_worker_pim
  elif grep -qvE '^price_manager/([^/]+/)?static/' <<<"$runtime"; then
    dc restart celery_beat
    dc restart --timeout 3600 celery_worker celery_worker_pim
  fi

  deployed ""
}

main "$@"
