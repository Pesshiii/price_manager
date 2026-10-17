# Автодеплой на прод

Прод — git-чекаут, запущенный через `docker compose`; код подключён в контейнеры
томом (`./price_manager:/app`), образ несёт только зависимости. Поэтому обычный
коммит не требует пересборки: достаточно обновить чекаут и мягко перезапустить
процессы.

`pm-deploy.timer` раз в две минуты запускает `pm-deploy` (копию
[pm-deploy.sh](pm-deploy.sh)). Он выкатывает `origin/main`, только когда на этом
коммите зелёный CI («Django test suite»).

| Что изменилось | Что делает автодеплой | Простой |
|---|---|---|
| только `.md`, тесты, `.claude/`, `.github/`, `deploy/` | `git merge`, без перезапуска | нет |
| только статика (`static/`) | `manage.py check` → `collectstatic` → HUP gunicorn | нет |
| Python, шаблоны | то же + перезапуск beat и воркеров (выгрузки рендерят шаблоны) | нет у сайта; задачи ждут в Redis, пока воркер доделывает текущие (до 60 мин) |
| `requirements.txt`, `Dockerfile`, `docker-compose.yml` | `build` → `check` → пересоздание web, затем воркеров | несколько секунд у сайта |
| миграции | **ничего**: останавливается и присылает сообщение | — |

После переключения скрипт проверяет страницу входа. Если `check`, сборка,
`collectstatic` или проверка не прошли, он возвращает чекаут на прежний коммит,
запоминает плохой SHA в `/var/lib/pm-deploy/skipped` (дальше не пробует, пока
main не уйдёт вперёд) и присылает сообщение (Bitrix24 или Telegram, см. шаг 5).

**Никогда не автоматически:** миграции, `db` и `redis` (перезапуск базы — только
руками), `.env`, nginx и сами скрипты деплоя (после их правки — снова шаг 5).

**В чекауте прода нельзя `git clean`:** `media/` (загруженные прайсы) и
`staticfiles/` лежат внутри него и попадают под gitignore.

**git в чекауте — только от его владельца**, того же пользователя, что в
`User=` сервиса. Команды ниже написаны так:

```bash
cd /путь/к/чекауту && OWNER=$(stat -c '%U' .)
sudo -u "$OWNER" -H git status
```

Если запустить git от root, в чекауте останутся файлы root, и автодеплой на них
споткнётся:
- **в `.git`** — `fetch` упадёт с `Permission denied`, скрипт сразу пришлёт
  сообщение;
- **в рабочем дереве** (например, каталог, который git создал при `merge` от root)
  — `merge` не сможет записать файл. Скрипт вернёт чекаут на прежний коммит и
  остановится на этом SHA.

Найти такие файлы:

```bash
sudo find . -path ./price_manager/media -prune -o -path ./price_manager/staticfiles -prune -o ! -user "$OWNER" -print
```

Вернуть владельца можно ровно этим путям: `sudo chown -R "$OWNER": <пути>`, для
`.git` — `sudo chown -R "$OWNER": .git`. Весь чекаут так не переписывать:
`media/` и `staticfiles/` принадлежат пользователю контейнера (uid 1011).

Если `fetch` не проходит по другой причине (сеть, GitHub), скрипт молча
повторяет попытки. Сообщение приходит, если сбой длится дольше 30 минут
(`FETCH_ALERT_AFTER` в `/etc/pm-deploy.env`), и ещё одно — когда `fetch` снова
пройдёт.

## Подключение (один раз, по порядку)

Порядок важен:
- Django должен узнать домен (шаги 1 и 3) раньше, чем nginx начнёт его
  передавать (шаг 4), иначе каждый запрос получит 400.
- nginx должен ходить на `127.0.0.1` (шаг 2) раньше, чем web перестанет слушать
  все адреса (шаг 3).

### 1. `.env` в чекауте

```
ALLOWED_HOSTS=pm.example.kz,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://pm.example.kz
```

`localhost,127.0.0.1` пока оставить: на них держится откат nginx в шаге 4.

### 2. nginx: `proxy_pass` на `127.0.0.1`

После шага 3 web слушает только IPv4-loopback, а `localhost` может сначала
разрешиться в `::1` (`getent ahosts localhost`). Если в `proxy_pass` стоит
`localhost`, заменить его на `127.0.0.1`. Остальное в конфиге пока не трогать.
Сейчас это безопасно: web пока слушает все адреса.

```bash
sudo grep -nE 'proxy_pass|proxy_set_header' /etc/nginx/sites-enabled/*
sudo nginx -t && sudo systemctl reload nginx
```

### 3. Первый деплой этой версии — вручную, в нерабочее время

Автодеплой его не применит: у старых контейнеров нет `exec` и 10 с на остановку,
а смена портов пересоздаёт `db` и `redis` (перезапуск Postgres).

```bash
sudo -u "$OWNER" -H git status --short  # должно быть пусто
docker compose exec -T celery_worker celery -A price_manager inspect active   # задач нет
# свежий дамп — той же командой, что в cron-задаче бэкапа
sudo -u "$OWNER" -H git fetch && sudo -u "$OWNER" -H git merge --ff-only origin/main
docker compose build && docker compose up -d
```

Засечь, через сколько секунд после `up -d` страница входа отвечает 200. После
пересборки автодеплой ждёт 45 с, затем ещё до минуты. Если web поднимается
дольше, увеличьте `smoke 45` в скрипте, иначе каждое обновление зависимостей
будет откатываться.

Проверка:

```bash
docker compose exec web cat /proc/1/cmdline | tr '\0' ' '   # gunicorn …, не sh
docker compose kill -s HUP web && docker compose logs --since 1m web   # Handling signal: hup, Booting worker
sudo ss -ltnp | grep docker-proxy        # все порты только на 127.0.0.1
```

Сайт по домену должен работать как раньше. Откат:
`sudo -u "$OWNER" -H git reset --hard <прежний SHA>` и `docker compose up -d`.

### 4. nginx: заголовки

Добавить заголовки из [nginx.conf.example](nginx.conf.example) в `location` сайта,
остальное оставить как есть.

```bash
sudo cp /etc/nginx/sites-enabled/<сайт> ~/nginx-site.bak
sudo nginx -t && sudo systemctl reload nginx      # reload — без простоя
```

Проверка: `curl -sI https://pm.example.kz/accounts/login/` → `200`; в
`/var/log/nginx/access.log` нет новых 400 (неизвестный Host) и 403 (CSRF); вход по
паролю и через Bitrix24, корзина, ссылка из формы «Разработчикам» работают.
Откат: вернуть копию, `nginx -t`, `reload`.

### 5. Таймер

Нужны `jq` и `curl`. Пользователь сервиса — владелец чекаута, в группе `docker`.
Проверка: должна вывестись таблица контейнеров, а не `permission denied … docker.sock`.

```bash
sudo -u "$OWNER" -H docker compose ps
```

```bash
sudo install -m 755 deploy/pm-deploy.sh /usr/local/bin/pm-deploy
sudo install -m 755 deploy/pm-notify.sh /usr/local/bin/pm-notify
sudo install -m 644 deploy/systemd/* /etc/systemd/system/
sudo install -m 640 deploy/pm-deploy.env.example /etc/pm-deploy.env
```

Затем: в `/etc/pm-deploy.env` вписать `APP_DIR`, `DOMAIN`, `WEB_PORT` и канал
уведомлений (ниже); в `/etc/systemd/system/pm-deploy.service` заменить
`User=CHANGE_ME`; `sudo chgrp <группа пользователя> /etc/pm-deploy.env`.

**Уведомления** уходят во все заполненные каналы:
- **Bitrix24** — нужен только доступ с сервера к своему порталу
  (`curl -sS -o /dev/null -w '%{http_code}\n' https://<портал>/rest/` отвечает
  кодом, а не `000`). В Bitrix24:
  «Приложения → Разработчикам → Другое → Входящий вебхук», права «Мессенджер
  (im)». Адрес вебхука (`https://<портал>/rest/<id>/<код>/`) — в `B24_WEBHOOK`,
  свой ID пользователя Bitrix24 (виден в адресе профиля) — в `B24_USER_ID`.
  Сообщения приходят системными уведомлениями.
- **Telegram** — `TG_TOKEN` и `TG_CHAT_ID` личного бота. Если `api.telegram.org`
  с сервера не открывается (`curl -sS https://api.telegram.org` висит), нужен
  `TG_PROXY` или другой канал.

Адрес вебхука и токен — секреты: они живут только в `/etc/pm-deploy.env`.

```bash
sudo systemctl daemon-reload
sudo -u "$OWNER" pm-notify "PM: проверка уведомлений"   # должно прийти; иначе в выводе — какой канал не принял
sudo systemctl start pm-deploy.service && journalctl -u pm-deploy -n 20   # нового нет — ничего не делает
sudo systemctl enable --now pm-deploy.timer
```

Первые реальные проверки: PR только с `.md` (в журнале «перезапуск не нужен»),
затем правка шаблона (в `docker compose logs web` виден HUP, сайт не моргнул).

## Деплой с миграциями

Пока миграция не выкачена руками, автодеплой не выкатит и ничего, что слито после
неё, срочные исправления тоже: скрипт сравнивает `main` с тем, что стоит на проде.
Поэтому PR с миграцией сливают, только когда готовы сразу задеплоить его вручную.

Автодеплой встал и прислал сообщение. Вручную, в нерабочее время:

1. Прочитать миграции и описание PR: бывают обязательные шаги после
   (например, `manage.py run_task reindex_pim_ids`).
2. `docker compose exec -T celery_worker celery -A price_manager inspect active` — задач нет.
3. Свежий дамп.
4. ```bash
   sudo -u "$OWNER" -H git fetch && sudo -u "$OWNER" -H git merge --ff-only origin/main
   docker compose stop celery_beat celery_worker celery_worker_pim
   docker compose run --rm --no-deps -T web python manage.py migrate --noinput
   docker compose exec -T web python manage.py collectstatic --noinput
   docker compose kill -s HUP web       # или build + up -d, если менялись зависимости
   docker compose start celery_beat celery_worker celery_worker_pim
   ```
5. Шаги после миграции, затем `sudo rm /var/lib/pm-deploy/skipped`.

Пока идёт миграция, сайт работает на старом коде с новой схемой. Без простоя это
только для обратно совместимых миграций: колонку добавить в одном PR, удалить в
следующем.

## Откат, пауза, журнал

- **Плохой коммит прошёл все проверки:** revert в GitHub — автодеплой выкатит его
  как обычный коммит. Срочно: `sudo systemctl stop pm-deploy.timer`,
  `sudo -u "$OWNER" -H git reset --hard <SHA>`, `docker compose kill -s HUP web`.
- **Пауза:** `sudo systemctl stop pm-deploy.timer`; вернуть — `start`.
- **Журнал:** `journalctl -u pm-deploy -f`.
- **Снова попробовать пропущенный SHA:** `sudo rm /var/lib/pm-deploy/skipped`.

## Правка скрипта

Каждую ветку `pm-deploy.sh` и каналы `pm-notify.sh` проверяет
`bash deploy/tests/test_pm_deploy.sh` на временных git-репозиториях с заглушками
вместо docker и curl. Этот тест — шаг CI. Меняете поведение скрипта — добавьте
сценарий. После слияния установите скрипт на сервере заново (шаг 5): автодеплой
напомнит об этом сам, но сообщение придёт по старой версии `pm-notify`.
