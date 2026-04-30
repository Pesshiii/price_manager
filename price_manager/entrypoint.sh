#!/bin/sh

echo "Applying migrations ..."
python manage.py migrate

# docker compose down -v
# docker cp ".\backup.backup" postgres_db:/
# docker exec -it postgres_db /bin/bash
# pg_restore --clean --verbose -U priceuser -d price_manager ./backup.backup
# docker exec price_manager_db pg_restore -U priceuser -h localhost -p 5432 -d price_manager --clean -v backup.dump
# docker exec pricemanager python manage.py migrate
# docker compose up --build

echo "Starting server..."
gunicorn --bind 0.0.0.0:$PORT price_manager.wsgi:application