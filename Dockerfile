# Импортирует сборку питона на машине linux
FROM python:3.13.3-slim-bookworm

# предотварщает создание c файлов и сдандарныей cout cin
ENV PYTHONDONTWRITEBYTECODE=1 \
PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y curl

# Установка uv болле быстрый менеджер чем pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Установка звисимостей(отдельно от импорта проекта для избежания повторной установки после любых изменений в проекте)
# Перестраивается только если есть изменения зависимостей
COPY price_manager/requirements.txt .

RUN uv pip install -r requirements.txt --system

# Импорт и запуск проекта
COPY price_manager/ .

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "price_manager.wsgi:application"]