"""Зонд §5a: выдержит ли PIM широкий отбор по категории.

Живая нога фильтра (D15) спрашивает у PIM id товаров категории и подставляет их
в `Product.pim_id IN (...)`. Вопрос, на который надо ответить ДО того, как её
писать: сколько товаров в самой большой категории. Если там столько, что один
IN их не унесёт, честный вывод — живая нога годится только для узких фильтров,
и это повод вернуться к решению, а не молча обрезать набор.

Зонд ходит в PIM и ничего не пишет. Без настоящих PIM_TOKEN/PIM_HOST он
осмысленно не отработает — так и скажет.

    docker compose exec web python manage.py probe_pim_category_size --top 5
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from pim_api import EntityList, Where, fetch_list

from ... import pim_client
from ...models import Category

# Выше этого набора id подставлять в IN уже не стоит: URL запроса к PIM растёт
# линейно по числу id, и вместе с ним растёт и сам IN в SQL. Порог намеренно
# грубый — зонду нужно разделить «спокойно влезает» и «не влезает», а не найти
# точную границу.
IN_CLAUSE_COMFORT_LIMIT = 1000


class Command(BaseCommand):
    help = 'Проверяет, сколько товаров PIM отдаёт на самые крупные категории (зонд §5a).'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=5,
                            help='Сколько самых крупных категорий проверить.')
        parser.add_argument('--page-size', type=int, default=200,
                            help='Размер страницы при обходе.')
        parser.add_argument('--max-items', type=int, default=IN_CLAUSE_COMFORT_LIMIT,
                            help='Предел набора. Превышение — это и есть ответ зонда.')

    def handle(self, *args, **options):
        categories = (
            Category.objects.annotate(n=Count('products'))
            .filter(n__gt=0).order_by('-n')[:options['top']]
        )
        if not categories:
            self.stdout.write(self.style.WARNING(
                'Локальных категорий с товарами нет — сначала нужен бэкфилл '
                '(product.backfill_products_from_pim).'
            ))
            return

        verdicts = []
        for category in categories:
            # Тот же разворот по дереву, что делает фильтр: PIM сопоставляет
            # ровно те id, которые мы прислали, поэтому родителя недостаточно.
            descendant_ids = list(
                category.get_descendants(include_self=True)
                .exclude(pim_id__isnull=True).exclude(pim_id='')
                .values_list('pim_id', flat=True)
            )
            if not descendant_ids:
                self.stdout.write(f'{category}: нет ни одного pim_id в ветке — пропуск.')
                continue

            try:
                result = fetch_list(
                    pim_client.site,
                    EntityList(
                        name='Product',
                        select=['id'],
                        where=[Where(attribute='categories', type='linkedWith',
                                     value=descendant_ids)],
                    ),
                    page_size=options['page_size'],
                    max_items=options['max_items'],
                )
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f'{category}: PIM не ответил — {exc!r}. '
                    'Проверьте PIM_TOKEN/PIM_HOST: с заглушками зонд не работает.'
                ))
                return

            verdicts.append((str(category), result.total, result.truncated))
            marker = self.style.ERROR('ВЫШЕ ПРЕДЕЛА') if result.truncated else self.style.SUCCESS('ок')
            self.stdout.write(
                f'{category}: узлов в ветке {len(descendant_ids)}, '
                f'товаров в PIM {result.total}, получено {len(result.items)} — {marker}'
            )

        if not verdicts:
            return

        worst = max(v[1] for v in verdicts)
        self.stdout.write('')
        if worst > options['max_items']:
            self.stdout.write(self.style.ERROR(
                f'ВЫХОД §5a: худший случай {worst} товаров при пределе {options["max_items"]}. '
                'Живая нога фильтра в таком виде обслуживает только узкие отборы. '
                'Это надо вернуть на решение, а не обрезать набор молча.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Худший случай {worst} товаров — влезает в предел {options["max_items"]}. '
                'Живую ногу можно писать; требования §5c остаются в силе.'
            ))
