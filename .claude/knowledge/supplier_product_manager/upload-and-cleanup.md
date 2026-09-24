---
title: Upload and cleanup
summary: The file a setting depends on, and what the cleanup keeps.
code: price_manager/supplier_product_manager/tasks.py
---
# Upload and cleanup

## Upload and cleanup — the file a setting depends on

- **`UploadSupplierFile.form_valid`** (`views.py:145`) reads the workbook's
  sheet names **before** creating anything. It used to create the `Setting`
  first and read the file inside a `while not created` loop with `except
  BaseException`, so a corrupt or password-protected file was taken for a name
  clash and the loop kept creating `name(1)`, `name(2)`, … until gunicorn killed
  the worker. Name suffixing is now bounded by `MAX_SETTING_NAME_ATTEMPTS`
  (`views.py:51`) and catches only `IntegrityError` inside a savepoint. Empty
  `Setting`s with a `(N)` suffix, no file and no links are likely leftovers of
  the old loop.
- **`cleanup_supplier_files_task`** (`tasks.py:131`) never deletes a setting's
  newest file: `keep_last` is clamped to at least 1 and
  `SUPPLIER_FILES_KEEP_LAST` defaults to 1 (`settings/celery.py`). It used to
  default to 0, which on a 30-minute beat deleted every file — including the
  one being mapped or waiting in the import queue. Files in
  `STATUS_QUEUED`/`STATUS_RUNNING` are skipped too.
- **The upload view does not delete older files.** It used to, immediately —
  including the file an import was reading at that moment. The run's in-memory
  `supplier_file` FK then pointed at a deleted row, the full `run.save()` in
  `_finish_run` failed after the data was committed, and the run stayed
  «Выполняется» with no notification. Now the import always takes the newest
  file, the upload only marks older `QUEUED`/`NEEDS_CONFIRMATION` files
  `ERROR` (they will never be imported), and the cleanup deletes them. As a
  second line, `_finish_run` and the file log/status helpers write with
  queryset `update()`s, so a row deleted mid-import no longer fails the task.
