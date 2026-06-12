# syntax=docker/dockerfile:1.6

# ---------- 1) build ----------
FROM node:20-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# Vite запекает VITE_*-переменные в бандл во время билда. В нашей
# Railway-схеме Caddy проксирует /api/* → Django, поэтому axios должен
# обращаться по абсолютному пути /api/...; без этого запросы вида
# POST /auth/login/ улетают мимо @backend-матчера в file_server и
# возвращают 405 Allow: GET, HEAD.
ENV VITE_API_BASE_URL=/api
RUN pnpm build

# ---------- 2) serve ----------
FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
# Railway инжектит $PORT в рантайме; Caddyfile его подхватит.
