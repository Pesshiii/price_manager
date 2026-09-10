---
name: ui-review
description: Screenshot price_manager's real screens in the running Docker stack and review them for layout, accessibility and Russian UI-copy problems. Use when explicitly asked for a UI review, a design critique, an accessibility pass, a responsive/mobile check, or "how does this screen actually look". Boots the stack, so do not reach for it unprompted after routine template edits.
---

# UI review

price_manager has no design system, no CSS build and no component library — the
UI is Django templates + HTMX + a CDN Bootstrap. So a design review here cannot
read tokens or diff components. It has to **look at rendered pages**.

This skill boots the stack, drives the app with the Playwright REPL, captures a
named set of screens, and turns the screenshots into a findings report.

**It does not file GitHub issues.** Issue creation belongs to `tg-tracker` and
`/triage`, which carry the duplicate search and the audit trail. Two systems
creating issues with different dedup behaviour is how the tracker fills with
stale duplicates. End with the report and offer; let the user decide.

## Before anything renders — four gates

Each of these produces screenshots that *look* fine and are worthless. Check all
four before capturing, and abort rather than reviewing bad pixels.

**1. The stack is serving.** Follow `run-price-manager` to bring it up
(`docker compose up --build -d`), then poll — gunicorn logs `Listening at`
before Django has finished `migrate`/`collectstatic`:

```bash
timeout 60 bash -c 'until curl -s -o /dev/null -w "%{http_code}" "http://localhost:${WEB_PORT:-8000}/admin/" 2>/dev/null | grep -qE "^[23]"; do sleep 2; done'
```

If another agent is running a second stack, `WEB_PORT` and `PROJECT_NAME` decide
which one you poll, screenshot and `exec` into — see "Which stack you are talking
to" in `run-price-manager`. Reviewing the wrong stack is a fifth way to produce
plausible, worthless screenshots: they render fine, they are just someone else's
branch.

**2. Login actually took.** `LoginRequiredMiddleware` gates everything behind
`/`, so a failed login silently gives you five screenshots of the login form.
After `login`, run `url`. A good login lands on **`/mainproduct/`**, not `/`.
If the url still contains `/accounts/login/`, the `agent_test` account is
missing from this volume — recreate it with the command in
`run-price-manager`'s *Test account* section and start over. Do not proceed.
This is not hypothetical: the volume on this machine had **zero users** when
this skill was written, and the failure is silent.

**3. Bootstrap actually loaded.** `base.html` pulls Bootstrap 5.3, select2,
bootstrap-icons and jQuery from **jsdelivr and code.jquery.com** at render time.
With blocked or absent egress the page renders unstyled, and a critique of an
unstyled page is a flood of false findings. Gate on a BS5 custom property
resolving:

```
eval getComputedStyle(document.documentElement).getPropertyValue('--bs-primary')
```

Empty string → the CDN did not load. Stop and say so; do not review.

**4. There is data to review.** An empty database renders «Товары не найдены»
everywhere, and a review of that is a review of empty states — worth doing, but
it is not a review of the tables, the density, or the responsive behaviour of a
real price list. Count first:

```bash
docker compose exec -T web python manage.py shell -c "
from supplier_manager.models import Supplier
from main_product_manager.models import MainProduct
print('suppliers:', Supplier.objects.count(), 'products:', MainProduct.objects.count())"
```

At zero, say so in the report and scope the review to empty states, navigation
and forms. Do not describe an empty table as a layout problem.

## Capture

Launch the driver with screenshots going to the scratchpad, not the repo:

```bash
cd .claude/skills/run-price-manager
SCREENSHOT_DIR="<scratchpad>/ui-review-shots" \
  BASE_URL="http://localhost:${WEB_PORT:-8000}" node driver.mjs <<'EOF'
launch
nav /accounts/login/
screenshot 06-login
login
url
nav /
eval getComputedStyle(document.documentElement).getPropertyValue('--bs-primary')
screenshot 01-mainpage
EOF
```

Keep it to one heredoc per logical group — the driver processes lines
sequentially, so a single long heredoc is fine, but a failure midway is easier
to read when the groups are separate.

### The screen catalogue

Top-level screens. The header nav labels them **Поставщики / Валюта / Заявки / Еще**
— use those names in findings, not the model names:

| # | Screen | Path | Why it matters |
|---|---|---|---|
| 01 | Главная | `/` | landing |
| 02 | Главный прайс | `/mainproduct/` | the widest table in the app; HTMX search + infinite scroll |
| 03 | Поставщики | `/supplier/` | list; «Добавить» navigates away rather than opening a modal |
| 04 | Валюта | `/currency/` | smallest list; its «Добавить» is a bare unstyled `<button>` — see *Two create affordances* below |
| 05 | Заявки | `/shopping-tabs/` | the `hx-swap-oob` screens |
| 06 | Вход | `/accounts/login/` | the only logged-out page — shoot it **first**, before `login`; afterwards Django bounces you to `/mainproduct/` |

Everything else sits behind a primary key. **Resolve pks by scraping the list
page, never by hardcoding and never with a `manage.py shell` query** — the skill
has to work against whatever database the volume happens to hold:

```
nav /supplier/
eval Array.from(document.querySelectorAll('a[href^="/supplier/"]')).map(a => a.getAttribute('href')).filter(h => /^\/supplier\/\d+\/$/.test(h)).slice(0, 5)
```

Then shoot the ones that came back:

| Screen | Path shape |
|---|---|
| Карточка поставщика | `/supplier/<pk>/` |
| Настройки разметки колонок | `/supplier/<pk>/settings/` |
| Наценки поставщика | `/supplier/<pk>/pricemanagers/` |
| Карточка товара | `/mainproduct/<pk>/detail` |
| Корзина | `/shopping-tabs/<pk>/` |

### Modals — otherwise you review only tables

Most forms in this app live in a modal, and a full-page shot of a list page
captures none of them. Per `htmx-modal-crud` the trigger carries
`data-bs-toggle="modal" data-bs-target="#modal-container"` and HTMX swaps the
body in afterwards, so the shell opens instantly and the content arrives late.

On Главный прайс the triggers are **page-level buttons**, not row actions —
verified 2026-09-04, and worth knowing because one of them is not a form:

| Order in DOM | Button | `hx-get` |
|---|---|---|
| 1 | «Добавить товар» | `/mainproduct/create` |
| 2 | «Добавить категорию» | `/mainproduct/mainproduct/bulk-category` |
| 3 | «Обновить» | `/mainproduct/sync` |

`click [data-bs-target="#modal-container"]` takes the **first** match, which is
«Добавить товар» — the one you want. Do not iterate blindly over the three:
the third starts a PIM sync, which is real work against the external API, not a
form to photograph. Target by text or `hx-get` if you need a specific one.

```
nav /mainproduct/
sleep 1500
click [data-bs-target="#modal-container"]
sleep 1200
text #modal-container .modal-content
screenshot 02-mainproduct-modal
```

**Confirm with `text`, not `wait-for`.** The `#modal-container` shell ships
with placeholder markup (417 characters of it before any fetch), so a
`wait-for #modal-container .modal-body` returns the moment Bootstrap adds
`.show` and proves nothing about the content having arrived — the `sleep` is
doing the real waiting. Reading the text back is what tells you the form is
there; the row actions in
`main_product_manager/templates/mainproduct/partials/tables_bycat.html:12-34`
follow the same convention but only exist once the table has rows.

`#modal-container` is also the pattern on the корзина screens
(`core/templates/shopping_tab/`) and the наценки screens
(`product_price_manager/templates/price_manager/partials/`). Shoot at least one
of each; the shopping-tab modals are the `hx-swap-oob` variety and behave
differently on submit.

#### Two create affordances — a standing inconsistency

The convention is not universal, and the exception is worth knowing before you
report it as a bug:

| Screen | «Добавить» does | Source |
|---|---|---|
| Главный прайс, корзины, наценки | opens `#modal-container` | `tables_bycat.html:12` |
| Поставщики | `onclick` full-page nav to `/supplier/create/` | `supplier_manager/templates/supplier/list.html:12` |
| Валюты | same, and the button has **no Bootstrap class at all** | `core/templates/currency/list.html` |

So the same action type has two different affordances, and one of the three
buttons is unstyled. **Verified visually on 2026-09-04:** `/currency/` renders a
browser-default grey button flush against the viewport edge, with no page
heading and no `.container` wrapper, while `/supplier/` and `/mainproduct/` are
laid out normally. That is a legitimate consistency finding — report it once,
here, rather than as a surprise on each screen. It also means you cannot reach
the supplier or currency create forms with a `click`; navigate to
`/supplier/create/` and `/currency/create/` directly.

### Responsive

`viewport` resizes but does **not** re-render HTMX fragments already in the DOM,
so resize *before* navigating:

```
viewport 375x812
nav /mainproduct/
sleep 1000
screenshot 02-mainproduct-mobile
viewport 1280x720
```

Worth doing on 02 (Главный прайс, the wide table) and 05 (Заявки) at minimum. `base.html`
sets a normal `width=device-width` viewport meta, and the wide tables rely on a
`.scrollbar-top` overflow wrapper — check that it still scrolls rather than
overflowing the body.

### HTMX timing, generally

The product search box is debounced `delay:0.5s` and swaps `#mainproducts-table`
by `outerHTML`. Anything that swaps a table has the same shape. After a `fill`
or a filter click, `sleep` ≥1000ms before shooting, or you capture stale content
and draw conclusions from it. See `run-price-manager`'s *Gotchas*.

Finish with `console --errors` — a JS error explains a broken-looking screen far
more cheaply than a visual critique of it.

## Review

### Known causes — check these first and collapse into them

**The Bootstrap version is split.** Crispy emits BS4 markup into a BS5
stylesheet — CLAUDE.md's *Frontend* section owns the full explanation and the
reason not to "fix" it. What matters for a review is the discipline it demands:

**Measure before you attribute.** `.form-control` survives in BS5, so most
forms look right and this mismatch is *not* automatically the cause of what you
are looking at. Only four dropped classes produce visible breakage. Count them
on the screen in question:

```
eval document.querySelectorAll('.custom-select, .form-row, .form-control-file').length
```

Nonzero is evidence; zero means look elsewhere for the cause. The upload
screens are the likeliest place to find them (`crispy_bootstrap4` ships a
`field_file.html`). When several screens do show it, report it once as this one
root cause with the affected screens listed, not as separate findings.

**Everything is Russian.** `<html lang="ru">`, and every string in `base.html`
and the templates is Russian. Findings about copy, and any suggested
replacement text, must be written in Russian to be actionable. An English
microcopy suggestion cannot be pasted into a template and is noise.

### Then the general pass

If `design:design-critique` and `design:accessibility-review` are available in
this session, hand them the screenshots — they carry the WCAG criteria and the
hierarchy/consistency vocabulary, and there is no reason to restate it here.
Tell each one, in the prompt, that the UI language is Russian and the framework
is Bootstrap 5 with no custom design system.

Those skills are served by the session, not installed in this repo, so a plain
terminal session may not have them. If they are absent, do the pass inline
against this checklist rather than stopping:

- **Contrast and state** — Bootstrap defaults mostly pass; custom colours and
  the `text-muted` on light backgrounds are where it fails.
- **Touch targets** on the mobile shots — table row actions are the usual
  offender.
- **Hierarchy** — what does the eye land on first, and is that the primary
  action on the screen?
- **Consistency across screens** — the same action named or placed differently
  on two lists is a real finding and the one a per-screen review misses.
- **Empty and loading states** — HTMX swaps leave gaps; the modal spinner
  placeholder is visible whenever the fetch is slow.
- **Keyboard reachability** of modal open/close, since modals hold every form.

## Report

Write `ui-review-<YYYY-MM-DD>.md` to the scratchpad and send it with
`SendUserFile` alongside the two or three screenshots that carry the argument.
Do not paste every screenshot into the transcript.

Structure it as:

1. **What was captured** — screens, viewports, and anything that could not be
   reached (with why).
2. **Root causes** — the collapsed ones, the crispy/BS5 mismatch first if it
   showed up.
3. **Findings**, each with the screen, what is wrong, and what it should be.
   Russian for anything that becomes UI copy.
4. **Not filed** — say plainly that nothing was written to the tracker, and
   offer: the promising ones can go to `/triage` or `tg-tracker` as
   `needs-triage` issues on request.

Rank by whether a user is blocked, not by how bad it looks.

## Do not

- **Do not `docker compose down -v`.** A `PreToolUse` hook guards this; do not
  work around it. The volume was empty when this skill was written, but a
  review is never the reason to find out whether it still is — plain
  `docker compose down` is enough to reset containers and touches no volume.
- **Do not edit templates during a review.** Capture and critique are one job;
  fixing is another, and mixing them means the screenshots no longer match the
  code they describe.
- **Do not review the `product`, `pricing`, `supplier`, `supplier_feed` or
  `dataframe` apps' surfaces.** They are the retiring API-first stack and have
  no UI worth improving — see CLAUDE.md's *Direction of travel*.
- **Do not file issues from this skill.** See the top.

$ARGUMENTS
