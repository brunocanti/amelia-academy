# Contributing

Thanks for your interest. Issues and pull requests are welcome.

## Set up

Follow "Install and run" in the [README](README.md). Always run Python through the project venv (`app/backend/.venv`, `app/trainer/.venv`).

## Before you open a pull request

- Backend tests pass: `cd app/backend && PYTHONPATH=. .venv/bin/pytest -q`
- The UI builds: `cd app/ui && npm run build`
- Keep pull requests small and focused on one change.

## Product rules

Read the premise in the README ("The hard part stays underneath"). Before you ship a screen, ask: would someone who has never seen Amelia know what to click without reading an explanation?

- Generated content starts as a proposal. Only a person's click changes its status.
- Model failures are shown. There is no silent fallback to another model.
- External models run only through their tool's CLI, never through a direct API call (`docs/adr/017-external-models-through-the-tool-cli.md`).

## Design records

- A change in architecture gets a new ADR in `docs/adr/`.
- A new feature gets a spec in `docs/specs/`.
- `docs/architecture/estado-atual.md` describes what exists today. Update it when that changes.

Docs may be written in Portuguese or English.

## License

By contributing, you agree that your contribution is licensed under the MIT License of this project.
