---
title: Bitrix24 login — mechanism
summary: How the hand-rolled Bitrix24 OAuth login links, matches and creates users.
code: price_manager/core/bitrix24.py, price_manager/core/views.py
---
# Bitrix24 login — mechanism

## Bitrix24 login — mechanism (CLAUDE.md's `core` bullet covers purpose/policy)

`core/bitrix24.py` + `bitrix24_login`/`bitrix24_callback` (`core/views.py:133`,`:151`).

- `login()` after the hand-rolled exchange needs `user.backend` set by hand
  (`views.py:197`) — no `authenticate()` call happened, so Django can't infer
  it; omitting it raises `ValueError`.
- OAuth `state` is compared as **bytes** —
  `secrets.compare_digest(state.encode(), expected_state.encode())`
  (`views.py:165-167`) — because `compare_digest` raises `TypeError` on a
  non-ASCII `str`; pinned by `test_non_ascii_state_is_refused_not_a_500`
  (`tests.py:284`).
- `_get_json` (`bitrix24.py:64-91`) logs only `type(exc).__name__`, never
  `str(exc)`, on a `requests.RequestException` (`:71`) — urllib3's message
  embeds the full request URL, and the query string carries
  `client_secret`/`access_token`.
- The callback URL doubles as the Bitrix app's **install URL**
  (`views.py:155-158`): Bitrix POSTs install-time tokens there; the view
  answers 200 and stores nothing — why it's `@csrf_exempt` (`:149`).
- Tests fake the network with a URL-dispatching `side_effect` on
  `core.bitrix24.requests.get` (`_fake_bitrix24`, `tests.py:191-204`) rather
  than patching `exchange_code`/`fetch_current_user` — so the portal-endpoint
  check and request params get exercised, not assumed.
- Login vs link is decided by **session state**, not by what the lookup finds:
  `bitrix24_callback` passes `link_to=request.user` when someone is logged in,
  and `resolve_user` then only calls `link()` — it can refuse, never switch
  users. Refusals in link mode go back to `bitrix24-link`, not `login` (which
  would bounce a logged-in user straight to the main page).
- `user.current` returns `ID` as a **string**; `resolve_user` casts it and
  refuses a non-positive/unparseable one before any lookup (`bitrix24.py:217-224`).
- A race on the unique `bitrix_user_id` (two first logins at once) is caught as
  `IntegrityError` inside a savepoint in `link()` (`bitrix24.py:159-182`) and
  `_create_user()` (`:185-206`); the loser's freshly created user is rolled
  back and both end up in the winner's account.
- `Bitrix24LinkRequiredMiddleware` answers htmx with `HttpResponseClientRedirect`
  (`middleware.py:43`) — a plain 302 would be swapped into the fragment — and
  takes `next` from `HX-Current-URL`, since the htmx request path is a
  fragment. `toast-messages` is exempt: the link page's own toasts would
  otherwise trigger a fetch that redirects back to it.
- Keepdb trap met while testing this: a test DB kept from **another branch**
  holding an extra table with an FK to `auth_user` makes every
  `TransactionTestCase` flush fail with «cannot truncate a table referenced in a
  foreign key constraint». Not the code — rerun without `--keepdb`.
