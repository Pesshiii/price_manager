---
title: Middleware
summary: LoginRequiredMiddleware, toaster_middleware and the Bitrix24 link-required gate.
code: price_manager/core/middleware.py
---
# Middleware

## Middleware (`core/middleware.py`)

`LoginRequiredMiddleware` (class starts `:71`) — global login gate;
**everything behind `/` requires login**. Exemptions: `STATIC_URL`/`MEDIA_URL`
prefixes, `settings.LOGIN_URL`, `LOGIN_EXEMPT_URLS`, and `/admin/login`,
`/admin/logout` (hardcoded, so the stock admin login still works). Every other
anonymous request is redirected to the login page — there is no JSON 401
branch any more: it served the `/api/` routes, removed with the API stack.

`LOGIN_EXEMPT_URLS` entries are **URL names**, not raw paths: `__init__`
(`:74-88`) resolves each via `resolve_url()` once, into a path set
(`:79-82`), then `_is_exempt` does an exact `path in self.exempt_paths` check
per request (`:108`). `'bitrix24-login'`/`'bitrix24-callback'` were added
here (`settings/messages.py:19-20`) alongside `'login'`/`'logout'`/`'admin:*'`.

`toaster_middleware` (`:138-154`) — if `django.contrib.messages` storage is
non-empty, adds `HX-Trigger-After-Settle: toasts:fetch` to the response via
`trigger_client_event(..., after="settle")`. Adapted from Josh Karamuth's
django-messages-toast-htmx pattern (credited in the docstring). The listener
is `core/templates/base.html:34` — `hx-get="{% url 'toast-messages' %}"
hx-trigger="toasts:fetch from:body"`.

**A 204 response never shows its pending message as a toast.** HTMX does no
swap on 204 (`HX-Swap: none` semantics are implicit — no content, nothing to
settle), so `htmx:afterSettle` never fires and the `HX-Trigger-After-Settle`
header is never acted on; the message stays in the session and only surfaces
on the *next* full page load, not the action that produced it. Fix: return an
empty **200** (`HttpResponse()`) instead of `HttpResponse(status=204)`, paired
with `hx-swap="none"` on the triggering element — the swap is a no-op but
settle still happens. `HttpResponseClientRefresh` actions are unaffected
(the reload itself re-renders the message). Worked example:
`product/views.py:260-284` `ProductExportView` — its docstring (`:269-274`)
states the same reasoning after the view was changed from 204 to 200; see
[[product]] for the export feature itself.

`Bitrix24LinkRequiredMiddleware` (`:12-68`, ahead of `LoginRequiredMiddleware`
in this file) is the Bitrix24 link gate — see [[core/bitrix24-login]] for the
mechanism it enforces.
