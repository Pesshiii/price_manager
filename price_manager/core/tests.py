from django.core.cache import cache
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

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
