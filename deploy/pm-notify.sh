#!/bin/sh
# pm-notify TEXT      send TEXT to the owner
# pm-notify --failed  send the tail of the last pm-deploy run (pm-deploy-failed.service)
#
# Every configured channel gets the text:
#   - Bitrix24: B24_WEBHOOK (an inbound webhook with the `im` scope) and
#     B24_USER_ID get a system notification (im.notify.system.add);
#   - Telegram: TG_TOKEN and TG_CHAT_ID, a personal bot and chat, not the group
#     bot of .claude/telegram-bot/. TG_PROXY (any curl --proxy URL) is for a
#     server that cannot reach api.telegram.org directly.
# With none configured it only prints, so the journal still has the text.
# Each channel gets NOTIFY_ATTEMPTS tries (see send). Exits non-zero only when
# every configured channel failed.
# Installed as a copy in /usr/local/bin, like pm-deploy.
set -u

if [ -z "${TG_TOKEN:-}${B24_WEBHOOK:-}" ] && [ -r /etc/pm-deploy.env ]; then
  . /etc/pm-deploy.env
fi
NOTIFY_ATTEMPTS=${NOTIFY_ATTEMPTS:-3}
NOTIFY_RETRY_DELAY=${NOTIFY_RETRY_DELAY:-10}

if [ "${1:-}" = --failed ]; then
  text="PM: автодеплой упал
$(journalctl -u pm-deploy.service -n 8 --no-pager -o cat)"
else
  text=${1:?usage: pm-notify TEXT | pm-notify --failed}
fi

# send NAME CURL_ARGS... posts once per attempt, waiting NOTIFY_RETRY_DELAY
# seconds longer before each retry. Retried: no answer at all (a network error
# or a timeout, http_code 000), 408, 429 and 5xx. Any other 4xx means a wrong
# token, chat or webhook, and repeating it would only hold up the deploy that
# is waiting for this message.
send() {
  name=$1; shift
  attempt=1
  while :; do
    code=$(curl -sS --connect-timeout 5 --max-time 15 -o /dev/null -w '%{http_code}' "$@")
    case "${code:-000}" in
      2??) return 0 ;;
      000|408|429|5??) ;;
      *) echo "pm-notify: $name ответил $code, повторять не буду" >&2; return 1 ;;
    esac
    if [ "$attempt" -ge "$NOTIFY_ATTEMPTS" ]; then
      echo "pm-notify: $name не принял сообщение (попыток: $attempt, последний ответ: ${code:-000})" >&2
      return 1
    fi
    sleep $((NOTIFY_RETRY_DELAY * attempt))
    attempt=$((attempt + 1))
  done
}

echo "$text"
sent=0
failed=0

if [ -n "${B24_WEBHOOK:-}" ] && [ -n "${B24_USER_ID:-}" ]; then
  if send Bitrix24 "${B24_WEBHOOK%/}/im.notify.system.add" \
       --data-urlencode "USER_ID=${B24_USER_ID}" \
       --data-urlencode "MESSAGE=${text}"; then
    sent=$((sent + 1))
  else
    failed=$((failed + 1))
  fi
fi

if [ -n "${TG_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
  if send Telegram ${TG_PROXY:+--proxy "$TG_PROXY"} \
       "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       --data-urlencode "chat_id=${TG_CHAT_ID}" \
       --data-urlencode "text=${text}"; then
    sent=$((sent + 1))
  else
    failed=$((failed + 1))
  fi
fi

[ "$failed" -eq 0 ] || [ "$sent" -gt 0 ]
