from django.core.management.base import BaseCommand

from main_product_manager.pim_api import EntityList, Where, site
from supplier_manager.models import Category


class Command(BaseCommand):
    help = "Заполняет pim_id для категорий, находя их в PIM по имени"

    def add_arguments(self, parser):
        parser.add_argument(
            '--entity',
            default='Category',
            help='Имя сущности в PIM (по умолчанию: Category)',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Перезаписать уже заполненные pim_id',
        )

    def handle(self, *args, **options):
        entity = options['entity']
        overwrite = options['overwrite']

        # Process level by level so parents always have pim_id before children
        max_level = Category.objects.order_by('-level').values_list('level', flat=True).first()
        if max_level is None:
            self.stdout.write('Нет категорий для обработки.')
            return

        updated = 0
        not_found = 0
        skipped = 0
        errors = 0

        for level in range(max_level + 1):
            qs = Category.objects.filter(level=level).select_related('parent')
            if not overwrite:
                qs = qs.filter(pim_id__isnull=True)

            for cat in qs:
                # Children whose parent has no pim_id cannot be narrowed down
                if cat.parent is not None and not cat.parent.pim_id:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(
                        f'  {cat}  →  пропущено (нет pim_id у родителя)'
                    ))
                    continue

                where = [Where(attribute='name', type='equals', value=cat.name)]
                if cat.parent is not None:
                    where.append(Where(attribute='parentId', type='equals', value=cat.parent.pim_id))

                try:
                    result = site.get(EntityList(name=entity, select=['id'], where=where))
                    items = result.get('list', [])
                    if items:
                        cat.pim_id = items[0]['id']
                        cat.save(update_fields=['pim_id'])
                        updated += 1
                        self.stdout.write(f'  {cat}  →  {cat.pim_id}')
                    else:
                        not_found += 1
                        self.stdout.write(self.style.WARNING(f'  {cat}  →  не найдено'))
                except Exception as exc:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f'  {cat}  →  ошибка: {exc}'))

        self.stdout.write(self.style.SUCCESS(
            f'\nГотово: обновлено={updated}, не найдено={not_found}, пропущено={skipped}, ошибок={errors}'
        ))
