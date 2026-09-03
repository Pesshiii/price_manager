---
name: record-insight
description: Hand a newly-learned fact about a Django app to that app's knowledge keeper, so the next session starts with it. Use after working in an app and discovering something non-obvious.
disable-model-invocation: true
---

# Record an insight

Take what was learned in this session about one app and get it merged into that
app's knowledge file by its keeper agent. **You do not write the knowledge file
yourself** — the keeper owns it, dedupes against what is already there, and
prunes what the change disproved.

## Which keeper

| App | Agent | Knowledge file |
|---|---|---|
| `main_product_manager` | `main-product-keeper` | `.claude/knowledge/main_product_manager.md` |
| `core` | `core-keeper` | `.claude/knowledge/core.md` |
| `product` | `product-keeper` | `.claude/knowledge/product.md` |
| `supplier_product_manager` | `supplier-product-keeper` | `.claude/knowledge/supplier_product_manager.md` |
| `supplier_manager` | `supplier-manager-keeper` | `.claude/knowledge/supplier_manager.md` |
| `product_price_manager` | `price-rules-keeper` | `.claude/knowledge/product_price_manager.md` |
| `pricing`, `supplier`, `supplier_feed`, `dataframe` | `retiring-stack-keeper` | `.claude/knowledge/retiring_stack.md` |

Apps with no keeper (`file_manager`, `api_auth`, `pim_api`, `blogapp`) are too
small to carry one. If something there genuinely matters, it belongs in
`CLAUDE.md`, not in a new knowledge file.

## Steps

1. **Work out the insight.** If `$ARGUMENTS` named an app but not a fact, look
   back over what actually happened this session in that app: what surprised
   you, what you got wrong the first time, what took more than one attempt.
   That is the material. If nothing did, say so and stop — an empty record is
   better than a padded one.

2. **Filter it before passing it on.** Drop anything that is:
   - already in `CLAUDE.md` or `AGENTS.md` (they own repo-wide invariants),
   - answerable by a five-second grep,
   - narration of this session rather than a fact about the code,
   - a preference about how to work rather than a fact about the app.

3. **Dispatch to the keeper** with the Agent tool, telling it to RECORD. Give it
   the insight, the `file:line` evidence, and how you found out. Example:

   > RECORD this in your knowledge file: `Setting.is_bound()` is not read-only —
   > it rewrites `Link`s with `value=''` to `None` before validating
   > (`supplier_product_manager/models.py:133`). Found when a read-only
   > readiness check produced writes in the query log.

4. **Report what changed.** Name the file the keeper updated and summarise the
   edit in a line, so the diff is not a surprise at commit time.

## If several apps were touched

One dispatch per app, each with only that app's insight. Do not send the same
fact to two keepers — put it where it belongs and let the other file link to it
with `[[app_name]]`.

$ARGUMENTS
