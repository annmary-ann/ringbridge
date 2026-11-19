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

Coming with M0 (#2–#4): `uv sync`, `docker compose up`, `uv run poe check`.

## Conduct

Be kind and assume good intent. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
