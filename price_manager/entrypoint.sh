#!/bin/sh

# echo "Applying migrations ..."
# python manage.py migrate

# docker compose down -v
# docker cp ".\backup.backup" postgres_db:/
# docker exec -it postgres_db /bin/bash
# pg_restore --clean --verbose -U priceuser -d pricemanager ./backup.backup
# docker compose up --build

echo "Starting server..."
python manage.py runserver 0.0.0.0:8000