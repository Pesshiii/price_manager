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
# Exits non-zero only when every configured channel failed.
# Installed as a copy in /usr/local/bin, like pm-deploy.
set -u

if [ -z "${TG_TOKEN:-}${B24_WEBHOOK:-}" ] && [ -r /etc/pm-deploy.env ]; then
  . /etc/pm-deploy.env
fi

if [ "${1:-}" = --failed ]; then
  text="PM: автодеплой упал
$(journalctl -u pm-deploy.service -n 8 --no-pager -o cat)"
else
  text=${1:?usage: pm-notify TEXT | pm-notify --failed}
fi

echo "$text"
sent=0
failed=0

if [ -n "${B24_WEBHOOK:-}" ] && [ -n "${B24_USER_ID:-}" ]; then
  if curl -fsS --max-time 10 -o /dev/null "${B24_WEBHOOK%/}/im.notify.system.add" \
       --data-urlencode "USER_ID=${B24_USER_ID}" \
       --data-urlencode "MESSAGE=${text}"; then
    sent=$((sent + 1))
  else
    failed=$((failed + 1)); echo "pm-notify: Bitrix24 не принял сообщение" >&2
  fi
fi

if [ -n "${TG_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
  if curl -fsS --max-time 10 -o /dev/null ${TG_PROXY:+--proxy "$TG_PROXY"} \
       "https://api.telegram.org/bot${TG_TOKEN}/sendMessage" \
       --data-urlencode "chat_id=${TG_CHAT_ID}" \
       --data-urlencode "text=${text}"; then
    sent=$((sent + 1))
  else
    failed=$((failed + 1)); echo "pm-notify: Telegram не принял сообщение" >&2
  fi
fi

[ "$failed" -eq 0 ] || [ "$sent" -gt 0 ]
