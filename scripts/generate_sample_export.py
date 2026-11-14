#!/usr/bin/env python3
"""Generate fictional exports in isolation; never opens the configured library/database.

Run with .venv/bin/python scripts/generate_sample_export.py after make dev-install.
All source images, the PDF and records are generated in a temporary directory.
"""

import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import Settings
from app.core.storage import MARKER
from app.db.exports import Export
from app.db.library import Document, DocumentPage
from app.db.models import Base
from app.exports.package import build
from app.exports.schema import FIELDS
from app.main import create_app
from app.pipeline.ocr import read_document
from app.pipeline.prepare import prepare_document
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


def card(back=False):
    image = Image.new("RGB", (1050, 600), "#f5f4ef")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1050, 16), fill="#235947")
    lines = (
        [
            "FICTIONAL / SAMPLE ONLY",
            "Example Solar Structures",
            "Mira Example - Sales",
            "mira@example.invalid",
            "+91 00000 00001",
            "Fictional Solar Expo 2026",
        ]
        if not back
        else [
            "FICTIONAL / SAMPLE ONLY",
            "Card back",
            "Example solar mounting structures",
            "Illustration only; no real company or contact.",
        ]
    )
    for index, line in enumerate(lines):
        draw.text((45, 60 + index * 65), line, fill="#17392e", font_size=30)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def brochure():
    stream = io.BytesIO()
    canvas = Canvas(stream)
    for number in (1, 2):
        canvas.drawString(40, 760, f"FICTIONAL SAMPLE BROCHURE - PAGE {number}")
        canvas.drawString(
            40, 720, "Example Pumps - brochure-only company, no contact people."
        )
        canvas.drawString(
            40,
            680,
            "Makes fictional irrigation pumps. This is generated demonstration data.",
        )
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


def generate(folder):
    with TemporaryDirectory(prefix="expo-fictional-export-") as temporary:
        root = Path(temporary)
        values = {
            "app_url": "https://library.example.invalid",
            "assets_free_floor_bytes": 0,
        }
        for name in ("assets", "previews", "db", "models", "exports", "backup"):
            path, volume_id = root / name, uuid4()
            path.mkdir()
            (path / MARKER).write_text(str(volume_id))
            values[f"{name}_dir"], values[f"{name}_volume_id"] = path, volume_id
        for name, value in (
            ("database_password", "sample-only-" * 5),
            ("host_id", str(uuid4())),
            ("encryption_key", Fernet.generate_key().decode()),
        ):
            path = root / name
            path.write_text(value)
            values[f"{name}_file"] = path
        settings = Settings(**values)
        engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
        )

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        with TestClient(
            create_app(settings, engine=engine),
            base_url=settings.canonical_origin,
            headers={"Origin": settings.canonical_origin},
        ) as web:

            def request(method, path, **kwargs):
                response = web.request(method, "/api/v1" + path, **kwargs)
                response.raise_for_status()
                return response.json()

            request(
                "POST",
                "/auth/setup",
                json={"password": "fictional-sample-account-only"},
            )
            web.headers["X-CSRF-Token"] = web.cookies["expo_csrf"]
            expo = request(
                "POST", "/expos", json={"name": "FICTIONAL Solar Expo 2026"}
            )["id"]
            session = request("POST", "/upload-sessions", json={"expo_id": expo})["id"]

            def upload(name, content, mime):
                return request(
                    "POST",
                    f"/upload-sessions/{session}/files",
                    files={"file": (name, content, mime)},
                    data={"sha256": hashlib.sha256(content).hexdigest()},
                )["document"]["id"]

            front = upload("FICTIONAL-card-front.png", card(), "image/png")
            back = upload("FICTIONAL-card-back.png", card(True), "image/png")
            pdf = upload("FICTIONAL-brochure.pdf", brochure(), "application/pdf")
            with Session(engine) as db:
                for id in (front, back, pdf):
                    db.get(Document, UUID(id)).processing_state = "waiting_grouping"
                db.commit()
            request("POST", "/grouping/combine", json={"document_ids": [front, back]})
            with Session(engine) as db:
                pages = list(
                    db.query(DocumentPage)
                    .filter(DocumentPage.document_id == UUID(front))
                    .order_by(DocumentPage.order)
                )
                pages[0].role, pages[1].role = "front", "back"
                db.commit()
            request(
                "PATCH",
                f"/documents/{front}",
                json={
                    "type": "card",
                    "title": "FICTIONAL Example Solar Structures - front and back",
                },
            )
            request(
                "PATCH",
                f"/documents/{pdf}",
                json={"type": "brochure", "title": "FICTIONAL Example Pumps brochure"},
            )
            company = request(
                "POST",
                "/companies",
                json={
                    "fields": {
                        "display_name": "FICTIONAL Example Solar Structures",
                        "products": ["Example solar mounting structures"],
                        "website": "https://example.invalid",
                    }
                },
            )["id"]
            other = request(
                "POST",
                "/companies",
                json={
                    "fields": {
                        "display_name": "FICTIONAL Example Pumps",
                        "products": ["Example irrigation pumps"],
                    }
                },
            )["id"]
            request(
                "POST",
                f"/documents/{front}/attach-company",
                json={"company_id": company},
            )
            request(
                "POST", f"/documents/{pdf}/attach-company", json={"company_id": other}
            )
            for index, name in enumerate(("Mira Example", "Dev Example"), 1):
                request(
                    "POST",
                    "/contacts",
                    json={
                        "company_id": company,
                        "document_id": front,
                        "fields": {
                            "full_name": name,
                            "designation": "=SUM(1)"
                            if index == 2
                            else "Sales, Example division",
                            "channels": [
                                {
                                    "kind": "phone",
                                    "label": "Mobile",
                                    "raw": f"+91000000000{index}",
                                },
                                {
                                    "kind": "phone",
                                    "label": "Office",
                                    "raw": "00123000456",
                                },
                                {
                                    "kind": "email",
                                    "label": "Work",
                                    "raw": f"person{index}@example.invalid",
                                },
                            ],
                        },
                    },
                )
            request(
                "POST",
                "/notes",
                json={
                    "document_id": front,
                    "text": "FICTIONAL personal note, deliberately selected for this sample.\nExample second line.",
                },
            )
            with Session(engine) as db:
                doc = db.get(Document, UUID(pdf))
                prepare_document(db, doc, settings)
                read_document(db, doc, settings)
                db.commit()
            fields = {table: list(names) for table, names in FIELDS.items()}
            folder.mkdir(parents=True, exist_ok=True)
            for format in ("xlsx", "csv", "vcf", "zip"):
                tables = ["contacts"] if format in ("csv", "vcf") else list(fields)
                result = request(
                    "POST",
                    "/exports",
                    json={
                        "scope": "all",
                        "format": format,
                        "tables": tables,
                        "fields": {key: fields[key] for key in tables},
                        "include_vcard": True,
                    },
                )
                with Session(engine) as db:
                    export = db.get(Export, UUID(result["id"]))
                    build(db, export, settings)
                    shutil.copyfile(
                        settings.exports_dir / export.path,
                        folder / f"fictional-sample.{format}",
                    )
                assert result["counts"]["contacts"] == 2
                assert result["counts"]["brochure_only_companies"] == 1
            with ZipFile(folder / "fictional-sample.zip") as archive:
                manifest = json.loads(archive.read("manifest.json"))
                for file in manifest["files"]:
                    assert (
                        hashlib.sha256(archive.read(file["path"])).hexdigest()
                        == file["sha256"]
                    )
                assert (
                    len(manifest["files"]) == 4
                )  # Front/back images and two PDF page mappings.
        engine.dispose()
    print(
        f"Created four fictional exports in {folder}. No configured database, provider or library files were used."
    )


if __name__ == "__main__":
    generate(Path(__file__).resolve().parents[1] / "examples" / "sample-export")
