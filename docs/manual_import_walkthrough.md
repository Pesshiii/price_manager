# Manual e2e: загрузка товаров через dataframe

Ручной сценарий для проверки полного pipeline импорта на запущенном сервере.
Дополняет автотесты в `price_manager/product/tests/test_import.py`.

## Предусловия

- Сервер: `python manage.py runserver` (порт 8000).
- В БД есть суперюзер (`python manage.py createsuperuser`).
- Файл `sample.csv` рядом с этой инструкцией (см. ниже).
- На Windows: `curl.exe` (поставляется с Windows 10+) — **не** PowerShell-алиас `curl`.

## Тестовые данные

`sample.csv`:

```csv
sku,name,category,brand,color,weight
S1,Дрель,Инструменты,Acme,red,1500
S2,Чехол,Аксессуары,Brandy,blue,50
```

В БД через админку или shell заранее создать `CharacteristicType`:

```bash
python manage.py shell -c "from product.models import CharacteristicType; \
  CharacteristicType.objects.get_or_create(name='color', defaults={'label':'Цвет','value_type':'string'}); \
  CharacteristicType.objects.get_or_create(name='weight', defaults={'label':'Вес','value_type':'integer'})"
```

## Шаги

### 1. CSRF-токен

```bash
curl.exe -c cookies.txt http://localhost:8000/api/auth/csrf/
```

Ожидаем `200 OK`, в `cookies.txt` появится `csrftoken=<TOKEN>`.

### 2. Логин

```bash
curl.exe -b cookies.txt -c cookies.txt ^
  -X POST ^
  -H "X-CSRFToken: <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"admin\",\"password\":\"admin\"}" ^
  http://localhost:8000/api/auth/login/
```

Ожидаем `200 OK`, ответ `{"username":"admin", ...}`. Cookie `sessionid` сохранится.

### 3. Загрузить файл → session_id

```bash
curl.exe -b cookies.txt ^
  -X POST ^
  -H "X-CSRFToken: <TOKEN>" ^
  -F "file=@sample.csv" ^
  http://localhost:8000/api/dataframe/sessions/
```

Ожидаем `201 Created`, ответ `{"session_id":"<UUID>","filename":"sample.csv","size":...}`.

### 4. Превью DataFrame

`preview.json`:

```json
{
  "session_id": "<SID>",
  "instructions": {"reader": {"func": "read_csv", "args": {}}, "transforms": []},
  "row_limit": 50
}
```

```bash
curl.exe -b cookies.txt ^
  -X POST ^
  -H "X-CSRFToken: <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d @preview.json ^
  http://localhost:8000/api/dataframe/preview/
```

Ожидаем `200 OK`, `columns: ["sku","name","category","brand","color","weight"]`, `total_rows: 2`.

### 5. Превью импорта (mapping → payloads без записи)

`import_preview.json`:

```json
{
  "session_id": "<SID>",
  "instructions": {"reader": {"func": "read_csv", "args": {}}, "transforms": []},
  "mapping": {
    "sku":  {"column": "sku"},
    "name": {"column": "name"},
    "category": {"column": "category"},
    "brand":    {"column": "brand"},
    "status":   {"const": "active"},
    "characteristics": {
      "color":  {"column": "color"},
      "weight": {"column": "weight"}
    }
  },
  "row_limit": 200
}
```

```bash
curl.exe -b cookies.txt ^
  -X POST ^
  -H "X-CSRFToken: <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d @import_preview.json ^
  http://localhost:8000/api/products/import/preview/
```

Ожидаем `200 OK`, `total: 2`, `valid: 2`, `invalid: 0`.
Каждый `rows[*].payload` содержит `characteristics`, `category`, `brand`.

### 6. Commit

Те же данные на `/api/products/import/commit/`:

```bash
curl.exe -b cookies.txt ^
  -X POST ^
  -H "X-CSRFToken: <TOKEN>" ^
  -H "Content-Type: application/json" ^
  -d @import_preview.json ^
  http://localhost:8000/api/products/import/commit/
```

Ожидаем `200 OK`, `{"created":2,"updated":0,"skipped":0,"errors":[]}`.

### 7. Верификация: товары видны через API

```bash
curl.exe -b cookies.txt "http://localhost:8000/api/products/products/?search=Дрель"
```

Ожидаем `200 OK`, в `results` товар `S1` с `characteristics.color=red`, `characteristics.weight=1500`.

## Что считается success'ом

- Все шаги вернули заявленные статусы.
- Шаг 6: `created=2, skipped=0, errors=[]`.
- Шаг 7: товары находятся в выдаче, `Category` и `Brand` созданы.

## Troubleshooting

- **403 на шаге 2** — `X-CSRFToken` не подхватился. Проверь, что заголовок реально передаётся (`curl.exe -v`) и что `cookies.txt` подключён через `-b`.
- **404 на шаге 4–6** — session протухла (TTL 24ч) или сервер был перезапущен с очисткой `MEDIA_ROOT`. Повторить шаг 3.
- **400 на шаге 6 с `errors[*].characteristics.color`** — забыли создать `CharacteristicType` (предусловия).
- **500 на шаге 6** — миграции `product` не накатаны: `python manage.py migrate product`.
