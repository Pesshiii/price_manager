# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Price Manager** is a Django Rest based web application for managing product prices, stock levels, and supplier information. It integrates supplier product catalogs, calculates dynamic pricing rules, and maintains a centralized product database with price history tracking.

## Development Commands

### Repo layout

The Django project lives in the nested `price_manager/` directory (one level below the repo root). `manage.py`, `requirements.txt`, and all apps are there. **Run every `python manage.py …` / `celery …` / `pip install` command from inside `price_manager/`.**

### Local Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Tests

Docker is used for testing

```bash
python manage.py test                              # all tests
python manage.py test core                         # single app
python manage.py test core.tests.MyTestClass       # single class
python manage.py test product.tests.test_import    # single module (new layout)
```
Test layout is mixed: most apps use a single `tests.py`; the `product` app uses a `tests/` package — `test_api_crud.py`, `test_api_filters.py`, `test_import.py`, `test_import_async.py` (covers `run_import_commit` Celery task + `ImportJob` stage transitions), `test_import_dynamic_chars.py` (EAV dynamic-characteristics behavior), `test_models.py`, plus `fixtures.py` (shared test helpers — not a test module).

### Migrations
```bash
python manage.py makemigrations app_name
python manage.py migrate
```

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`github.com/Pesshiii/price_manager`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Multi-context repo — `CONTEXT-MAP.md` at the root points to the backend (`CONTEXT.md`) and frontend (`frontend/CONTEXT.md`) contexts; system-wide ADRs in `docs/adr/`. See `docs/agents/domain.md`.