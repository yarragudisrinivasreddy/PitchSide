# Contributing to PitchSide

Thank you for your interest in improving PitchSide.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pre-commit install
```

## Quality gates

Every change must keep all gates green before a pull request:

```bash
python -m pytest -q --cov=app       # all tests pass, coverage >= 95%
python -m pylint app/ tests/        # 10.00 target, no new messages
python -m radon cc app/ -n C        # no C-grade complexity
python -m mypy app/                 # no type errors
```

## Design rules

1. **Gemini interprets, the graph computes.** Generative output must never
   contain invented numbers; all figures come from `app/domain/` modules.
2. Services degrade gracefully: every Google client call path must survive
   missing credentials via typed `UPSTREAM_FAILURES` handling.
3. Security headers live in the `after_request` hook only — never add
   `before_request` origin validation.
4. Keep routes thin; put logic in `app/services/assistant.py` or the domain.
