"""Зонд §5a: выдержит ли PIM широкий отбор по категории.

Живая нога фильтра (D15) должна была спросить у PIM id товаров категории и
подставить их в `Product.pim_id IN (...)`. Зонд отвечает на вопрос, который
надо было задать ДО того, как её писать.

Дерево берётся из САМОГО PIM, а не из локальных категорий: локальные появляются
только после бэкфилла, а вопрос к PIM не зависит от того, дошёл бэкфилл или нет.
Первая версия зонда ходила по локальным Category и на пустой базе отвечала «нет
категорий» вместо ответа по существу.

Только чтение. Без настоящих PIM_TOKEN/PIM_HOST осмысленно не отработает — так
и скажет.

    docker compose --env-file ../../../.env run --rm --no-deps -T web \\
        python manage.py probe_pim_category_size

Результат прогона 2026-09-16 записан в .claude/shift-to-product-brief.md §5a.
"""

import collections
import time

import httpx
from django.core.management.base import BaseCommand

from pim_api import EntityList, Where, fetch_list

from ... import pim_client

# Замерено на живом PIM: 100 id проходит, 125 даёт 414 URI Too Long. Ниже —
# консервативный размер куска, а не найденная граница.
CHUNK_SIZE = 90

# Выше этого набора товаров отбор перестаёт быть интерактивным: id надо ещё
# выкачать страницами, а потом внести в SQL-овый IN.
INTERACTIVE_PRODUCT_LIMIT = 1000


class Command(BaseCommand):
    help = 'Проверяет, выдержит ли PIM широкий отбор по категории (зонд §5a).'

    def add_arguments(self, parser):
        parser.add_argument('--chunk-size', type=int, default=CHUNK_SIZE,
                            help='Сколько id категорий слать в одном запросе.')
        parser.add_argument('--limit', type=int, default=INTERACTIVE_PRODUCT_LIMIT,
                            help='Порог, выше которого отбор считается неинтерактивным.')

    def handle(self, *args, **options):
        site = pim_client.site
        try:
            cats = fetch_list(
                site,
                EntityList(name='Category', select=['id', 'name', 'parentId', 'isRoot']),
                page_size=200,
            )
        except Exception as exc:
            self.stderr.write(self.style.ERROR(
                f'PIM не ответил — {exc!r}. Проверьте PIM_TOKEN/PIM_HOST: с заглушками '
                'зонд не работает, а PIM_HOST должен быть голым именем хоста без схемы.'
            ))
            return

        self.stdout.write(
            f'Категорий в PIM: {cats.total} (получено {len(cats.items)}, '
            f'обрезано: {cats.truncated})'
        )

        children = collections.defaultdict(list)
        for c in cats.items:
            children[c.get('parentId')].append(c)
        roots = [c for c in cats.items if c.get('isRoot')]

        def descendants(cid):
            out, stack = [cid], [cid]
            while stack:
                for child in children.get(stack.pop(), []):
                    out.append(child['id'])
                    stack.append(child['id'])
            return out

        self.stdout.write(f'Корневых категорий: {len(roots)}')
        self.stdout.write('')

        worst_products = 0
        worst_branch = 0
        over_limit = []

        for root in sorted(roots, key=lambda r: -len(descendants(r['id']))):
            ids = descendants(root['id'])
            chunks = [ids[i:i + options['chunk_size']]
                      for i in range(0, len(ids), options['chunk_size'])]
            started = time.monotonic()
            total = 0
            try:
                for chunk in chunks:
                    total += site.get(EntityList(
                        name='Product', select=['id'], maxSize=1,
                        where=[Where(attribute='categories', type='linkedWith', value=chunk)],
                    )).get('total') or 0
            except httpx.HTTPStatusError as exc:
                self.stdout.write(self.style.ERROR(
                    f'{root.get("name")}: HTTP {exc.response.status_code} на {len(ids)} id — '
                    'кусок всё ещё слишком велик, уменьшите --chunk-size.'
                ))
                continue

            elapsed = time.monotonic() - started
            worst_products = max(worst_products, total)
            worst_branch = max(worst_branch, len(ids))
            flag = ''
            if total > options['limit']:
                over_limit.append((root.get('name'), total))
                flag = self.style.ERROR('  ВЫШЕ ПОРОГА')
            self.stdout.write(
                f'{root.get("name")}: узлов {len(ids)}, запросов {len(chunks)}, '
                f'товаров ~{total} за {elapsed:.2f}с{flag}'
            )

        self.stdout.write('')
        self.stdout.write(f'Худший случай: ветка из {worst_branch} узлов, ~{worst_products} товаров.')
        if over_limit:
            self.stdout.write(self.style.ERROR(
                f'ВЫХОД §5a: {len(over_limit)} из {len(roots)} корневых категорий дают больше '
                f'{options["limit"]} товаров. Чтобы отдать их в `pim_id IN (...)`, id надо '
                'выкачать страницами — это десятки запросов и десятки секунд на один клик по '
                'фильтру. Живая нога в таком виде обслуживает только узкие отборы. '
                'Это надо вернуть на решение, а не обрезать набор молча.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                'Все корневые категории влезают в порог — живую ногу можно писать; '
                'требования §5c остаются в силе.'
            ))
