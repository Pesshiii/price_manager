# Мутации страницы категории монтируются вложенно под /categories/<id>/

Страница категории выполняет две группы мутаций: управление M2M `CharacteristicType.categories` и bulk-назначение товаров. Оба действия инициируются в контексте конкретной категории. Эндпоинты монтируются как actions на `CategoryViewSet`:

- `POST /api/products/categories/<id>/characteristics/` — добавить CharacteristicType в M2M (или создать новый и добавить)
- `DELETE /api/products/categories/<id>/characteristics/<char_id>/` — убрать из M2M (JSONB товаров не затрагивается)
- `GET /api/products/categories/<id>/characteristics/<char_id>/usage/` — COUNT товаров с ненулевым значением этой характеристики (вызывается лениво, только при клике "Убрать")
- `POST /api/products/categories/<id>/assign-products/` — bulk-установить `Product.category` для списка `product_ids`

**Рассмотренные альтернативы:** распределить по существующим ресурсам — `POST /characteristic-types/<id>/categories/` и `PATCH /products/bulk/`. Отклонена: размазывает логику одной страницы по разным ресурсам, сложнее авторизовывать и документировать как единый workflow.
