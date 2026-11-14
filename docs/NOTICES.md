# Open-source notices

Dependency versions were pinned on 28 October 2026. The authoritative, complete version and hash records are `backend/requirements.lock`, `backend/requirements-worker.lock`, `backend/requirements-dev.lock`, `frontend/package-lock.json`, `models.lock.json` and image references in the Dockerfiles/Compose file. This inventory describes the main components; their installed distributions retain upstream copyright, licence and bundled-library notices. Preserve those notices when redistributing images. No upstream copyright ownership is claimed for this project.

## Application dependencies

| Component | Pinned version | Licence / source |
|---|---|---|
| FastAPI | 0.162.0 | [MIT](https://github.com/fastapi/fastapi) |
| Uvicorn | 0.54.0 | [BSD-3-Clause](https://github.com/Kludex/uvicorn) |
| Pydantic / pydantic-settings | 2.14.1 / 2.16.2 | [MIT](https://github.com/pydantic/pydantic) |
| SQLAlchemy / Alembic | 2.0.55 / 1.20.1 | [MIT](https://github.com/sqlalchemy/sqlalchemy) |
| psycopg | 3.3.6 | [LGPL-3.0-only](https://github.com/psycopg/psycopg) |
| cryptography | 50.0.2 | [Apache-2.0 OR BSD-3-Clause](https://github.com/pyca/cryptography) |
| argon2-cffi | 25.1.0 | [MIT](https://github.com/hynek/argon2-cffi) |
| Pillow | 13.0.0 | [MIT-CMU, with bundled-library notices](https://github.com/python-pillow/Pillow) |
| pillow-heif | 1.8.1 | [BSD-3-Clause](https://github.com/bigcat88/pillow_heif); bundled libheif has its own LGPL notices |
| pypdf | 6.21.3 | [BSD-3-Clause](https://github.com/py-pdf/pypdf) |
| pypdfium2 | 5.14.0 | [BSD-3-Clause / Apache-2.0 and PDFium dependency notices](https://github.com/pypdfium2-team/pypdfium2) |
| openpyxl | 3.1.5 | [MIT](https://foss.heptapod.net/openpyxl/openpyxl) |
| PyJWT | 2.15.1 | [MIT](https://github.com/jpadilla/pyjwt) |
| Official MCP Python SDK | 2.3.0 | [MIT](https://github.com/modelcontextprotocol/python-sdk) |
| tzdata | 2026.6 | [Apache-2.0; IANA timezone data notices](https://github.com/python/tzdata) |
| PaddlePaddle / PaddleOCR / PaddleX | 3.3.1 / 3.7.0 / 3.7.2 | [Apache-2.0](https://github.com/PaddlePaddle/PaddleOCR) |
| CPU PyTorch | 2.9.1+cpu | [BSD-3-Clause and bundled-library notices](https://github.com/pytorch/pytorch) |
| sentence-transformers | 6.2.0 | [Apache-2.0](https://github.com/huggingface/sentence-transformers) |
| transformers / tokenizers | 5.21.0 / 0.23.3 | [Apache-2.0](https://github.com/huggingface/transformers) |
| ImageHash | 4.3.2 | [BSD-2-Clause](https://github.com/JohannesBuchner/imagehash) |
| OpenCV headless | 4.10.0.84 | [Apache-2.0 and bundled-library notices](https://github.com/opencv/opencv-python) |
| React / React DOM | 19.3.1 | [MIT](https://github.com/facebook/react) |
| React Router | 7.18.5 | [MIT](https://github.com/remix-run/react-router) |
| TanStack Query / Table | 5.105.0 / 8.21.3 | [MIT](https://github.com/TanStack) |
| Radix Dialog / Tooltip | 1.3.1 / 1.4.1 | [MIT](https://github.com/radix-ui/primitives) |
| cmdk | 1.1.1 | [MIT](https://github.com/pacocoursey/cmdk) |
| hash-wasm | 4.12.0 | [MIT](https://github.com/Daninet/hash-wasm) |
| idb | 8.0.4 | [ISC](https://github.com/jakearchibald/idb) |
| Lucide React icons | 1.63.0 | [ISC](https://github.com/lucide-icons/lucide) |
| PDF.js | 6.4.299 | [Apache-2.0](https://github.com/mozilla/pdf.js) |
| PhotoSwipe | 5.4.4 | [MIT](https://github.com/dimsemenov/PhotoSwipe) |
| Workbox | 7.4.1 | [MIT](https://github.com/GoogleChrome/workbox) |
| Vite / vite-plugin-pwa | 8.3.5 / 2.0.0 | [MIT](https://github.com/vite-pwa/vite-plugin-pwa) |
| Tailwind CSS | 4.3.3 | [MIT](https://github.com/tailwindlabs/tailwindcss) |

HTTP, validation, numerical and test dependencies are included in the lockfiles and [dependency inventory](dependency-inventory.json). Test/build tools include pytest, Ruff, Vitest, TypeScript, Playwright, fake-indexeddb and ReportLab. Browser binaries, Python/Node runtimes, Debian/Alpine packages and native libraries retain their own licences. Pillow's embedded default font and ReportLab's bundled fonts retain their distribution notices; fictional samples use these packaged fonts and generated artwork.

## Services and images

- [PostgreSQL 18.6](https://www.postgresql.org/about/licence/): PostgreSQL Licence. The `pg_dump` executable and its required shared libraries are copied from the exact pinned database image into the worker, retaining that image's upstream software terms.
- [pgvector 0.8.7](https://github.com/pgvector/pgvector): PostgreSQL Licence. `pg_trgm` is a PostgreSQL extension.
- [Caddy 2.11.7](https://github.com/caddyserver/caddy): Apache-2.0. Stock official build; no third-party DNS module is bundled.
- [Python 3.12.14](https://www.python.org/psf/license/): PSF and bundled notices. [Node 24.19.0](https://github.com/nodejs/node): MIT and bundled notices.

## Cached model weights

Model cards at the exact revisions below were checked for licence metadata on 29 October 2026. Downloaded weights stay in the configured model cache; none are copied into the source repository. Model files and their terms are separate from the libraries that execute them.

| Repository | Exact revision | Model-card licence |
|---|---|---|
| [PaddlePaddle/PP-OCRv5_mobile_det](https://huggingface.co/PaddlePaddle/PP-OCRv5_mobile_det) | `0d63e78e2b680928f6b1747d76a08db6e645efb7` | Apache-2.0 |
| [PaddlePaddle/en_PP-OCRv5_mobile_rec](https://huggingface.co/PaddlePaddle/en_PP-OCRv5_mobile_rec) | `267c36e24c331595590fe7bd72bde2436fd286f2` | Apache-2.0 |
| [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | Apache-2.0 |
| [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) | `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` | MIT |

The default English recognition model does not establish accuracy for every language/layout. No Ollama model, commercial model weights or ChatGPT credentials are redistributed. Owner-selected AI models carry their own terms.

## Reuse and generated material

The app integrates the named packages through their public APIs. MCP transport/lifespan integration follows the official SDK; the Hermes config example follows its public documentation. No existing card-scanner/CRM application or proprietary source was imported. App icons and example cards/PDFs are generated locally; sample records are entirely fictional.
