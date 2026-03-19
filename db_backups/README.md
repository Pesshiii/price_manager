# Database backups for Docker initialization

Положите сюда файл бэкапа PostgreSQL перед первым запуском `docker compose up`.

Поддерживаемые форматы:
- `.sql`
- `.sql.gz`
- `.dump`
- `.backup`
- `.tar`

Если в папке лежит один файл, он будет восстановлен автоматически.
Если файлов несколько, укажите нужный через переменную окружения `POSTGRES_BACKUP_FILE`.

Важно: скрипт восстановления выполняется только при первой инициализации контейнера PostgreSQL,
когда volume `postgres_db` ещё пустой. Если база уже была создана, удалите volume перед повторным
восстановлением:

```bash
docker compose down -v
docker compose up --build
```
