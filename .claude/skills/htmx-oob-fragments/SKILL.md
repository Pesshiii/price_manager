---
name: htmx-oob-fragments
description: Update several regions of a page from one HTMX response using hx-swap-oob, as done throughout core/templates/shopping_tab/. Use when one action must refresh a status chip, a summary panel and a list together without a full reload, when adding a view that returns a multi-fragment partial, or when an OOB region mysteriously renders blank.
---

# HTMX out-of-band fragments

The repo has **two** HTMX response conventions. Pick deliberately:

| | convention | skill |
|---|---|---|
| Form in a Bootstrap modal, success = full reload | `HttpResponseClientRefresh()` | `htmx-modal-crud` |
| One action updates several regions in place, no reload | `hx-swap-oob` fragments | **this one** |

Use OOB when a reload would be disproportionate or would lose state the user
cares about (scroll position, an open modal, a filled filter). The shopping-tab
/ cart feature in `core` is built almost entirely this way.

## Anatomy

**1. A fragment owns a region.** Its root element carries the region's `id` plus
`hx-swap-oob="true"`. HTMX places it by `id`, ignoring the triggering element's
`hx-target`.

```django
{# core/templates/shopping_tab/partials/item_state_chip.html #}
<div id="cart-item-state" hx-swap-oob="true">
  {% if item.confirmed_product %}...{% else %}...{% endif %}
</div>
```

**2. A response partial is just a list of fragments.** No wrapper element.

```django
{# core/templates/shopping_tab/partials/item_confirm_response.html #}
{% include 'shopping_tab/partials/item_state_chip.html' %}
{% include 'shopping_tab/partials/item_workspace.html' %}
```

**3. The view returns it, and refuses to serve it as a page.**

```python
class CartItemUnconfirmView(LoginRequiredMixin, View):
    template_name = 'shopping_tab/partials/item_confirm_response.html'

    def post(self, request, pk):
        if not request.htmx:
            return redirect('cart-item-detail', pk=pk)
        ...
        return render(request, self.template_name, {'item': item})
```

## The three response shapes in use

**Pure OOB** — every fragment is out-of-band, nothing is swapped into the
trigger's target. `item_confirm_response.html` above.

**Primary + OOB siblings** — the first element swaps into the target normally,
the rest go out-of-band. Gate the OOB part so it only fires when something
actually changed (`core/templates/shopping_tab/partials/add_item_form.html`):

```django
<form hx-post="..." hx-target="this" hx-swap="outerHTML"> ... </form>
{% if item_added %}
  <span id="cart-items-count" hx-swap-oob="true">{{ items_total }}</span>
  {% include 'shopping_tab/partials/tab_summary.html' %}
  {% include 'shopping_tab/partials/items_table.html' %}
{% endif %}
```

**Modal-aware** — the same view is reachable from a page and from inside a
modal, and the two need different responses. The template passes a flag with
`hx-vals='{"modal": "true"}'` and the view branches on it
(`CartItemConfirmProductView`, `CartItemRemoveProductView`):

```python
if request.POST.get('modal'):
    # redraw the modal in place; the list behind it updates OOB
    return render(request, 'shopping_tab/partials/item_products_modal_refresh.html', context)
return render(request, self.template_name, {'item': item})
```

Confirming inside the modal instead returns `HttpResponseClientRefresh()` —
reload is acceptable there because the modal closes anyway.

## Reusing one template both ways

A fragment that is sometimes the primary target and sometimes an OOB sibling
takes an `oob` flag rather than being duplicated:

```django
{# core/templates/shopping_tab/includes/product_select_cell.html #}
<div id="cart-item-select-{{ record.pk }}"{% if oob %} hx-swap-oob="true"{% endif %}>
```

Callers opt in with `{% include '...' with record=product added=True oob=True %}`.
Same idiom in `core/templates/core/partials/notifications_badge.html`,
`notifications_count.html`, and `main/includes/filter_field.html` (which spells
the flag `hx_swap_oob`).

## Checklist for a new OOB interaction

- [ ] Every region you intend to update already has a stable `id` on the page.
- [ ] One fragment template per region, root element carries that `id` + `hx-swap-oob="true"`.
- [ ] A response partial that `{% include %}`s them at **top level** — no wrapper `<div>`.
- [ ] View guards with `if not request.htmx: return redirect(...)`.
- [ ] **View supplies the context every fragment needs** — see the first gotcha.
- [ ] If the action is reachable from inside a modal, decide the modal response and pass `hx-vals='{"modal": "true"}'`.

## Gotchas

- **A fragment with missing context blanks its region instead of erroring.** This
  is the trap. Django renders undefined variables as empty, so an OOB fragment
  whose data you forgot to pass will silently wipe a working part of the page.
  `ShoppingTabAddItemView.post()` calls `context.update(_shopping_tab_summary(tab))`
  precisely so `tab_summary.html` and `items_table.html` have their numbers — drop
  that line and the summary panel goes blank with no error anywhere. When you add
  a fragment to an existing response partial, re-check what the view passes.
- **OOB elements must be top-level in the response.** HTMX only scans top-level
  children for `hx-swap-oob`. Wrapping your includes in a `<div>` for tidiness
  silently disables every one of them.
- **`hx-swap-oob` matches by `id`, not by target.** If the id isn't on the page
  when the response lands, that fragment is dropped — no error, no console
  warning. Modals are the usual cause: the region exists on the page behind, or
  doesn't exist yet, depending on what's open.
- **Group regions that always change together.** `item_workspace.html` deliberately
  wraps both columns in one OOB region because confirming a product changes both
  the decision panel and the candidate list — two fragments would mean two chances
  to get the context wrong. Its own comment says so.
- **`hx-swap-oob="outerHTML"` and `="true"` behave the same here.**
  `core/templates/core/includes/checkbox_field.html` uses `outerHTML`; everything
  in `shopping_tab/` uses `true`. Match whatever the file you're editing already does.
- **Don't reach for OOB when a reload is fine.** Modal CRUD forms use
  `HttpResponseClientRefresh()` on success and that stays the simpler default —
  it resets the DOM, closes the modal, and shows a `messages` toast for free.
