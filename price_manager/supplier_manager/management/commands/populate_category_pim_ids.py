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
        parser.add_argument(
            '--from-pim',
            action='store_true',
            dest='from_pim',
            help='Удалить все категории и пересоздать их из PIM',
        )

    def handle(self, *args, **options):
        entity = options['entity']

        if options['from_pim']:
            self._sync_from_pim(entity)
        else:
            self._populate_pim_ids(entity, overwrite=options['overwrite'])

    # ------------------------------------------------------------------
    # --from-pim: wipe and recreate from PIM
    # ------------------------------------------------------------------

    def _sync_from_pim(self, entity):
        self.stdout.write('Удаление всех категорий...')
        Category.objects.all().delete()

        created = 0
        errors = 0

        def fetch_and_create(parent_db, parent_pim_id):
            nonlocal created, errors
            if parent_pim_id is None:
                where = [Where(attribute='isRoot', type='isTrue')]
            else:
                where = [Where(attribute='parentId', type='equals', value=parent_pim_id)]

            try:
                result = site.get(EntityList(name=entity, select=['id', 'name'], where=where))
            except Exception as exc:
                errors += 1
                self.stdout.write(self.style.ERROR(f'  Ошибка запроса: {exc}'))
                return

            for item in result.get('list', []):
                try:
                    cat = Category.objects.create(
                        parent=parent_db,
                        name=item['name'],
                        pim_id=item['id'],
                    )
                    created += 1
                    self.stdout.write(f'  {cat}  ←  {cat.pim_id}')
                    fetch_and_create(cat, item['id'])
                except Exception as exc:
                    errors += 1
                    self.stdout.write(self.style.ERROR(
                        f'  {item.get("name")}  →  ошибка создания: {exc}'
                    ))

        fetch_and_create(parent_db=None, parent_pim_id=None)
        Category.objects.rebuild()
        self.stdout.write(self.style.SUCCESS(
            f'\nГотово: создано={created}, ошибок={errors}'
        ))

    # ------------------------------------------------------------------
    # default: populate pim_id on existing categories
    # ------------------------------------------------------------------

    def _populate_pim_ids(self, entity, overwrite):
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
