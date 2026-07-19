# Testing Policy

## Rule (overrides default "no tests unless asked")

**After every functional or UI change, write tests.** No exceptions.

This applies to:
- New routes or endpoints
- Modified route behavior (new params, changed response)
- Template changes that depend on backend logic (forms, HTMX interactions)
- New or modified services
- Bug fixes (regression test for the fixed bug)

## What to test

| Change type | Required test |
|-------------|---------------|
| New/modified API endpoint | Request → response status + body assertion |
| Template with form (HTMX) | POST endpoint with form data → correct response |
| Service function | Unit test with mocked DB |
| Bug fix | Test that reproduces the bug pre-fix |
| New model/migration | Model creation + query test |

## How to write

- Use existing test patterns from `tests/` directory
- pytest + httpx AsyncClient for route tests
- Fixtures from `tests/conftest.py`
- Keep tests fast (mock external services, no real LLM/Reddit calls)
- File naming: `tests/test_<module>.py` matching `app/routes/<module>.py` or `app/services/<module>.py`

## CI integration

Tests must pass locally before suggesting deploy:
```bash
pytest tests/ -x -q --timeout=30 --ignore=tests/test_geo_monitoring.py -k "not hypothesis"
```

## Why

Regression rate increased in June-July 2026. Every untested change is a liability for the next deploy. Tests are the gate that prevents broken code from reaching production.
