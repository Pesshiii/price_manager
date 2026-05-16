#!/bin/sh

echo "Applying migrations ..."
python manage.py migrate

# docker compose down -v
# docker cp ".\backup.backup" postgres_db:/
# docker exec -it postgres_db /bin/bash
# pg_restore --clean --verbose -U priceuser -d price_manager ./backup.dump
# docker exec pricemanager python manage.py migrate
# docker compose up --build

echo "Starting server..."
gunicorn --bind 0.0.0.0:$PORT price_manager.wsgi:application