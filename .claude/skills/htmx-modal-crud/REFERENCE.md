# HTMX Modal CRUD — reference templates

Working, current examples of this exact pattern to read before copying blindly:
- `price_manager/product_price_manager/{views,tables,forms}.py` and
  `price_manager/product_price_manager/templates/price_manager/partials/{create,update,table,pricemanager_form}.html`
  — the cleanest example, including inline delete.
- `price_manager/main_product_manager/{views,tables}.py` and
  `.../templates/mainproduct/{list.html,partials/update.html}` — uses
  `HttpResponseClientRedirect` instead of refresh, and the simple crispy form style.
- `price_manager/core/templates/core/includes/table_htmx.html` — the shared
  sortable/infinite-scroll table template every `Table.Meta` should point at.

Below, replace `App`/`app`/`Model`/`model` with your names.

## models.py

Plain Django model — nothing special about this pattern's models.

## admin.py

```python
from django.contrib import admin
from .models import Model

@admin.register(Model)
class ModelAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
```

## forms.py — option A: crispy (default choice)

```python
from django import forms
from .models import Model

class ModelForm(forms.ModelForm):
    class Meta:
        model = Model
        fields = ['name', 'value']
```

Rendered in the template with `{% load crispy_forms_tags %}{{ form|crispy }}` —
no `FormHelper` needed for a plain vertical form. `CRISPY_TEMPLATE_PACK` is
already set to `bootstrap4` in `price_manager/price_manager/settings/third_party.py`;
this is intentional even though the surrounding modal chrome is Bootstrap 5
(`data-bs-*`) — the two coexist, crispy only touches field markup.

## forms.py — option B: manual per-field (when you need custom layout)

Same `ModelForm`, but rendered field-by-field in the template with
`django-widget-tweaks` instead of `|crispy`. Use this when fields need to be
grouped into custom rows/cards, need conditional collapse (e.g. a fixed-price
vs. formula toggle), or need a bespoke widget like the discounts
multi-select-as-dropdown in `pricemanager_form.html`. See that file for the
full pattern (checkbox-driven `collapse` sections, a custom dropdown-with-search
built from a `<select multiple>`, all vanilla JS at the bottom of the partial).

Basic field:
```html
{% load widget_tweaks %}
<div class="mb-3">
  <label class="form-label">{{ form.name.label }}</label>
  {% render_field form.name class="form-control form-control-sm" %}
  {% if form.name.errors %}
    <div class="invalid-feedback d-block">{{ form.name.errors|join:", " }}</div>
  {% endif %}
</div>
```

## tables.py

```python
from django.utils.html import format_html
from django.urls import reverse
import django_tables2 as tables
from .models import Model

class ModelListTable(tables.Table):
    class Meta:
        model = Model
        fields = ['name', 'value']
        template_name = 'core/includes/table_htmx.html'
        attrs = {'class': 'table table-auto table-stripped table-hover clickable-rows'}

    def render_name(self, record):
        return format_html(
            '''<a title="Обновить" class="btn btn-sm btn-primary"
                 data-bs-toggle="modal" data-bs-target="#modal-container"
                 hx-get="{}" hx-target="#modal-container .modal-content" hx-swap="innerHTML">
                 <i class="bi bi-pencil-square"></i></a> <span>{}</span>''',
            reverse('model-update', kwargs={'pk': record.pk}), record.name,
        )
```

## views.py

```python
from django.contrib import messages
from django.shortcuts import resolve_url
from django.views.generic import CreateView, UpdateView
from django_tables2 import SingleTableView
from django_htmx.http import HttpResponseClientRefresh
from .models import Model
from .forms import ModelForm
from .tables import ModelListTable

class ModelList(SingleTableView):
    model = Model
    table_class = ModelListTable
    template_name = 'app/partials/table.html'

    def get(self, request, *args, **kwargs):
        if self.request.htmx:
            self.template_name = 'app/partials/table.html#table'
        return super().get(request, *args, **kwargs)


class ModelCreate(CreateView):
    model = Model
    form_class = ModelForm
    template_name = 'app/partials/create.html'

    def get_success_url(self):
        return resolve_url('model-create')

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Добавлено')
        return HttpResponseClientRefresh()


class ModelUpdate(UpdateView):
    model = Model
    form_class = ModelForm
    template_name = 'app/partials/update.html'

    def dispatch(self, request, *args, **kwargs):
        self.instance = Model.objects.get(pk=self.kwargs.get('pk'))
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return resolve_url('model-update', self.kwargs.get('pk'))

    def post(self, request, *args, **kwargs):
        if request.POST.get('delete') == 'true':
            self.instance.delete()
            return HttpResponseClientRefresh()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        form.save()
        messages.success(self.request, 'Сохранено')
        return HttpResponseClientRefresh()
```

`get_success_url` matters even though the response is a client refresh: Django
still requires it to exist for `CreateView`/`UpdateView.form_valid()`'s default
flow to be overridable safely, and other code paths (e.g. `form_invalid` isn't
touched, but some subclasses call `super().form_valid()`) may rely on it.

## urls.py (wherever this app's routes live — see checklist)

```python
path('models/', views.ModelList.as_view(), name='models'),
path('model/create/', views.ModelCreate.as_view(), name='model-create'),
path('model/<int:pk>/', views.ModelUpdate.as_view(), name='model-update'),
```

## templates/app/list.html

```html
{% extends 'base.html' %}

{% block body %}
  {% partialdef table inline %}
    {% load django_tables2 %}
    {% render_table table %}
  {% endpartialdef %}

  <div id="modal-container" class="modal modal-xl fade" tabindex="-1" aria-hidden="true">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="container d-flex justify-content-center mb-4 mt-4">
          <div class="spinner-grow" role="status"></div>
        </div>
      </div>
    </div>
  </div>
{% endblock %}
```

`{% partialdef table inline %}` (django-template-partials) is what lets
`views.py` request `'app/partials/table.html#table'` for an htmx-only fragment
while the same file serves the full page on a normal GET. `#modal-container`
must be declared exactly once per list page — every trigger on that page reuses it.

## templates/app/partials/create.html

```html
<div class="modal-header">
  <h5 class="modal-title">Новая запись</h5>
  <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
</div>
<form method="post" hx-post="{% url 'model-create' %}"
      hx-target="#modal-container .modal-content" hx-swap="innerHTML">
  {% csrf_token %}
  <div class="modal-body">
    {% if form.non_field_errors %}
      <div class="alert alert-danger">{{ form.non_field_errors }}</div>
    {% endif %}
    {% include "app/partials/model_form.html" with form=form %}
  </div>
  <div class="modal-footer gap-2">
    <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button>
    <button type="submit" class="btn btn-primary px-4">Добавить</button>
  </div>
</form>
```

Add `enctype="multipart/form-data"` to the `<form>` if the model has a
`FileField`/`ImageField`.

## templates/app/partials/update.html

Same as `create.html`, but `hx-post` targets `model-update`, and the footer
gets an extra delete button:

```html
<button type="submit" name="delete" value="true" class="btn btn-outline-danger me-auto"
        onclick="return confirm('Удалить эту запись?')">Удалить</button>
```

## templates/app/partials/model_form.html

The actual `<label>`/field markup, `{% include %}`d by both `create.html` and
`update.html` so the two stay in sync — see the two forms.py options above for
what goes here (`{{ form|crispy }}` for option A, or field-by-field
`{% render_field %}` blocks for option B).

## Table trigger, if not embedded via `render_<col>()`

On a detail/list page outside the table (e.g. a detail view's edit button):

```html
<button type="button" class="btn btn-primary"
        data-bs-toggle="modal" data-bs-target="#modal-container"
        hx-get="{% url 'model-update' pk=object.pk %}"
        hx-target="#modal-container .modal-content" hx-swap="innerHTML">Изменить</button>
```
