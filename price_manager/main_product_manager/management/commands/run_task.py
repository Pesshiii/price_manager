from django.core.management.base import BaseCommand
from main_product_manager import tasks
from supplier_manager import tasks as sm_tasks

TASKS = {
    'rebuild_categories': tasks.rebuild_categories_task,
    'recalculate_vectors_missing': tasks.recalculate_vectors_missing_task,
    'update_prices': tasks.update_prices_task,
    'update_stocks': tasks.update_stocks_task,
    'update_logs': tasks.update_logs_task,
    'delete_outdated_logs': tasks.delete_outdated_logs_task,
    'create_pim_links': tasks.create_pim_links_task,
    'reindex_pim_ids': tasks.reindex_pim_ids_task,
    'sync_categories': sm_tasks.sync_categories_task,
}


class Command(BaseCommand):
    help = "Запускает задачи main_product_manager вручную"

    def add_arguments(self, parser):
        parser.add_argument(
            'task',
            nargs='?',
            choices=list(TASKS.keys()),
            help='Имя задачи. Если не указано — запускаются все задачи последовательно.',
        )
        parser.add_argument(
            '--async',
            action='store_true',
            dest='async_mode',
            help='Отправить задачу в Celery вместо синхронного выполнения.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=None,
            dest='batch_size',
            help='Размер батча upsertAsync для create_pim_links/reindex_pim_ids.',
        )
        parser.add_argument(
            '--delay',
            type=float,
            default=None,
            dest='delay',
            help='Задержка (сек) между запросами к PIM для create_pim_links/reindex_pim_ids.',
        )

    def handle(self, *args, **options):
        task_name = options['task']
        async_mode = options['async_mode']
        batch_size = options['batch_size']
        delay = options['delay']

        to_run = {task_name: TASKS[task_name]} if task_name else TASKS

        for name, task in to_run.items():
            self.stdout.write(f'Запуск: {name} ...')
            kwargs = {}
            if name in ('create_pim_links', 'reindex_pim_ids'):
                if batch_size is not None:
                    kwargs['batch_size'] = batch_size
                    self.stdout.write(self.style.SUCCESS(f'Размер батча: {batch_size}'))
                if delay is not None:
                    kwargs['delay'] = delay
                    self.stdout.write(self.style.SUCCESS(f'Delay: {delay}'))
            if async_mode:
                task.delay(**kwargs)
                self.stdout.write(self.style.SUCCESS(f'  → Отправлено в Celery'))
            else:
                result = task(**kwargs)
                self.stdout.write(self.style.SUCCESS(f'  → Готово: {result}'))
