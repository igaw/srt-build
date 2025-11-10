# srt-build

tooling to build RT test kernels with Lava.

## Development

Quickstart:

1. Create a virtualenv and install dev tools:
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt

2. Format and lint:
   black .
   ruff check .

3. Run tests:
   pytest -q

The CI pipeline runs linting, formatting checks and the smoke tests on each PR.
