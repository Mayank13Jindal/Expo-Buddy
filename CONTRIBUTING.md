# Contributing to Expo Buddy

Keep changes small and preserve originals, manual corrections and unsynced phone
captures. Use fictional records in issues, screenshots, tests and pull requests.
Include a focused regression test for behavior changes.

## Development

The Docker quick start in README runs the app. For host-side development tools,
install Python 3.12, Node 24.19+ (below 25, see `frontend/.nvmrc`; npm refuses other
versions), `uv` and `make`, then:

```sh
make dev-install
make test
```

The backend uses FastAPI/SQLAlchemy/Alembic; the frontend uses React/TypeScript.
Pinned Python dependencies include hashes. Regenerate the relevant lockfiles when
you change dependencies, and check their licenses. `make openapi` regenerates
OpenAPI and TypeScript types against a running stack. Never hand-edit a migration
already used by others; add a new one.

## Tests

```sh
make lint
make test-backend
make test-frontend
cd frontend && npm run build
```

`make lint` also runs ESLint and the Prettier check on the frontend. Run `make format`
to format frontend code before you commit. To hide the one-time formatting commit from
`git blame`, run `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

GitHub Actions runs these checks without starting a live provider or handling real
credentials. The Stack workflow also builds the Docker stack with password sign-in,
then runs the integration tests and the browser tests against it. It runs on pull
requests, pushes to `main` and on demand. Integration tests (`make test-integration`) require a running stack.
Browser tests (`make e2e`) create, edit and delete data: use a separate disposable
installation with password access enabled and the fictional test password from
the test files. Never aim them at your personal collection.

The optional review/findings/grouping fixtures in `frontend/tests/e2e/fixtures`
require `EXPO_SYNTHETIC_AUDIT=1`. Their browser specs also require explicit
`AUDIT_*_FIXTURES` environment flags. The restart spec additionally expects a
separate Compose project `expo-buddy-audit` configured through `.local/audit/.env`;
it stops and restarts that test API. Ordinary CI excludes these live browser tests.

For UI changes, check keyboard navigation, loading/failure/empty states and
320px/390px widths as well as desktop. For extraction changes, check uncertain
multi-person associations and that retrying preserves manual corrections.
For storage/recovery changes, practice a restore into a new database and clean
marked storage; do not overwrite a working database to run a test.

## Keeping dependencies current

Dependabot opens grouped pull requests once a month for GitHub Actions, the
frontend (npm) and the Docker images. CI, including the full Stack run, checks
each one; merge it when it is green. Major npm updates come as separate pull
requests. Node stays on 24.x and Python on 3.12 until you change them on purpose.

Python lockfiles are hashed `uv pip compile` output, which Dependabot cannot
regenerate. To refresh their indirect dependencies, run `make lock-upgrade`,
then `make test` and open a pull request. To change a direct dependency, edit its
pin in `backend/pyproject.toml` first. GitHub security alerts cover the Python
lockfiles too, so enable Dependabot alerts in the repository settings.

## Pull requests

Explain the problem, resulting behavior and checks run. Add screenshots when they
help assess a visible change. Describe any migration or compatibility impact.
Avoid committing `.env`, `.secrets`, `.local`, model weights, browser state,
real captures, exports, logs or certificates. See [publishing checks](docs/github.md).
