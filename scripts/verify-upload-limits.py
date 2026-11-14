#!/usr/bin/env python3
"""Opt-in test for the disposable localhost stack after browser tests.

Creates fictional records and uploads 500 MiB of generated files. Never use on a real library.
Uses only the fake browser-test account; never prompts for production credentials.
"""

import hashlib
import io
import json
from pathlib import Path

import httpx
from PIL import Image, ImageDraw
from storage_config import read_env

config = read_env(Path(".env"))
if (
    config.get("APP_URL") != "https://localhost:8443"
    or config.get("ALLOW_SHARED_BACKUP_DISK") != "true"
):
    raise SystemExit(
        "This check runs only against the disposable localhost development configuration."
    )
folder = Path(".local/large-files")
folder.mkdir(exist_ok=True)
image = folder / "FAKE-LARGE-IMAGE.jpg"
picture = Image.new("RGB", (1000, 600), "white")
ImageDraw.Draw(picture).text(
    (30, 60), "FICTIONAL CARD - LARGE UPLOAD TEST ONLY", fill="black"
)
picture.save(image)
with image.open("ab") as stream:
    stream.truncate(100 * 1024**2)
pdf = folder / "FAKE-LARGE-PDF.pdf"
content = b"BT /F1 16 Tf 35 700 Td (FICTIONAL BROCHURE - LARGE UPLOAD TEST ONLY. Makes example solar structures.) Tj ET"
objects = [
    b"<< /Type /Catalog /Pages 2 0 R >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /Contents 4 0 R >>",
    b"<< /Length "
    + str(len(content)).encode()
    + b" >>\nstream\n"
    + content
    + b"\nendstream",
]
prefix = b"%PDF-1.4\n"
offsets = [0]
for i, obj in enumerate(objects, 1):
    offsets.append(len(prefix))
    prefix += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
offsets.append(len(prefix))
padding = 400 * 1024**2 - len(prefix) - 400
for _ in range(10):
    header = f"5 0 obj\n<< /Length {padding} >>\nstream\n".encode()
    end = b"\nendstream\nendobj\n"
    xref = len(prefix) + len(header) + padding + len(end)
    suffix = (
        end
        + b"xref\n0 6\n0000000000 65535 f \n"
        + b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    new = 400 * 1024**2 - len(prefix) - len(header) - len(suffix)
    if new == padding:
        break
    padding = new
with pdf.open("wb") as stream:
    stream.write(prefix + header)
    chunk = b"0" * 1024**2
    remaining = padding
    while remaining:
        block = chunk[: min(remaining, len(chunk))]
        stream.write(block)
        remaining -= len(block)
    stream.write(suffix)
assert pdf.stat().st_size == 400 * 1024**2


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024**2):
            result.update(block)
    return result.hexdigest()


ca = str(Path(".secrets/caddy-data/caddy/pki/authorities/local/root.crt"))
results = []
with httpx.Client(
    base_url="https://localhost:8443",
    verify=ca,
    trust_env=False,
    timeout=1200,
    headers={"Origin": "https://localhost:8443"},
) as web:
    web.post(
        "/api/v1/auth/login", json={"password": "fake-e2e-password-123"}
    ).raise_for_status()
    web.headers["X-CSRF-Token"] = web.cookies["expo_csrf"]
    expo = web.post(
        "/api/v1/expos", json={"name": "FICTIONAL large-file gateway acceptance"}
    ).json()["id"]
    session = web.post("/api/v1/upload-sessions", json={"expo_id": expo}).json()["id"]
    for path, mime in ((image, "image/jpeg"), (pdf, "application/pdf")):
        sha = digest(path)
        with path.open("rb") as stream:
            response = web.post(
                f"/api/v1/upload-sessions/{session}/files",
                files={"file": (path.name, stream, mime)},
                data={"sha256": sha},
            )
        assert response.status_code == 201, (response.status_code, response.text)
        saved = response.json()
        assert (
            saved["status"] == "saved"
            and saved["asset"]["bytes"] == path.stat().st_size
        )
        actual = hashlib.sha256()
        with web.stream(
            "GET", "/api/v1/assets/" + saved["asset"]["id"] + "/original"
        ) as download:
            download.raise_for_status()
            for block in download.iter_bytes(1024**2):
                actual.update(block)
        assert actual.hexdigest() == sha
        results.append(
            {
                "file": path.name,
                "bytes": path.stat().st_size,
                "upload": 201,
                "download_sha256_matches": True,
            }
        )

    # One byte above each image/PDF limit: streamed, without another large temporary copy.
    class ExtraByte(io.RawIOBase):
        def __init__(self, path):
            self.source = path.open("rb")
            self.extra = False

        def read(self, size=-1):
            data = self.source.read(size)
            if data:
                return data
            if not self.extra:
                self.extra = True
                return b"0"
            return b""

        def seek(self, *args):
            raise io.UnsupportedOperation()

        def close(self):
            self.source.close()
            super().close()

    for path, mime in ((image, "image/jpeg"), (pdf, "application/pdf")):
        stream = ExtraByte(path)
        try:
            response = web.post(
                f"/api/v1/upload-sessions/{session}/files",
                files={"file": (path.name, stream, mime)},
            )
        finally:
            stream.close()
        assert response.status_code == 413, (response.status_code, response.text)
        results.append(
            {"file": path.name, "bytes": path.stat().st_size + 1, "rejected": 413}
        )
Path(".local/large-file-results.json").write_text(json.dumps(results, indent=2))
for path in (image, pdf):
    path.unlink()
print(
    "Real trusted-HTTPS gateway checks passed: 100 MiB image and 400 MiB PDF saved and downloaded with matching SHA-256; one byte above each limit rejected."
)
