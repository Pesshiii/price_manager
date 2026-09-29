"""Контент товара из PIM для карточки: описания, характеристики, прочие поля.

Описания лежат в зеркале (raw_data) — их приносит ночная синхронизация, в PIM
за ними не ходим. Характеристик в зеркале нет: синхронизация их не запрашивает.
Их берём одним запросом Product/{id} с Flatten-Attributes, когда карточка
открыта, и держим в кэше.

Только показ. Фильтровать по характеристикам этим нельзя — для этого их
придётся зеркалить. Списком PIM их отдаёт (Flatten-Attributes +
allAttributes=true, ~2,7 с на страницу в 200 товаров), но без подписей и
групп — названия тогда брать из справочника Attribute.
"""

from __future__ import annotations

import logging
import re

import httpx
import nh3
from django.conf import settings
from django.core.cache import cache
from django.utils.html import escape, linebreaks, strip_tags
from django.utils.safestring import mark_safe

from pim_api import FlatEntity
from releases.rendering import ALLOWED_ATTRIBUTES, ALLOWED_TAGS

from . import pim_client

logger = logging.getLogger(__name__)

# Час, а не сутки, как у фото: характеристики правят в PIM и хотят увидеть
# здесь. Сразу — кнопкой «Обновить», она идёт мимо кэша.
CACHE_TTL = 60 * 60

# Карточка ждёт ответа PIM только в ленивой панели, но и там 5 секунд
# по умолчанию — долго, а медленный PIM — не повод показывать ошибку.
FETCH_TIMEOUT = 10

# <img> — нет: картинки PIM без токена отвечают 401, в описании был бы битый значок.
DESCRIPTION_TAGS = ALLOWED_TAGS - {'img'}
DESCRIPTION_ATTRIBUTES = {tag: attrs for tag, attrs in ALLOWED_ATTRIBUTES.items() if tag != 'img'}

# Похоже на HTML: есть открывающий или закрывающий тег. «a < b» — ещё текст.
_TAG = re.compile(r'</?[a-zA-Z][^>]*>')

# Пустые обёртки, которые оставляют шаблоны описаний: «<h4>Преимущества</h4><ul></ul>».
_EMPTY_ELEMENT = re.compile(r'<(p|ul|ol|li|div|span|h[1-6])>\s*</\1>')
# ...и заголовок, под которым после этого ничего не осталось: за ним сразу
# следующий заголовок или конец текста.
_ORPHAN_HEADING = re.compile(r'<(h[1-6])>[^<]*</\1>\s*(?=<h[1-6]>|$)')

# Как показывать атрибут каждого типа. Прочие типы (setProducts — linkMultiple,
# связи) характеристиками не являются: состав набора карточка выводит сама.
_KINDS = {
    'varchar': 'text', 'text': 'multiline', 'int': 'number', 'float': 'number',
    'bool': 'bool', 'url': 'url',
}

# Поля товара PIM, которые не попали ни в описание, ни в характеристики.
# price/rrp из PIM сюда не входят нарочно: рядом с ценами ГП они путали бы.
OTHER_FIELDS = [
    ('ean', 'EAN'),
    ('mpn', 'MPN'),
    ('customsNumber', 'Код ТН ВЭД'),
    ('countryOfOriginName', 'Страна происхождения'),
    ('productGroupName', 'Группа товаров'),
    ('tag', 'Теги'),
    ('note', 'Заметка'),
]


class PimUnavailable(Exception):
    """PIM не ответил, а в кэше ничего нет."""


def clean_description(value) -> str:
    """Описание из PIM, безопасное для вывода как HTML.

    В PIM HTML встречается в обоих полях — и в wysiwyg longDescription, и в
    текстовом description. Текст без тегов переводы строк бы потерял, поэтому
    его переносы превращаются в <p>/<br>.
    """
    if not isinstance(value, str) or not value.strip():
        return ''
    if not _TAG.search(value):
        return mark_safe(linebreaks(escape(value.strip())))
    html = nh3.clean(
        value,
        tags=DESCRIPTION_TAGS,
        attributes=DESCRIPTION_ATTRIBUTES,
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
    )
    previous = None
    while previous != html:
        previous, html = html, _EMPTY_ELEMENT.sub('', html)
    html = _ORPHAN_HEADING.sub('', html.strip()).strip()
    return mark_safe(html) if strip_tags(html).strip() else ''


def description_html(raw_data: dict, name: str | None) -> str:
    """description — если он не повторяет название товара."""
    html = clean_description(raw_data.get('description'))
    if html and name and strip_tags(html).strip() == name.strip():
        return ''
    return html


def pim_product_url(pim_product_id: str | None) -> str | None:
    """Ссылка на товар в интерфейсе PIM."""
    host = (settings.PIM_HOST or '').split('://')[-1].strip('/')
    if not pim_product_id or not host:
        return None
    return f'https://{host}/#Product/view/{pim_product_id}'


def _cache_key(pim_product_id: str) -> str:
    # Не pim_product:{id}: под тем ключом main_product_manager.utils держит
    # тот же товар без атрибутов, и формы ответа смешались бы.
    return f'pim_product_flat:{pim_product_id}'


def fetch_flat_product(pim_product_id: str, refresh: bool = False) -> dict | None:
    """Товар PIM с характеристиками. None — в PIM такого товара нет.

    `pim_product_id` — id записи Product в PIM (raw_data['id']), не
    Product.pim_id: тот — PriceManagerProduct, и его нет у наборов.

    Сбой PIM отдаёт прошлый ответ из кэша, если он есть, — даже при refresh;
    без него поднимает PimUnavailable.
    """
    key = _cache_key(pim_product_id)
    if not refresh:
        cached = cache.get(key)
        if cached is not None:
            return cached
    try:
        data = pim_client.site.get(FlatEntity(name='Product', id=pim_product_id), timeout=FETCH_TIMEOUT)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            cache.delete(key)
            return None
        logger.warning('pim_content: PIM ответил %s на товар %s', exc.response.status_code, pim_product_id)
    except Exception:
        logger.warning('pim_content: не удалось получить товар %s из PIM', pim_product_id, exc_info=True)
    else:
        cache.set(key, data, CACHE_TTL)
        return data
    stale = cache.get(key)
    if stale is None:
        raise PimUnavailable(pim_product_id)
    return stale


def _format_number(value) -> str:
    if isinstance(value, float):
        text = f'{value:.4f}'.rstrip('0').rstrip('.')
        return text.replace('.', ',')
    return str(value)


def _label(code: str, definition: dict, definitions: dict) -> str:
    label = definition.get('label') or code
    # У атрибута с единицей PIM дописывает к подписи тип значения:
    # «Длина (Float)» рядом с «Длина (Unit)». Название атрибута — без него.
    if f'{code}Unit' in definitions:
        label = re.sub(r'\s*\([A-Za-z ]+\)$', '', label)
    if definition.get('channelName'):
        label = f'{label} / {definition["channelName"]}'
    return label


def characteristics(data: dict) -> list[dict]:
    """Характеристики, сгруппированные как в PIM.

    [{'name': 'Упаковка', 'items': [{'label', 'value', 'unit', 'kind'}, ...]}, ...]
    Группы и строки в порядке сортировки PIM, пустые значения пропущены.
    """
    definitions = data.get('attributesDefs') or {}
    groups: dict = {}
    for code, definition in definitions.items():
        kind = _KINDS.get(definition.get('type'))
        if kind is None or definition.get('unitIdField'):
            continue
        value = data.get(code)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if kind == 'url' and not str(value).strip().lower().startswith(('http://', 'https://')):
            # В href попадает только http(s): javascript: автоэкранирование не остановит.
            kind = 'text'
        if kind == 'bool':
            value = 'да' if value else 'нет'
        elif kind == 'number':
            value = _format_number(value)
        unit = (data.get(f'{code}UnitData') or {}).get('symbol') if kind == 'number' else None
        group = definition.get('attributeGroup') or {}
        group_key = group.get('id') or ''
        if group_key not in groups:
            groups[group_key] = {
                'name': group.get('name') or 'Без группы',
                # Без группы — в конце.
                'sort': (0, group.get('sortOrder') or 0) if group_key else (1, 0),
                'items': [],
            }
        groups[group_key]['items'].append({
            'label': _label(code, definition, definitions),
            'value': value,
            'unit': unit,
            'kind': kind,
            'sort': (definition.get('sortOrderInAttributeGroup') or 0, definition.get('sortOrder') or 0),
        })
    result = sorted(groups.values(), key=lambda g: (g['sort'], g['name']))
    for group in result:
        group['items'].sort(key=lambda item: (item['sort'], item['label']))
    return result


def other_fields(data: dict) -> list[tuple[str, str]]:
    """Заполненные поля из OTHER_FIELDS: [(подпись, значение), ...]."""
    result = []
    for field, label in OTHER_FIELDS:
        value = data.get(field)
        if isinstance(value, list):
            value = ', '.join(str(v) for v in value if v)
        if value not in (None, '') and str(value).strip():
            result.append((label, str(value).strip()))
    return result
