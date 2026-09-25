---
title: ImportRun and the import guard
summary: Import history and parse counters; confirmation instead of a silent bad import.
code: price_manager/supplier_product_manager/models.py, price_manager/supplier_product_manager/views.py, price_manager/supplier_product_manager/guard.py, price_manager/supplier_product_manager/tasks.py
---
# ImportRun and the import guard

## Import history — `ImportRun` and the parse counters

Every run of `process_supplier_file_import` leaves one `ImportRun`
(`models.py:248`) — `applied`, `refused` (a `SupplierImportError` or missing
storage file, `message` = the user-facing reason) or `failed` (anything else,
re-raised). It is the per-setting coverage history the import guard compares a
new file against, so **do not add an import path that bypasses the task**
without recording a run.

- The counters come from `get_sps_result` (`functions.py:423`), which returns
  `(payload, stats)`; `get_sps` (`functions.py:410`) is its payload-only
  wrapper. Stage counters are listed in `SPS_STAT_FIELDS` (`functions.py:41-56`).
  Two of them are warnings, not losses: `duplicates` (exact `(article, name)`
  repeats — the first row wins) and `article_conflicts` (articles appearing in
  the file with several names — loaded as separate products; counted only
  when names come from the file). `duplicate_warning(stats)` turns them into
  the «Внимание: …» sentence the import notification carries, and a
  notification with it is `warning`, not `success`. Payload and stats are
  cached **together** under schema version `1.7` (`functions.py:39`) — a
  bare-list entry from an older version would break the unpack, so changing
  the cached shape again means bumping `SPS_JSON_SCHEMA_VERSION`.
- **Price and stock coverage are separate on purpose** (`covered_price`,
  `covered_stock`, `_coverage`): a stock column can stop parsing, or lose its
  `Link`, while prices keep loading, and the total row count hides that. An
  unmapped stock yields `covered_stock = 0`, the same as a column where no
  number parsed. Production has had exactly this — suppliers with prices on
  nearly every row and stock NULL on nearly all of them.
- A refusal carries the counters gathered so far on `exc.stats`, so a refused
  run shows where the rows were lost. `created`/`updated`/`missing` exist only
  for applied runs (`load_setting` returns `ImportOutcome(sps, stats)`,
  `functions.py:1012`).
- `supplier_file` is `SET_NULL` with `file_name` copied: the cleanup task deletes
  files, the history must outlive them.

## The import guard — confirmation instead of a silent bad import

`process_supplier_file_import` (`tasks.py:138`) parses first via
`_import_setting` (`get_sps_result` + `apply_counts`), then asks
`guard.evaluate` (`guard.py:31`) whether to apply. It holds the import (status
`pending`, `SupplierFile.STATUS_NEEDS_CONFIRMATION`, a `warning` notification
whose link opens the dialog) when:

- the setting has fewer than `SUPPLIER_IMPORT_GUARD_MIN_HISTORY` (3) applied
  runs — **every** import asks until history exists; there is deliberately no
  history-free heuristic and no seeding from old notifications;
- `covered_price` or `covered_stock` is below `SUPPLIER_IMPORT_GUARD_RATIO`
  (0.7) × the **median** of the last `SUPPLIER_IMPORT_GUARD_WINDOW` (5) applied
  runs. Median, not mean: one force-applied outlier must not drag the
  baseline. A metric whose median is 0 (the setting never delivered it) is
  not checked. Thresholds live in `settings/project.py:37-47`.
- **independent of history**, the import would clear rows linked to the
  catalog: `missing_linked` ≥ max(`SUPPLIER_IMPORT_GUARD_MISSING_LINKED_MIN`
  (10), `…_SHARE` (0.05) × `linked_own`), both from `apply_counts`
  (`functions.py:925`) over the setting's own rows. Coverage is blind to
  this: a supplier that renames its products keeps the row count while every
  linked row goes missing. Skipped for a setting whose `clearable_fields()`
  (`models.py:131`) is empty (it clears nothing). Right after deploy,
  migration 0015 links every row of a multi-setting supplier to all its
  settings, so the first import of each such setting may trip this —
  correctly: those rows really are cleared once.

- **independent of history**, a column the setting maps by header is not in
  the file (`stats['missing_columns']`, reason `missing_columns`, which lists
  the file's headers). Its field would otherwise freeze at the last value — or
  take the setting's fallback for every row. A header that is present over an
  empty column is not missing: `get_df` drops all-empty columns but keeps their
  headers in `df.attrs['empty_columns']` (`functions.py:273-277`; it survives
  the cache pickle).

`price_changes()` (`functions.py:969`) records, per mapped price field, how
the file changes the prices of rows already in the base (`compared`,
`changed`, `jumps` beyond ×2 either way, `median_ratio`) into
`ImportRun.price_changes` and the dialog's «Разбор файла». **It does not hold
anything yet**: the production snapshot had too little price history to
calibrate a threshold. Calibrate it on the recorded runs once they accumulate
outside test mode.

Confirmed runs are `applied` runs, so they feed the history: a genuine shrink
stops asking after a few confirmations.

Confirmation mechanics — each piece closes a specific race:

- `import_run_apply` (`views.py:275`) claims the run with a conditional
  `UPDATE … WHERE status='pending'` → `running` and dispatches through
  `dispatch_after_commit`; a double click finds nothing to claim.
- The confirmed task re-applies **without** a second check, but only if the
  newest file and `_get_setting_signature` still match `ImportRun.signature`
  (`tasks.py:219-230`); otherwise the run becomes `superseded`. A confirmation
  never applies a file or mapping the user did not see.
- A new import of the setting, or a new upload, marks a pending run
  `superseded` through `supersede_pending_runs` (`tasks.py:109`). Cleanup
  skips files in `STATUS_NEEDS_CONFIRMATION`.
- **The confirmation notification never expires.** It is a `PersistentNotification`
  with `kind='confirmation'` and `ref='import_run:<pk>'` (see [[core]]). Every
  exit from pending deletes it for all users through `dismiss_confirmations`
  (`tasks.py:84`):
  - apply and cancel (the views)
  - both supersede sites (`supersede_pending_runs`)
  - `_finish_run` (`tasks.py:65`) with any status other than pending

  `_refuse_busy` (`tasks.py:174`) puts a confirmed run back to pending, so it
  re-creates the notification with the dialog link. A missed transition
  leaves the notification hanging until `_drop_stale_confirmations`
  (`tasks.py:423`) in `cleanup_supplier_files_task` catches it (every 30 min).
  Don't lean on that: a new transition out of pending should call
  `dismiss_confirmations` itself.
- `load_setting` (`functions.py:1012`) writes inside `transaction.atomic()`
  (`_apply`, `functions.py:1034`): upsert, clearing of missing rows and the
  supplier's `stock_updated_at` / `price_updated_at` land together or not
  at all.
- **The supplier is stamped with a queryset `update()`** (`_stamp_supplier`,
  `functions.py:1138`), never `setting.supplier.save()`. The `Supplier`
  object is loaded early in the import; a full `save()` wrote back every
  field a manager changed in the meantime — a priority level edited
  mid-import, for instance.

UI: `SettingListTable.last_import` (`tables.py:71`, annotated by
`SettingList.get_queryset`, `views.py:496`, one subquery, no N+1) shows the
last run; a pending one is a button opening `import_confirm_modal.html` in
its own compact `#import-confirm-modal` on the supplier page (not the shared
`modal-xl` container). `SupplierDetail` opens it on load for
`?import_run=<pk>` only while that run is still pending, so the
`HttpResponseClientRefresh` after apply/cancel does not reopen it.
