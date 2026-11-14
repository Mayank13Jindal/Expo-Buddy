# Contributing to Expo Buddy

Keep changes small and preserve originals, manual corrections and unsynced phone
captures. Use fictional records in issues, screenshots, tests and pull requests.
Include a focused regression test for behavior changes.

## Development

The Docker quick start in README runs the app. For host-side development tools,
install Python 3.12, Node 24.19+ (below 25), `uv` and `make`, then:

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

GitHub Actions runs these checks without starting a live provider or handling real
credentials. Integration tests (`make test-integration`) require a running stack.
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

## Pull requests

Explain the problem, resulting behavior and checks run. Add screenshots when they
help assess a visible change. Describe any migration or compatibility impact.
Avoid committing `.env`, `.secrets`, `.local`, model weights, browser state,
real captures, exports, logs or certificates. See [publishing checks](docs/github.md).
