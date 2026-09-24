---
title: execute_locked_task and Celery dispatch
summary: The Redis lock, the transaction, TaskRunHistory, atomic=False and dispatch_after_commit.
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
   lock-skipped — with `duration_ms` and `updated_count`.
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
  `dispatch_after_commit()` (`task_runner.py:24`) instead — CLAUDE.md's
  "Dispatching a subtask" paragraph has the why. The `reindex_pim_ids_task`
  fan-out in `main_product_manager/tasks.py:145-150` is the worked example.
