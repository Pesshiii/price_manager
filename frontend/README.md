# Price Manager Frontend

React + Vite + TypeScript + Mantine SPA для Price Manager. Сейчас живёт в `price_manager/frontend/` — позже будет вынесено в отдельный репозиторий.

## Стек

- **Vite** + **React 18** + **TypeScript**
- **Mantine 7** (UI kit, формы, нотификации)
- **React Router v6**
- **axios** (с session + CSRF)

## Установка

Требуется Node 18+ и pnpm:

```powershell
# один раз
corepack enable
corepack prepare pnpm@latest --activate

# в папке frontend/
pnpm install
pnpm dev
```

Dev server слушает `http://localhost:5173`. Запросы на `/api/*` проксируются на Django (`http://localhost:8000`) — см. `vite.config.ts`.

## Mock-логин

Пока бэкенд DRF не подключён, в `src/api/auth.ts` стоит `USE_MOCK = true`.
Войти можно с `admin / admin`. Когда появятся эндпоинты `/api/auth/csrf/`, `/api/auth/login/`, `/api/auth/me/`, `/api/auth/logout/` — поставить `USE_MOCK = false`.

## Структура

```
src/
├── api/         # axios client, CSRF, auth endpoints
├── auth/        # AuthContext, RequireAuth
├── layout/      # AppShell layout
├── pages/       # экраны (Login, Dashboard, ...)
├── routes.tsx   # роутинг
└── main.tsx     # entry, MantineProvider
```

## Скрипты

- `pnpm dev` — dev server
- `pnpm build` — продакшен-сборка в `dist/`
- `pnpm typecheck` — проверка типов
