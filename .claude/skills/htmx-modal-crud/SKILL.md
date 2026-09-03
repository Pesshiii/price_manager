---
name: htmx-modal-crud
description: Scaffold a Django model with a list view (django-tables2) plus create/edit "modal" views wired up with HTMX + Bootstrap 5, matching this repo's legacy-app conventions (product_price_manager, main_product_manager, supplier_manager). Use when the user asks to add a new model/CRUD screen, "add a modal form", "add an edit modal", or a new manageable list to one of the legacy apps.
---

# HTMX Modal CRUD

Scaffolds the repo's standard pattern: a django-tables2 list where each row opens
a Bootstrap modal via HTMX, backed by plain `CreateView`/`UpdateView`. There is
**no shared Python mixin/base class for this** (`core/viewmixins.HtmxMixin` exists
but is dead code — don't use it). Reusability lives entirely in the template
convention below. See [REFERENCE.md](REFERENCE.md) for full copy-paste templates.

## The pattern, end to end

1. Row/detail page has a trigger element:
   `data-bs-toggle="modal" data-bs-target="#modal-container"` (opens the Bootstrap
   shell instantly) plus `hx-get="{% url '<name>-update' pk %}" hx-target="#modal-container .modal-content" hx-swap="innerHTML"`
   (HTMX fills it with the real form).
2. The list page declares the modal shell **once**: `<div id="modal-container" class="modal modal-xl fade">...spinner placeholder...</div>`.
3. `CreateView`/`UpdateView` render a template containing only
   `.modal-header` / `.modal-body` / `.modal-footer` (no `{% extends %}`) —
   this is what gets swapped into `#modal-container .modal-content`.
4. The `<form>` inside re-targets itself: `hx-post="..." hx-target="#modal-container .modal-content" hx-swap="innerHTML"`.
   Validation errors just re-render the same partial with `form.errors` — no
   special handling needed.
5. On success, return `django_htmx.http.HttpResponseClientRefresh()` — this is
   the default and simplest way to close the modal (full reload resets the DOM)
   and show the updated list + a `messages` toast. Use
   `HttpResponseClientRedirect(url)` instead only when success should navigate
   somewhere else (e.g. to a detail page), as `main_product_manager` does.
6. Inline delete (optional): a `<button type="submit" name="delete" value="true" onclick="return confirm('...')">`
   in the modal footer; the `UpdateView.post()` checks
   `request.POST.get('delete') == 'true'` and deletes before falling through
   to `super().post()`.

## Checklist for a new model

- [ ] `models.py` — plain model.
- [ ] `admin.py` — `@admin.register` + `ModelAdmin(list_display=[...])`. (Cart-related
      models in `core/` skip this — don't skip it for new models; it's a real gap there, not a convention.)
- [ ] `forms.py` — `ModelForm`. Default to crispy (`{{ form|crispy }}`,
      `CRISPY_TEMPLATE_PACK` is already `bootstrap4`) unless the form needs
      bespoke per-field layout, in which case use the manual
      `{% load widget_tweaks %}` + `{% render_field %}` style — see REFERENCE.md
      for both.
- [ ] `tables.py` — `django_tables2.Table` subclass, `Meta.template_name = 'core/includes/table_htmx.html'`
      (shared repo-wide partial: sortable headers via `hx-get`, infinite-scroll via
      `hx-trigger="intersect once"` on the last row — don't reinvent this).
      Add a `render_<col>()` method on whichever column should carry the
      modal-open trigger link.
- [ ] `views.py` — `SingleTableView` for the list (toggle `template_name` to
      `'...#table'` when `request.htmx` for partial refresh), `CreateView`,
      `UpdateView`.
- [ ] `templates/<app>/list.html` — extends `base.html`, declares `#modal-container`.
- [ ] `templates/<app>/partials/{create,update}.html` — modal body partials.
- [ ] `templates/<app>/partials/<name>_form.html` — the actual form fields, `{% include %}`d by both create/update partials so they stay in sync.
- [ ] `urls.py` — most legacy apps register routes centrally in
      `price_manager/price_manager/urls.py` rather than a per-app `urls.py`
      (exception: `main_product_manager` has its own, `include()`d). Match
      whatever the target app already does.

Full field-by-field templates, both form-rendering styles, and real examples
(with file paths) are in [REFERENCE.md](REFERENCE.md).
