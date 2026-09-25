---
name: record-insight
description: Hand a newly-learned fact about a Django app to that app's knowledge keeper, so the next session starts with it. Use after working in an app and discovering something non-obvious.
disable-model-invocation: true
---

# Record an insight

Take what was learned in this session about one app and get it merged into that
app's knowledge directory by its keeper agent. **You do not write the topics
yourself** — the keeper owns them, picks the topic the fact belongs in (or
starts a new one), dedupes against what is already there, and prunes what the
change disproved. You do the one thing the keeper cannot: it has no shell, so
**you regenerate the index** afterwards.

## Layout

`.claude/knowledge/<app>/` holds one markdown file per topic, each with front
matter (`title`, `summary`, `code`), plus a generated `README.md` listing them.
`.claude/knowledge/README.md` is the generated top-level index,
`.claude/knowledge/glossary.md` the hand-written map of Russian UI terms to
code. Links between topics are `[[app]]` and `[[app/topic]]`.

## Which keeper

| App | Agent | Knowledge directory |
|---|---|---|
| `main_product_manager` | `main-product-keeper` | `.claude/knowledge/main_product_manager/` |
| `core` | `core-keeper` | `.claude/knowledge/core/` |
| `product` | `product-keeper` | `.claude/knowledge/product/` |
| `supplier_product_manager` | `supplier-product-keeper` | `.claude/knowledge/supplier_product_manager/` |
| `supplier_manager` | `supplier-manager-keeper` | `.claude/knowledge/supplier_manager/` |
| `product_price_manager` | `price-rules-keeper` | `.claude/knowledge/product_price_manager/` |
| `pricing`, `supplier`, `supplier_feed`, `dataframe` | `retiring-stack-keeper` | `.claude/knowledge/retiring_stack/` |

Apps with no keeper (`file_manager`, `api_auth`, `pim_api`, `blogapp`) are too
small to carry one. If something there genuinely matters, it belongs in
`CLAUDE.md`, not in a new knowledge directory.

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
   the insight, the `file:line` evidence, and how you found out. If you already
   know which topic it belongs in — the app's `README.md` lists them — name it;
   otherwise let the keeper choose or start one. A Russian UI term that turned
   out to mean something specific in code goes to the glossary too; say so.
   Example:

   > RECORD this in your knowledge directory (topic `import-config` looks
   > right): `Setting.is_bound()` is not read-only — it rewrites `Link`s with
   > `value=''` to `None` before validating
   > (`supplier_product_manager/models.py:133`). Found when a read-only
   > readiness check produced writes in the query log.

   Working in a git worktree? Give the keeper the worktree's absolute path to
   the knowledge directory — otherwise it edits the main checkout.

4. **Regenerate and check the index**, from the repo (or worktree) root:

   ```bash
   python .claude/tools/knowledge_index.py
   python .claude/tools/knowledge_index.py --check
   ```

   The first rewrites any README the keeper's edit made stale; the second must
   exit 0. It fails on a topic without front matter and on a `[[link]]` that
   points nowhere (a renamed or split topic whose links were not fixed) — send
   that back to the keeper. A `code path … does not exist` warning means the
   keeper's front matter names a file that moved; ask it to fix the `code` line.
   CI runs `--check`, so a stale README fails the PR.

5. **Report what changed.** Name the topics the keeper created or updated and
   summarise each edit in a line, so the diff is not a surprise at commit time.

## If several apps were touched

One dispatch per app, each with only that app's insight. Do not send the same
fact to two keepers — put it where it belongs and let the other app's topic
link to it with `[[app/topic]]`. Keepers can run in parallel; regenerate the
index once, after the last one returns.

$ARGUMENTS
