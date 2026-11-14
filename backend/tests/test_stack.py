"""These checks exercise the real services, not a mocked database."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def compose(*args: str) -> str:
    return subprocess.check_output(["docker", "compose", *args], cwd=ROOT, text=True)


@pytest.mark.integration
def test_all_services_healthy_and_only_gateway_exposed():
    rows = [json.loads(line) for line in compose("ps", "--format", "json").splitlines()]
    assert {row["Service"] for row in rows} == {"gateway", "api", "worker", "db"}
    assert all(row["Health"] == "healthy" for row in rows)
    assert all(
        not publisher.get("PublishedPort") or (row["Service"] == "api" and publisher.get("URL") == "127.0.0.1" and publisher.get("TargetPort") == 1455)
        for row in rows
        if row["Service"] != "gateway"
        for publisher in row.get("Publishers") or []
    )


@pytest.mark.integration
def test_schema_extensions_worker_and_host_id():
    result = compose(
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "import json,urllib.request; "
        "print(urllib.request.urlopen('http://localhost:8000/api/v1/health').read().decode())",
    )
    status = json.loads(result)
    assert status["status"] == "ready"
    assert status["services"] == {"database": "ready", "schema": "ready", "worker": "ready"}
    extensions = compose(
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        "expo",
        "-d",
        "expo",
        "-Atc",
        "SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm') ORDER BY extname",
    )
    assert extensions.split() == ["pg_trgm", "vector"]
    identity = compose("exec", "-T", "api", "id", "-u").strip()
    assert identity != "0"


@pytest.mark.integration
def test_pinned_local_ocr_runs_without_network_and_keeps_input():
    code = """
import hashlib, socket
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from app.pipeline.ocr import read_image
path = Path('/tmp/fake-ocr-test.png')
image = Image.new('RGB', (1400, 650), 'white')
draw = ImageDraw.Draw(image)
font = ImageFont.load_default(size=48)
draw.text((60, 100), 'FICTIONAL SOLAR COMPANY', fill='black', font=font)
draw.text((60, 220), 'MAKES MOUNTING STRUCTURES', fill='black', font=font)
image.save(path)
before = hashlib.sha256(path.read_bytes()).hexdigest()
def no_network(*args, **kwargs):
    raise AssertionError('OCR attempted a network connection')
socket.create_connection = no_network
original_connect = socket.socket.connect
def no_ip_connect(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError('OCR attempted a network connection')
    return original_connect(sock, address)
socket.socket.connect = no_ip_connect
text, raw = read_image(path, Path('/data/models'))
assert 'FICTIONAL' in text.upper(), text
assert 'MOUNTING' in text.upper(), text
assert raw['lines'] and raw['lines'][0]['box']
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
path.unlink()
print('local OCR passed with cached models and unchanged input')
"""
    assert "local OCR passed" in compose("exec", "-T", "worker", "python", "-c", code)


@pytest.mark.integration
def test_cached_semantic_search_runs_without_network():
    code = """
import socket
from app.core.config import Settings
from app.pipeline.embeddings import encode
original_connect = socket.socket.connect
def no_internet(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        raise AssertionError('Cached semantic search attempted a network connection')
    return original_connect(sock, address)
socket.socket.connect = no_internet
settings = Settings()
passages = encode([
    'Fictional Alpha manufactures solar panel mounting structures.',
    'Fictional Beta supplies water filtration membranes.'
], settings)
query = encode(['making solar structures'], settings, query=True)[0]
assert all(len(vector) == 384 for vector in passages + [query])
assert all(abs(sum(value * value for value in vector) - 1) < 0.001 for vector in passages)
scores = [sum(a*b for a,b in zip(query, vector, strict=True)) for vector in passages]
assert scores[0] > scores[1], scores
print('local semantic search passed with cached models and all IP connections blocked')
"""
    assert "local semantic search passed" in compose("exec", "-T", "worker", "python", "-c", code)
