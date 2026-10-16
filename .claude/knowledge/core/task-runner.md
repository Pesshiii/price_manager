---
title: execute_locked_task and Celery dispatch
summary: The Redis lock, the transaction, TaskRunHistory, atomic=False, dispatch_after_commit and task time limits.
code: price_manager/core/task_runner.py
---
# execute_locked_task and Celery dispatch

## `execute_locked_task` — every Celery task should route through it

`core/task_runner.py`. Keyword-only signature:

```python
execute_locked_task(task_name=..., lock_ttl=..., runner=..., atomic=True)  # -> dict
```

What it gives you, in order:
1. Redis lock via `cache.add(f"task-lock:{task_name}", ..., timeout=lock_ttl)`
   — atomic; a second runner gets `status="skipped"`, `reason="lock_exists"`.
2. `runner()` inside `transaction.atomic()` — **unless `atomic=False`**, which
   runs it in autocommit. Only the transaction is dropped; steps 1, 3 and 4
   are unaffected, so the Redis lock still guarantees a single runner.
3. A `TaskRunHistory` row for **every** outcome — success, error, *and*
   lock-skipped — with `duration_ms` and `updated_count`. Except a hard
   time-limit kill: see *Time limits* below.
4. `cache.delete(lock_key)` in `finally`.

The skipped path `return`s at `:84`, **before** the `try` — so the `finally` at
`:133` never runs for it and a lock-loser cannot delete the winner's lock.

Errors are logged **and re-raised** (`:131`-`:132`) — it is not a swallow-all
wrapper. A task that wants to notify on failure must wrap the call itself;
see `core/tasks.py:51`–`59` (`update_cart_items_task`'s `try`/`except` around
the `execute_locked_task()` call).

`_normalize_updated_count` (`task_runner.py:14`) decides what `updated_count`
becomes: an int/float is cast, a tuple is **summed over its numeric members**,
anything else (including a dict or a model instance) becomes **0**.

The trap this sets: a runner returning a summary like
`{"updated": 42, "skipped": 3}` records **0**, and the obvious fix —
`return (42, 3)` — records **45**, a silently wrong metric that is worse. The
tuple branch is only correct when every member counts the same unit, as
`update_prices` (`product_price_manager/models.py:455`, passed straight as
`runner=` by both apps' `update_prices_task`) does: both members of its
`(count, dcount)` are counts of `MainProduct` rows written, so summing them
is correct. [[main_product_manager]]'s `reindex_pim_ids_task` shows the trap
from the other side: it used to return `(numbered, linked)` — Products
numbered and MainProducts linked, not the same unit — and was changed to a
bare `linked`, with a comment at the call site naming this exact trap
(`main_product_manager/tasks.py:155-157`); the function its batch task runs,
`push_pim_links` (`main_product_manager/utils.py:755`), returns a plain int
and raises `PimScanError` on failure rather than folding a failure count into
the total. **Return the one bare int you actually want counted.**

The rest of a dict return is not lost: the success path writes
`details={"result": str(result)}` (`:108`). That is a Python **repr string**
inside a `JSONField`, not structured JSON — reading it back needs
`ast.literal_eval`, not `json.loads`. (`error` is populated only on the error
path; `details` is left `{}` there.)

Three consequences worth remembering:
- `task_name` is the lock identity, independent of the Celery
  `@shared_task(name=...)`. Tasks meant to run in parallel need uniquified
  names — see the batch fan-out in [[main_product_manager]].
- A transaction must not span an HTTP call, and moving the *write* after the
  API loop does **not** achieve that — the transaction opens here, before the
  runner is ever entered, so it is held for the whole loop no matter where the
  write sits. `atomic=False` is the only thing that actually drops it. In
  [[main_product_manager]] that's `reindex_pim_ids_batch_task`
  (`tasks.py:166-175`), the HTTP-bound batch — its parent `reindex_pim_ids_task`
  stays atomic on purpose, since its own runner does only local DB work
  (backfill numbers, link/create `product.Product` rows) before dispatching.
- A runner that `.delay()`s subtasks inside the transaction queues them on
  Redis **immediately**, while its own DB writes can still roll back. Use
  `dispatch_after_commit()` (`task_runner.py:24`, a `transaction.on_commit`
  wrapper) instead. Dispatched early, a subtask can start against state that
  never committed: a batch selecting the rows its parent just created finds
  none of them, and after a rollback the already-dispatched batches keep
  running against a parent run recorded as failed. Outside a transaction it
  dispatches at once, so it is safe from views too. The `reindex_pim_ids_task`
  fan-out in `main_product_manager/tasks.py:145-150` is the worked example.

## Time limits: `time_limit=None` is not "no limit"

`settings/celery.py` sets `CELERY_TASK_TIME_LIMIT = 30 * 60`. To Celery, a
task's `time_limit=None` means *unset*: the worker takes
`time_limit or task.time_limit` (`celery/worker/request.py`) and falls back
to the pool default, which is that global. Six PIM tasks carried
`time_limit=None, soft_time_limit=None` as if it lifted the limit, so each was
capped at 30 minutes. The full photo pass (`product.refresh_product_photos`,
about an hour) was killed every night and had not written one `ProductPhoto`
row by 2026-10-16.

A hard-limit kill is a SIGKILL of the pool process, so the `finally` never
runs and nothing reaches `TaskRunHistory`:
- the lock stays until `lock_ttl` expires, and every run until then is
  `skipped`;
- the run leaves no row at all. The only trace is
  `Hard time limit (1800s) exceeded for <task>` in the worker log.

Hence the rules, with `product/tasks.py` (`PIM_SCAN_TIME_LIMIT`,
`PIM_BATCH_TIME_LIMIT`, `PHOTOS_TIME_LIMIT`) and
`main_product_manager/tasks.py` (`REINDEX_*_TIME_LIMIT`) as the examples:
- **A long task gets an explicit integer limit.** Neither `None` nor `0`
  works: both read as unset.
- **The limit equals the task's `lock_ttl`, from one constant.** A run that
  outlives its lock lets a second copy start on top of it.
- **`soft_time_limit` is one minute earlier.** It raises
  `SoftTimeLimitExceeded` (an `Exception` subclass) into the runner, so the
  error row is written and the lock released. A runner that swallows it gets
  no benefit: the per-item `except Exception` in `sync_products` and
  `push_pim_links`, and the page retry in `stale_product_pks`, swallow it,
  and those runs still end in the hard kill.

`core.tests.PimTaskTimeLimitTests` pins the six tasks and fails on any
`time_limit=None` or `soft_time_limit=None` in an app's `tasks.py`.

To run one of these past its limit by hand, call the task object directly in
`manage.py shell` (`refresh_product_photos_task(full=True)`). That runs in
process, outside the pool, so no time limit applies, while the lock and
`TaskRunHistory` still work.
