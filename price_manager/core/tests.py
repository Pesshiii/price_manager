import ast
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from price_manager.celery import app as celery_app
from price_manager.settings import celery as celery_settings

from .models import TaskRunHistory
from .task_runner import execute_locked_task


def _make_history(task_name: str) -> TaskRunHistory:
    now = timezone.now()
    return TaskRunHistory.objects.create(
        task_name=task_name,
        status="success",
        started_at=now,
        finished_at=now,
        duration_ms=0,
    )


class ExecuteLockedTaskAtomicTests(TransactionTestCase):
    """The `atomic` flag must control the transaction and nothing else.

    Uses TransactionTestCase because django.test.TestCase wraps every test in
    its own transaction, which would make `connection.in_atomic_block` True
    inside the runner no matter what the flag does.
    """

    def setUp(self):
        cache.clear()

    def test_runner_holds_a_transaction_by_default(self):
        seen = []

        execute_locked_task(
            task_name="test.atomic_default",
            lock_ttl=60,
            runner=lambda: seen.append(connection.in_atomic_block),
        )

        self.assertEqual(seen, [True])

    def test_runner_holds_no_transaction_when_atomic_false(self):
        seen = []

        execute_locked_task(
            task_name="test.atomic_false",
            lock_ttl=60,
            runner=lambda: seen.append(connection.in_atomic_block),
            atomic=False,
        )

        self.assertEqual(seen, [False])

    def test_atomic_false_still_takes_the_lock(self):
        # Hold the lock the way a concurrent worker would, then confirm a
        # non-transactional run is still gated by it.
        lock_key = "task-lock:test.lock_kept"
        self.assertTrue(cache.add(lock_key, "held-elsewhere", 60))
        seen = []

        payload = execute_locked_task(
            task_name="test.lock_kept",
            lock_ttl=60,
            runner=lambda: seen.append(1),
            atomic=False,
        )

        self.assertEqual(seen, [])
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["reason"], "lock_exists")
        # The loser must not clear the holder's lock.
        self.assertEqual(cache.get(lock_key), "held-elsewhere")
        cache.delete(lock_key)

    def test_atomic_false_keeps_writes_made_before_an_error(self):
        def _runner():
            _make_history("test.partial")
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            execute_locked_task(
                task_name="test.rollback",
                lock_ttl=60,
                runner=_runner,
                atomic=False,
            )

        self.assertTrue(TaskRunHistory.objects.filter(task_name="test.partial").exists())
        self.assertFalse(cache.get("task-lock:test.rollback"))

    def test_default_still_rolls_back_writes_made_before_an_error(self):
        def _runner():
            _make_history("test.partial")
            raise RuntimeError("boom")

        with self.assertRaises(RuntimeError):
            execute_locked_task(
                task_name="test.rollback",
                lock_ttl=60,
                runner=_runner,
            )

        self.assertFalse(TaskRunHistory.objects.filter(task_name="test.partial").exists())
        # The error-path history row is written outside the runner's transaction,
        # so it survives the rollback.
        self.assertTrue(TaskRunHistory.objects.filter(task_name="test.rollback", status="error").exists())


class CeleryBeatScheduleTests(SimpleTestCase):
    """The two ways a CELERY_BEAT_SCHEDULE entry silently stops running.

    Neither raises anywhere: beat just schedules less than the file appears to
    say, and the only symptom is a task that quietly stops showing up in
    TaskRunHistory. Commit e0a5070 hit the first one -- it added a
    delete_outdated_logs entry under the key 'update-logs' that was already
    taken, so main_product_manager.update_logs stopped being scheduled while
    the file still listed it.
    """

    def test_no_entry_is_overwritten_by_a_duplicate_key(self):
        # Has to read the source, not settings.CELERY_BEAT_SCHEDULE. By the time
        # the module is imported the duplicate is already gone: the dict just
        # holds one fewer entry, every remaining key is distinct, and nothing
        # runtime-visible says a task went missing.
        tree = ast.parse(Path(celery_settings.__file__).read_text(encoding='utf-8'))
        literal = next(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and any(getattr(t, 'id', None) == 'CELERY_BEAT_SCHEDULE' for t in node.targets)
        )
        keys = [key.value for key in literal.keys]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        self.assertEqual(duplicates, [], f'CELERY_BEAT_SCHEDULE keys repeated: {duplicates}')
        self.assertEqual(len(keys), len(settings.CELERY_BEAT_SCHEDULE))

    def test_every_scheduled_task_is_registered(self):
        # autodiscover_tasks() is lazy; nothing has forced the app tasks modules
        # to import in a test process.
        celery_app.loader.import_default_modules()
        for key, entry in settings.CELERY_BEAT_SCHEDULE.items():
            with self.subTest(entry=key):
                self.assertIn(entry['task'], celery_app.tasks)
