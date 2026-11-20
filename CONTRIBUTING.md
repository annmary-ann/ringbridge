# Contributing to Ringbridge

Thanks for your interest. Ringbridge is early, so design feedback is as valuable as code.

## Ways to help

- Comment on the [architecture](docs/architecture.md) or an [ADR](docs/adr/).
- Pick an issue labelled `good first issue` or `help wanted`.
- Build a connector for your calendar, CRM or messaging provider (see ADR-0007).
- Add simulation scenarios in your language.

## Workflow

1. Comment on the issue so nobody duplicates work.
2. Branch from `main`: `feat/<issue>-short-slug`, `fix/<issue>-...`, `docs/<issue>-...`.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:` ...).
4. Sign off every commit (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/).
5. Open a PR that says `Closes #<issue>`. CI must pass. PRs are squash-merged.

Changing an architectural boundary? Add or update an ADR in the same PR.

## Development setup

Requirements: [uv](https://docs.astral.sh/uv/) and Docker. uv installs Python 3.12 for you.

```sh
uv sync                 # create .venv with every workspace package (editable) + dev tools
uv run poe check        # lint, strict type check, tests: the same as CI
uv run poe hooks        # optional: install pre-commit hooks
uv run ringbridge --version
```

Layout: one uv workspace, one package per folder in `packages/` (`ringbridge-core`, `-agent`, `-server`, `-connectors`, `-sim`, `-cli`), each with `src/` and `tests/`. See [ADR-0004](docs/adr/0004-python-uv-monorepo.md).

**Windows with Smart App Control:** it can block the `.exe` shims uv creates (`poe.exe`, `mypy`). Run tasks as `uv run python -m poethepoet <task>`, and type-check in Linux with `uv run python -m poethepoet typecheck-docker`.

Start the local Docker stack (LiveKit, Redis, Postgres, S3, Jaeger) with `uv run poe up` and check it with `uv run poe smoke`. Details and ports: [docs/dev-stack.md](docs/dev-stack.md).

## Conduct

Be kind and assume good intent. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
