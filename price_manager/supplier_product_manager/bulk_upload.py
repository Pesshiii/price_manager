"""«Массовая загрузка» прайсов: все поставщики на одной странице << supplier/bulk-upload/ >>.

Строка на поставщика: настройка (по умолчанию — та, что применялась последней),
зона для файла и статус импорта. Файл, брошенный в строку, сразу сохраняется
и ставится в очередь; строка опрашивает свой статус, пока импорт идёт, и
отвечает только собой (hx-swap outerHTML) — остальные строки и незаконченные
загрузки в них страница не теряет.
"""
from pathlib import Path

from django.contrib import messages
from django.db.models import F
from django.db.models.functions import Greatest
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from supplier_manager.models import Supplier

from .forms import UploadFileForm
from .models import ImportRun, Setting, SupplierFile, format_count
from .views import (
  QUEUED_LOG,
  apply_import_run,
  cancel_import_run,
  start_setting_import,
  store_supplier_file,
)

ROW_TEMPLATE = 'supplier_product/bulk_upload/row.html'

# Row states. queued/running rows poll their own status.
IDLE, QUEUED, RUNNING, PENDING, APPLIED, ERROR, UNBOUND = (
  'idle', 'queued', 'running', 'pending', 'applied', 'error', 'unbound')
ACTIVE_STATES = {QUEUED, RUNNING}
# Which state a row filter chip picks; «overdue» is a separate flag.
FILTERS = [('all', 'Все'), ('overdue', 'Требуют обновления'), (PENDING, 'Ждут подтверждения'), (ERROR, 'С ошибкой')]


def _suppliers():
  return Supplier.objects.annotate(
    last_update=Greatest('price_updated_at', 'stock_updated_at'),
  ).order_by(F('last_update').asc(nulls_last=True), 'name')


def _file_label(supplier_file, run):
  name = (run.file_name if run and run.file_name else supplier_file.file.name) or ''
  return Path(name).name


def _last_log_line(logs):
  line = (logs or '').strip().splitlines()[-1:] or ['']
  # «[2026-09-30 12:00:00] текст» -> «текст»
  return line[0].split('] ', 1)[-1]


def updated_label(updated_at, now=None):
  """«сегодня 09:14», «вчера», «12 дн. назад», «не обновлялся»."""
  if updated_at is None:
    return 'не обновлялся'
  local = timezone.localtime(updated_at)
  days = (timezone.localdate(now) - local.date()).days
  if days <= 0:
    return f'сегодня {local:%H:%M}'
  if days == 1:
    return 'вчера'
  return f'{days} дн. назад'


def _job(supplier_file, run):
  """Статус последнего файла одной настройки."""
  status = supplier_file.status
  job = {'setting': supplier_file.setting, 'file': _file_label(supplier_file, run), 'run': run}
  if status == SupplierFile.STATUS_RUNNING:
    job['state'] = RUNNING
  elif status == SupplierFile.STATUS_QUEUED:
    # QUEUED is also the model default: a file uploaded but never put in the
    # queue (its setting was not mapped yet) has no queue log line.
    job['state'] = QUEUED if (supplier_file.logs or '').startswith(QUEUED_LOG) else IDLE
  elif status == SupplierFile.STATUS_NEEDS_CONFIRMATION:
    job['state'] = PENDING
    reasons = run.reason_lines() if run else []
    job['reasons'] = reasons
  elif status == SupplierFile.STATUS_SUCCESS:
    job['state'] = APPLIED
    if run:
      job['summary'] = (f'записано {format_count(run.covered or 0)}'
                        f' · новых {format_count(run.created or 0)}')
  else:
    job['state'] = ERROR
    if run and run.status == ImportRun.STATUS_CANCELLED:
      job['message'] = 'Импорт отменён, данные не изменены'
    else:
      job['message'] = (run.message if run and run.message else '') or _last_log_line(supplier_file.logs)
  job['finished_at'] = run.finished_at if run else None
  return job


def build_rows(suppliers, selected=None, upload_errors=None):
  """Строки страницы. selected: {supplier_pk: setting_pk} — выбор, который надо сохранить."""
  suppliers = list(suppliers)
  ids = [s.pk for s in suppliers]
  selected = selected or {}
  upload_errors = upload_errors or {}
  now = timezone.now()
  today = timezone.localdate()

  settings_by_supplier = {pk: [] for pk in ids}
  for setting in Setting.objects.filter(supplier__in=ids).only('id', 'name', 'supplier_id').order_by('name'):
    settings_by_supplier[setting.supplier_id].append(setting)

  last_applied = dict(
    ImportRun.objects.filter(supplier__in=ids, status=ImportRun.STATUS_APPLIED)
    .order_by('supplier_id', '-started_at').distinct('supplier_id')
    .values_list('supplier_id', 'setting_id'))

  # The newest file of every setting: cleanup keeps one per setting anyway.
  files = list(
    SupplierFile.objects.filter(setting__supplier__in=ids).select_related('setting')
    .order_by('setting_id', '-pk').distinct('setting_id'))
  runs = {
    run.supplier_file_id: run
    for run in ImportRun.objects.filter(supplier_file__in=[f.pk for f in files])
    .order_by('supplier_file_id', '-pk').distinct('supplier_file_id')
  }
  files_by_supplier = {pk: [] for pk in ids}
  for supplier_file in sorted(files, key=lambda f: -f.pk):
    files_by_supplier[supplier_file.setting.supplier_id].append(supplier_file)

  rows = []
  for supplier in suppliers:
    settings = settings_by_supplier[supplier.pk]
    setting_ids = {s.pk for s in settings}
    jobs = []
    for position, supplier_file in enumerate(files_by_supplier[supplier.pk]):
      job = _job(supplier_file, runs.get(supplier_file.pk))
      # The newest file always shows; other settings only while they need
      # attention — a supplier with a price file and a stock file uploads both.
      if position == 0 or job['state'] in (QUEUED, RUNNING, PENDING):
        jobs.append(job)
    error = upload_errors.get(supplier.pk)
    if error:
      jobs.insert(0, error)
    jobs = [j for j in jobs if j['state'] != IDLE]

    choice = selected.get(supplier.pk)
    if choice not in setting_ids:
      choice = last_applied.get(supplier.pk)
    if choice not in setting_ids:
      choice = max(setting_ids) if setting_ids else None

    statuses = [supplier.update_status(kind, now=now) for kind in ('price', 'stock')]
    state = jobs[0]['state'] if jobs else IDLE
    rows.append({
      'supplier': supplier,
      'settings': settings,
      'selected': choice,
      # Marked «последняя» in the select — only a setting that really was applied.
      'last_applied': last_applied.get(supplier.pk),
      'jobs': jobs,
      'state': state,
      'states': {j['state'] for j in jobs},
      'poll': any(j['state'] in ACTIVE_STATES for j in jobs),
      'overdue': any(s in ('overdue', 'never') for s in statuses),
      'updated_at': supplier.last_update,
      'updated_label': updated_label(supplier.last_update, now),
      'applied_today': any(j['state'] == APPLIED and j['finished_at']
                           and timezone.localdate(j['finished_at']) == today for j in jobs),
    })
  return rows


def _row_response(request, supplier, selected=None, upload_error=None):
  supplier = _suppliers().get(pk=supplier.pk)
  row = build_rows([supplier],
                   selected={supplier.pk: selected} if selected else None,
                   upload_errors={supplier.pk: upload_error} if upload_error else None)[0]
  return render(request, ROW_TEMPLATE, {'row': row})


def _selected_setting(request, supplier):
  value = request.POST.get('setting') or request.GET.get('setting') or ''
  if value.isdigit() and Setting.objects.filter(pk=value, supplier=supplier).exists():
    return int(value)
  return None


class BulkUploadView(TemplateView):
  template_name = 'supplier_product/bulk_upload/page.html'

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['rows'] = build_rows(_suppliers())
    context['filters'] = FILTERS
    return context


def bulk_upload_row(request, pk):
  '''Строка поставщика: GET — текущий статус (опрос), POST — загрузить файл и запустить импорт.'''
  supplier = get_object_or_404(Supplier, pk=pk)
  if request.method != 'POST':
    return _row_response(request, supplier, selected=_selected_setting(request, supplier))

  form = UploadFileForm(request.POST, request.FILES, pk=supplier.pk)
  if not form.is_valid():
    errors = [e for field_errors in form.errors.values() for e in field_errors]
    message = 'Выберите файл Excel (.xls, .xlsx, .xlsm)' if 'file' in form.errors else ' '.join(errors)
    return _row_response(request, supplier, selected=_selected_setting(request, supplier),
                         upload_error={'state': ERROR, 'message': message,
                                       'file': Path(getattr(request.FILES.get('file'), 'name', '')).name})
  supplier_file, error = store_supplier_file(request, supplier, form)
  if error:
    return _row_response(request, supplier, selected=_selected_setting(request, supplier),
                         upload_error={'state': ERROR, 'message': error,
                                       'file': Path(request.FILES['file'].name).name})
  setting = supplier_file.setting
  if not start_setting_import(setting, request.user):
    # The file is stored: once the setting is mapped, «Загрузить» on the
    # setting screen imports it without uploading again.
    return _row_response(request, supplier, selected=setting.pk, upload_error={
      'state': UNBOUND, 'setting': setting, 'file': Path(supplier_file.file.name).name,
      'setting_url': reverse('setting-update', kwargs={'pk': setting.pk}),
    })
  return _row_response(request, supplier, selected=setting.pk)


@require_POST
def bulk_upload_apply(request, pk, run_pk):
  '''«Подтвердить» в строке: применить импорт, который ждёт подтверждения.'''
  supplier = get_object_or_404(Supplier, pk=pk)
  run = apply_import_run(run_pk, request.user)
  if run is None:
    messages.warning(request, 'Этот импорт уже обработан')
  return _row_response(request, supplier, selected=_selected_setting(request, supplier))


@require_POST
def bulk_upload_cancel(request, pk, run_pk):
  '''«Отменить» в строке: данные не меняются.'''
  supplier = get_object_or_404(Supplier, pk=pk)
  if cancel_import_run(run_pk, request.user):
    messages.info(request, 'Импорт отменён, данные не изменены')
  else:
    messages.warning(request, 'Этот импорт уже обработан')
  return _row_response(request, supplier, selected=_selected_setting(request, supplier))
