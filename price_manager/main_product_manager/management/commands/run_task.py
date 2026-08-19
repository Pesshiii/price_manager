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

    def handle(self, *args, **options):
        task_name = options['task']
        async_mode = options['async_mode']

        to_run = {task_name: TASKS[task_name]} if task_name else TASKS

        for name, task in to_run.items():
            self.stdout.write(f'Запуск: {name} ...')
            if async_mode:
                task.delay()
                self.stdout.write(self.style.SUCCESS(f'  → Отправлено в Celery'))
            else:
                result = task()
                self.stdout.write(self.style.SUCCESS(f'  → Готово: {result}'))
