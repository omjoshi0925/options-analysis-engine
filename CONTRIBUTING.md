# Contributing

This project values verifiable numbers over feature count, so contributions
are judged on evidence. Thanks for taking the time.

## Setup

```bash
make venv && make test && make lint
```

## Ground rules

- Every numerical routine ships with an independent check: a published
  reference value, a closed form, quadrature, a simulation with a standard
  error, or a limiting case. A round trip alone is not enough.
- Market data are never fabricated. Tests use deterministic fixtures and the
  labelled synthetic demonstration; nothing in the repository may claim
  observed accuracy or a market-trained model.
- Credentials stay in the environment. Configs, logs, snapshots, and failure
  diagnostics must not contain tokens; `LiveConfig` rejects unknown keys for
  that reason.
- Existing definitions keep their meaning. Add columns and report sections
  rather than redefining error, MAE, within-spread rates, or the training
  target.
- Keep the compact style: small modules with one responsibility, explicit
  units in docstrings, and a clean `ruff check .`.

## Workflow

1. Open an issue describing the change and how it will be verified.
2. Branch from `main`. For numerical changes, add the failing test first.
3. Run `make test` and `make lint`. CI runs both on Python 3.10, 3.12, and 3.13.
4. Update `docs/METHODOLOGY.md` or `docs/LEARNING.md` when behaviour or a
   definition changes, and add a line to `CHANGELOG.md`.
5. Open a pull request using the template.

## Reporting a provider problem

Attach the failure record from `data/live/failures/` after removing any path
you consider private. Failure records never contain tokens or response
bodies. Say which provider, which configuration values, and what the
collector status reported.
