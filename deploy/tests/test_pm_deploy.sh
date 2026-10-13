#!/usr/bin/env bash
# Exercises every branch of deploy/pm-deploy.sh against throwaway git repos:
# a bare "origin", a "dev" clone that pushes commits, and an "app" clone that
# plays the production checkout. docker, curl and pm-notify are stubs that log
# their calls; jq and flock are the real ones when installed (CI), stubs
# otherwise (Git Bash on Windows).
#
#   bash deploy/tests/test_pm_deploy.sh
#
# A wrong branch in pm-deploy.sh is a production outage, so every change to it
# should come with a scenario here.
set -u

# PM_DEPLOY_SCRIPT: run against another copy, e.g. a deliberately broken one.
SCRIPT=${PM_DEPLOY_SCRIPT:-$(cd "$(dirname "$0")/.." && pwd)/pm-deploy.sh}
W=$(mktemp -d)
trap 'cd /; rm -rf "$W"' EXIT
mkdir -p "$W/bin" "$W/state"
LOG=$W/calls.log

export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.com

# --- stubs -------------------------------------------------------------------
cat > "$W/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$LOG"
[ "$1" = compose ] || exit 0
case "$2" in
  build) [ "${FAIL_BUILD:-0}" = 1 ] && exit 1 ;;
  run)   [ "${FAIL_CHECK:-0}" = 1 ] && exit 1 ;;
  exec)  [ "${FAIL_COLLECT:-0}" = 1 ] && exit 1 ;;
esac
exit 0
EOF
# CI_RESULT, not CI: GitHub Actions sets CI=true for every step.
cat > "$W/bin/curl" <<'EOF'
#!/usr/bin/env bash
url=""; for a in "$@"; do case "$a" in http*) url=$a;; esac; done
case "$url" in
  *api.github.com*)
    echo "curl github $url" >> "$LOG"
    case "${CI_RESULT:-success}" in
      down)       exit 7 ;;
      none)       echo '{"check_runs":[]}' ;;
      inprogress) echo '{"check_runs":[{"status":"in_progress","conclusion":null}]}' ;;
      *)          echo "{\"check_runs\":[{\"status\":\"completed\",\"conclusion\":\"${CI_RESULT:-success}\"}]}" ;;
    esac ;;
  *127.0.0.1*)
    n=$(cat "$W/smoke_n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$W/smoke_n"
    if [ "$n" -le "${SMOKE_FAIL_FIRST:-0}" ]; then printf 500; else printf 200; fi ;;
esac
EOF
printf '#!/bin/sh\necho "notify $*" >> "$LOG"\n' > "$W/bin/pm-notify"
REAL_FLOCK=1
if ! command -v jq >/dev/null; then
  cat > "$W/bin/jq" <<'EOF'
#!/usr/bin/env bash
python -c "import json,sys; r=(json.load(sys.stdin).get('check_runs') or [{}]); print(r[0].get('conclusion') or 'pending')"
EOF
fi
if ! command -v flock >/dev/null; then
  printf '#!/bin/sh\nexit 0\n' > "$W/bin/flock"
  REAL_FLOCK=0
fi
chmod +x "$W"/bin/*

# --- repos -------------------------------------------------------------------
# autocrlf off: with Git for Windows' default a fresh clone looks locally edited.
git init -q --bare -b main "$W/origin.git"
git -c core.autocrlf=false clone -q "$W/origin.git" "$W/dev" 2>/dev/null
cd "$W/dev"
git config core.autocrlf false
mkdir -p price_manager/app/templates
echo a > price_manager/app/views.py
echo a > price_manager/app/templates/x.html
echo a > price_manager/requirements.txt
echo a > Dockerfile; echo a > docker-compose.yml; echo a > README.md
git add -A; git commit -qm init; git push -q origin main
git -c core.autocrlf=false clone -q "$W/origin.git" "$W/app"
git -C "$W/app" config core.autocrlf false

export LOG W PATH="$W/bin:$PATH"
export APP_DIR=$W/app DOMAIN=pm.test WEB_PORT=8000 PM_NOTIFY=$W/bin/pm-notify
export STATE_DIRECTORY=$W/state SMOKE_DELAY=0 SMOKE_INTERVAL=0

PASS=0; FAILED=0
commit() { # message, then the files to touch
  local msg=$1; shift
  for f in "$@"; do mkdir -p "$(dirname "$f")"; echo "$RANDOM" >> "$f"; done
  git add -A; git commit -qm "$msg"; git push -q origin main
}
revert_last() { git revert --no-edit HEAD >/dev/null; git push -q origin main; }
run() { # optional VAR=value overrides
  : > "$LOG"; rm -f "$W/smoke_n"
  env "$@" bash "$SCRIPT" > "$W/out.txt" 2>&1; RC=$?
  HEAD=$(git -C "$W/app" rev-parse HEAD)
}
expect() { # description, condition
  if eval "$2"; then PASS=$((PASS+1)); echo "  ok   $1"
  else
    FAILED=$((FAILED+1)); echo "  FAIL $1"
    echo "------ output"; cat "$W/out.txt"; echo "------ calls"; cat "$LOG"; echo "------"
  fi
}
has() { grep -qF -- "$1" "$LOG"; }
said() { grep -qF -- "$1" "$W/out.txt"; }
line_of() { grep -nF -- "$1" "$LOG" | head -1 | cut -d: -f1; }
before() { # both calls happened, the first one earlier
  local a b; a=$(line_of "$1"); b=$(line_of "$2")
  [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]
}
dev_head() { git -C "$W/dev" rev-parse HEAD; }
app_head() { git -C "$W/app" rev-parse HEAD; }
skipped() { [ "$(cat "$W/state/skipped" 2>/dev/null)" = "$(dev_head)" ]; }
unskip() { rm -f "$W/state/skipped"; }

echo "1. nothing new"
run
expect "rc 0" '[ $RC = 0 ]'
expect "no docker, no GitHub call" '! has docker && ! has "curl github"'

echo "2. CI not green: no runs yet, in progress, red, GitHub down"
commit tpl price_manager/app/templates/x.html
OLD=$(app_head)
for r in none inprogress failure down; do
  run CI_RESULT=$r
  expect "$r: rc 0, not merged, no docker" '[ $RC = 0 ] && [ $HEAD = $OLD ] && ! has docker'
done
run CI_RESULT=inprogress
expect "in progress reads as pending" 'said pending'

echo "3. template -> check, collectstatic, HUP, workers restarted"
run
expect "rc 0, merged" '[ $RC = 0 ] && [ $HEAD = $(dev_head) ]'
expect "check in web and worker" 'has "compose run --rm --no-deps -T web python manage.py check" && has "compose run --rm --no-deps -T celery_worker python manage.py check"'
expect "collectstatic" 'has "compose exec -T web python manage.py collectstatic --noinput"'
expect "HUP, no build" 'has "compose kill -s HUP web" && ! has "compose build"'
expect "check before HUP" 'before "manage.py check" "kill -s HUP"'
expect "workers restarted with timeout" 'has "compose restart --timeout 3600 celery_worker celery_worker_pim"'

echo "4. static only -> HUP, workers untouched"
commit css price_manager/static/css/x.css price_manager/app/static/app/y.js
run
expect "rc 0, merged" '[ $RC = 0 ] && [ $HEAD = $(dev_head) ]'
expect "HUP, no restart" 'has "compose kill -s HUP web" && ! has "compose restart"'

echo "5. python -> HUP, beat and workers restarted, db/redis never touched"
commit py price_manager/app/views.py
run
expect "rc 0, merged" '[ $RC = 0 ] && [ $HEAD = $(dev_head) ]'
expect "beat restarted" 'has "compose restart celery_beat"'
expect "db/redis untouched" '! grep -E "compose (up|restart|build|stop).* (db|redis)( |$)" "$LOG"'

echo "6. docs, tests, .claude/ -> merged, nothing restarted"
commit docs README.md .claude/knowledge/x.md price_manager/app/tests/test_x.py price_manager/app/tests.py price_manager/app/notes.md
run
expect "rc 0, merged" '[ $RC = 0 ] && [ $HEAD = $(dev_head) ]'
expect "no docker" '! has docker && said "перезапуск не нужен"'

echo "7. migration -> skipped and reported once, before the merge"
commit mig price_manager/app/migrations/0002_x.py
OLD=$(app_head)
run
expect "rc 0, not merged" '[ $RC = 0 ] && [ $HEAD = $OLD ]'
expect "reported, skip file" 'has "notify PM: в main до" && skipped'
expect "no docker" '! has docker'
run
expect "next tick silent" '[ $RC = 0 ] && ! has notify && ! has "curl github"'
commit py2 price_manager/app/views.py
run
expect "a commit on top is still blocked, reported again" '[ $HEAD = $OLD ] && has "notify PM: в main до"'
git -C "$W/app" merge -q --ff-only origin/main; unskip   # the human deploy

echo "8. check fails -> reset, skipped, containers untouched"
commit badpy price_manager/app/views.py
OLD=$(app_head)
run FAIL_CHECK=1
expect "rc 1, rolled back, clean tree" '[ $RC = 1 ] && [ $HEAD = $OLD ] && [ -z "$(git -C "$W/app" status --porcelain)" ]'
expect "skipped" 'skipped'
expect "no HUP, restart or up" '! has "kill -s HUP" && ! has "compose restart" && ! has "compose up"'
run
expect "next tick skips it" '[ $RC = 0 ] && ! has docker'
unskip; revert_last

echo "9. requirements -> build, check, recreate web, then workers"
commit deps price_manager/requirements.txt
run
expect "rc 0, merged" '[ $RC = 0 ] && [ $HEAD = $(dev_head) ]'
expect "app services built" 'has "compose build web celery_worker celery_worker_pim celery_beat"'
expect "web recreated, no HUP" 'has "compose up -d --no-deps --force-recreate web" && ! has "kill -s HUP"'
expect "workers recreated" 'has "compose up -d --no-deps --force-recreate --timeout 3600 celery_beat celery_worker celery_worker_pim"'
expect "build < check < recreate" 'before "compose build" "manage.py check" && before "manage.py check" "force-recreate web"'

echo "10. build fails -> reset, nothing recreated"
commit deps2 price_manager/requirements.txt
OLD=$(app_head)
run FAIL_BUILD=1
expect "rc 1, rolled back" '[ $RC = 1 ] && [ $HEAD = $OLD ]'
expect "no check, no up" '! has "manage.py check" && ! has "compose up"'
unskip; revert_last

echo "11. smoke fails, rollback recovers"
commit brokentpl price_manager/app/templates/x.html
OLD=$(app_head)
run SMOKE_FAIL_FIRST=12
expect "rc 1, rolled back" '[ $RC = 1 ] && [ $HEAD = $OLD ]'
expect "web recreated, not HUPed again" 'has "compose up -d --no-deps --force-recreate web" && [ $(grep -c "kill -s HUP" "$LOG") = 1 ]'
expect "says the site answers" 'said "сайт отвечает"'
expect "workers untouched" '! has "restart celery"'
unskip; revert_last

echo "12. smoke fails after a rebuild, rollback does not recover"
commit docker Dockerfile
OLD=$(app_head)
run SMOKE_FAIL_FIRST=999
expect "rc 1, rolled back" '[ $RC = 1 ] && [ $HEAD = $OLD ]'
expect "old image rebuilt, web recreated twice" '[ $(grep -c "compose build" "$LOG") = 2 ] && [ $(grep -c "force-recreate web" "$LOG") = 2 ]'
expect "asks for a human" 'said "нужен человек"'
expect "workers untouched" '! has "celery_beat celery_worker"'
unskip; revert_last

echo "13. collectstatic fails -> web recreated on the old code"
commit tpl2 price_manager/app/templates/x.html
OLD=$(app_head)
run FAIL_COLLECT=1
expect "rc 1, rolled back" '[ $RC = 1 ] && [ $HEAD = $OLD ]'
expect "web recreated, no HUP" 'has "force-recreate web" && ! has "kill -s HUP"'
unskip; revert_last

echo "14. deploy scripts changed -> reinstall notice, nothing restarted"
commit deployscript deploy/pm-deploy.sh deploy/README.md
run
expect "rc 0, notice, no docker" '[ $RC = 0 ] && has "установите их заново" && ! has docker'

echo "15. local edit in the checkout -> merge refused, edit kept"
commit py3 price_manager/app/views.py
echo local >> "$W/app/price_manager/app/views.py"
OLD=$(app_head)
run
expect "rc 1, not merged, skipped" '[ $RC = 1 ] && [ $HEAD = $OLD ] && skipped'
expect "edit kept, no docker" 'grep -q local "$W/app/price_manager/app/views.py" && ! has docker'
git -C "$W/app" checkout -q -- .; unskip

echo "16. success is reported when NOTIFY_SUCCESS=1"
run NOTIFY_SUCCESS=1
expect "rc 0, reported" '[ $RC = 0 ] && has "notify PM: выкачен main до"'

if [ "$REAL_FLOCK" = 1 ]; then
  echo "17. a run while the previous one holds the lock exits quietly"
  commit py4 price_manager/app/views.py
  flock "$W/state/lock" sleep 3 &
  sleep 1
  run
  wait
  expect "rc 0, nothing done" '[ $RC = 0 ] && ! has "curl github" && said "ещё идёт"'
fi

echo
echo "pm-deploy.sh: $PASS passed, $FAILED failed"
[ "$FAILED" = 0 ]
