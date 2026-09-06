---
name: ux-copy-pass
description: Review price_manager's Russian UI copy — toasts, buttons, empty states, form labels, verbose_names — against both the rendered screens and the source strings that produce them, and report paste-ready replacements. Use when asked for a copy review, a microcopy pass, a terminology audit, or "do these messages actually say anything". Boots the stack, so do not reach for it unprompted after routine template edits.
---

# UX copy pass

`ui-review` looks at pixels. This looks at **words** — and the two do not see the
same surface, which is why this is a separate skill rather than a section of that
one.

UI copy in this repo lives in four places, and a screenshot reaches only part of
each:

| Where it lives | How much | On screen when? |
|---|---|---|
| Template literals | most of 146 templates | when you navigate there |
| `verbose_name` in `models.py` | **160** across the six live apps | only via a rendered form label or table header |
| `messages.*` toasts | **26** calls, whole repo | for a few seconds, **after an action**, fetched by HTMX |
| Form labels and validation errors | `forms.py` | only on a submit that fails |

A screenshot-only pass misses most of the copy; a grep-only pass can enumerate
every string but cannot say which ones a user actually meets, or in what company.
**This skill runs both and reconciles them.** The source pass enumerates; the
rendered pass ranks.

## The one thing that is easy to get wrong

**Use `git grep`, never `grep -r`.**

`.claude/worktrees/` holds full checkouts of the tree and is **not** in
`.gitignore`. A plain `grep -r` therefore walks every string twice. That is
merely annoying for a count and *fatal* for this skill specifically: two copies
of one string at two paths is indistinguishable from the inconsistency class you
are hunting, so the pass invents duplicate-terminology findings that do not
exist.

`git grep` reads the index, which a linked worktree is not in, so it sidesteps
this with no filter. Verified 2026-09-06 — `grep -r` reported 52 `messages.*`
calls and 6 `'Ошибка'`; the true numbers are **26 and 3**.

Every command below is `git grep` for this reason. If you reach for anything
else, exclude `.claude/worktrees` by hand.

## Gates

**`ui-review` owns these — read its four gates and satisfy all of them before
capturing anything.** Stack serving, login actually took, Bootstrap loaded from
the CDN, data present. They are not restated here; they fail the same way and
abort the same way.

One addition specific to this pass: at **zero products** the rendered half is
still worth running. Empty states are copy, they are some of the worst copy in
any app, and «Товары не найдены» is exactly the kind of string this skill exists
to interrogate. Say in the report that the tables were empty, and do not describe
an empty table as a copy problem.

## Pass 1 — the source inventory

Run these first. They are cheap, they need no stack, and they tell the rendered
pass what to go looking for.

**Toast and message strings** — the highest-value surface, because these are the
app talking back to someone who just did something:

```bash
git grep -n -E "messages\.(success|error|warning|info)\(" -- '*.py'
```

**Template literals**, per screen you plan to shoot:

```bash
git grep -n -E ">[[:space:]]*[А-Яа-яЁё]" -- '*/shopping_tab/*.html'
```

> **Start every pathspec with `*`, and check it returned something.** The Django
> root is `price_manager/`, one level below the repo root where `git grep`
> anchors, so a pathspec beginning `core/templates/…` silently matches
> **nothing** — no error, just zero results, which reads exactly like "no Russian
> strings here". A leading `*` matches across slashes and fixes it. Verified
> 2026-09-06: the anchored form returned 0, `'*/shopping_tab/*.html'` returned
> 105.
>
> Directory names are not all as convenient as `shopping_tab/`, which is unique
> in the tree. Currency templates are at `'*/templates/currency/*.html'`, and
> supplier ones at `'*/templates/supplier/*.html'` — where `supplier` is also the
> name of a retiring app, so include `templates/` in the pathspec to stay out of
> it. **A zero from any of these means "check the pathspec", not "no strings
> here"**, until you have seen it return nonzero once.

**Model `verbose_name`s** — scope to `models.py` and nothing else:

```bash
git grep -n "verbose_name" -- '*/models.py'
```

> **Never touch a migration.** `verbose_name` also appears in migration files —
> `core/migrations/0001_initial.py:36`, `0004_…` and `0010_…` all carry
> `'verbose_name': 'Заявка'`. Migrations are append-only history that this repo
> commits and never rewrites. A `file:line` pointing at one is a damaging
> suggestion, not a copy fix. Editing `models.py` is the fix; the migration
> Django then generates records it.

**Form labels:**

```bash
git grep -n -E "label\s*=|help_text\s*=" -- '*/forms.py'
```

### Ranking what comes back

160 `verbose_name`s will drown six real findings if you list them flat. Rank by
whether a user meets the string:

1. **Toasts and validation errors** — the app speaking directly to someone
   mid-task. Always top.
2. **Buttons, headings, empty states** — read on every visit.
3. **`verbose_name` that surfaces** in a table header or a crispy form label.
4. **`verbose_name` that only ever renders in Django admin.** Note in passing;
   do not spend a finding on it.

Only 1–3 belong in the findings list. Pass 2 is what separates tier 3 from tier
4 — but it captures a dozen screens, not 160 strings, so most `verbose_name`s
will end the run unclassified.

**Leave them unclassified and out of the findings list.** Do not guess a tier
from the field name: a report of 150 speculative rows buries the six real
findings, which is the specific failure this ranking exists to prevent. Say in
the report how many were left unranked, and move on.

## Pass 2 — the rendered pass

Use the `run-price-manager` driver. Commands: `launch nav wait-for screenshot
viewport click fill press text eval url sleep console login quit`. `screenshot`
is always `fullPage`.

`ui-review`'s screen catalogue and its pk-scraping recipe apply unchanged — reuse
them rather than re-deriving. **What differs is that two of this skill's four
surfaces are not reachable by navigation at all**, and neither is in that
catalogue.

> **The two heredocs below are untested starting points, not verified recipes.**
> Everything else in this skill was checked against source on 2026-09-06; these
> were not, because Docker was down when it was written. In particular `press
> Enter` assumes Enter reaches a submit button that HTMX has not intercepted, and
> `htmx-modal-crud` forms post via HTMX. If a recipe does not produce a toast,
> **suspect the recipe before the app**: read the form back with `text
> #modal-container .modal-content`, find the real submit control, and
> `click` it instead. Replace this note with a verified date once you have run
> them.

### Toasts must be provoked

`core/middleware.py:90` (`toaster_middleware`) fires a `toasts:fetch` client
event `after="settle"` whenever the response carries messages, and
`core/templates/core/partials/toast_messages.html` renders them. Consequence: a
toast is **never** on the page at `nav` time. You have to perform the action.

Pick actions that are safe to repeat and cheap to undo — creating and deleting a
корзина is the ideal pair, and it exercises three of the 26 strings:

```
nav /shopping-tabs/
sleep 1000
click [data-bs-target="#modal-container"]
sleep 1200
fill #id_name copy-pass-throwaway
press Enter
sleep 1500
text .toast-body
screenshot t1-toast-create
```

**Do not provoke a toast by starting real work.** «Обновить» on Главный прайс
(`/mainproduct/sync`) starts a PIM sync against the external API, and a copy pass
is not worth a live sync. `ui-review` documents the same hazard for the same
button.

Read the toast with `text .toast-body` as well as shooting it — Bootstrap toasts
auto-dismiss, and the text is the artifact you need, not the pixels.

### Validation errors need a failed submit

Submit a form empty and read what comes back:

```
nav /supplier/create/
sleep 800
press Enter
sleep 1000
text form
screenshot t2-validation-empty
```

Django's own field errors are Russian (`LANGUAGE_CODE = 'ru'` supplies them);
your findings are about the *labels and help text around them*, which are the
repo's own strings.

Finish with `console --errors`, same as `ui-review`.

## Reconcile — the finding classes

Each class below was found in this repo. **Line numbers verified 2026-09-06** —
re-check before quoting one, since the point of the skill is to get them fixed.

**1. Terminology split — one decision, N sites.** The flagship class, and the one
a per-screen review structurally cannot see. `ShoppingTab` is called **«Заявка»**
in the model (`core/models.py:62`), the nav
(`core/templates/includes/header.html:19`), and the breadcrumbs and title
(`core/templates/shopping_tab/detail.html:3,12,21`) — and **«Корзина»** in the
toasts (`core/views.py:155,164,212`), the add button in `base.html`, the modals,
and `main/instructions.html`. A user adds to a корзина and lands on a заявка.

Report this as **one finding**: the decision (which word wins) plus a mechanical
edit list. Do not file nine findings that share a cause — the same collapsing
`ui-review` applies to the BS5 mismatch.

**2. Errors that say nothing.** `messages.error(self.request, 'Ошибка')` at
`product_price_manager/views.py:113, 237, 273` — three of the app's 26 messages
are the bare word "Error". Also `'Что-то пошло не так'`. An error naming neither
what failed nor what to do next is a dead end.

**3. Model names leaking into UI.** `'Менеджер добавлен'` at
`product_price_manager/views.py:141, 257, 296` — «Менеджер» is the `PriceManager`
class; the screens call these **«Наценки»**. The user is told an object they have
never heard of was added.

**4. Typos.** `supplier_product_manager/views.py:326` —
`'Неоднозначная связь: Столбец\знаение'`: `знаение` → `значение`, and the whole
string is an internal concept shown to a user.

**5. Punctuation and casing drift.** The same sentence, two files, one period:
`supplier_manager/views.py:173` has `'Настройки поставщика сохранены.'`,
`supplier_product_manager/views.py:68` has `'Настройки поставщика сохранены'`.
Pick one convention for the app and list the exceptions.

**6. English strings in a Russian UI.**
`core/templates/core/partials/toast_messages.html:10` carries
`aria-label="Close"` — on the dismiss button of **every toast in the app**, so it
is what a Russian screen-reader user hears each time. → `aria-label="Закрыть"`.

## Traps

**A string in a template nobody renders is not a finding.**
`core/templates/core/includes/paginated_table_htmx.html:44` holds a
`{% blocktranslate %}` emitting English `{{ current_position }} of {{ total }}` —
which looks like a perfect finding and is worthless: `git grep -l
paginated_table_htmx` returns **nothing**. The template is dead. Confirm a
template is included or rendered by a view before filing anything about it.

**There is no translation layer, so the fix is always a direct edit.**
`USE_I18N = True` and `LANGUAGE_CODE = 'ru'` (`settings/base.py:66,70`), but the
repo has **no `locale/` directory** and exactly one `{% blocktranslate %}` — the
dead one above. Strings are hardcoded Russian. Never propose `.po` files,
`gettext` wrapping, or a translation workflow; that is a project, not a copy fix.

**Cramped or wrapped labels may be the Bootstrap split, not the words.** Before
recommending a shorter string because it overflows, count on that screen:

```
eval document.querySelectorAll('.custom-select, .form-row, .form-control-file').length
```

Nonzero means BS4 markup in a BS5 stylesheet — CLAUDE.md owns the explanation.
Zero means the layout is fine and the copy really is too long.

**The retiring five have no UI worth reviewing.** `product`, `pricing`,
`supplier`, `supplier_feed`, `dataframe` are API-only. Their 39 `verbose_name`s
are noise here — exclude them, and do not confuse `supplier` with the live
`supplier_manager`.

## Handing off to `design:ux-copy`

If `design:ux-copy` is available in this session, give it the reconciled
inventory — the strings, where each renders, and the screenshots. Tell it
explicitly, in the prompt, that **the UI language is Russian and every suggested
replacement must be written in Russian**; an English suggestion cannot be pasted
into a template and is noise.

That skill is served by the session, not installed in this repo, so a plain
terminal session may not have it. If it is absent, do the pass inline against the
six classes above rather than stopping.

## Report

Write `ux-copy-<YYYY-MM-DD>.md` to the scratchpad and send it with
`SendUserFile`, along with any screenshot that carries an argument.

Every finding is a table row, and the row is the fix:

| Где | Сейчас | Предлагается | Почему |
|---|---|---|---|
| `product_price_manager/views.py:113` | `Ошибка` | `Не удалось сохранить наценку` | Не говорит ни что упало, ни что делать дальше |

Rules that make the report usable:

- **`file:line`, always** — the fix should be a two-minute edit, not a search.
- **Suggestions in Russian.** No exceptions. Same rule `ui-review` carries.
- **Terminology findings get one row for the decision** plus an indented edit
  list, not one row per site.
- **Rank by whether the string blocks or misleads someone**, not by how much it
  offends you.
- Close with **Не заведено** — state plainly that nothing was written to the
  tracker, and offer to route the promising ones through `/triage` or
  `tg-tracker`.

## Do not

- **Do not file GitHub issues from this skill.** Creation belongs to `tg-tracker`
  and `/triage`, which carry the duplicate search and the audit trail.
  `ui-review` holds the same line for the same reason: two systems creating
  issues with different dedup behaviour is how a tracker fills with stale
  duplicates.
- **Do not edit templates, views or models during the pass.** The temptation is
  sharper here than in `ui-review` — a copy fix is one word — but capture and
  critique are one job and fixing is another. The report's paste-ready rows are
  the deliverable; `/implement-issue` or an ordinary session applies them.
- **Do not edit migrations.** See pass 1.
- **Do not `docker compose down -v`.** It deletes `postgres_data`. A `PreToolUse`
  hook guards this; do not work around it.
- **Do not leave throwaway rows behind.** A корзина created to provoke a toast
  gets deleted in the same run — which conveniently photographs the delete toast
  too.

$ARGUMENTS
