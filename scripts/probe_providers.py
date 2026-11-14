#!/usr/bin/env python3
"""Connectivity checks only; never import another app's credentials."""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from storage_config import read_env


def probe_ollama(url: str, model: str) -> dict:
    if not url:
        return {"provider": "ollama", "status": "not_configured"}
    try:
        with httpx.Client(timeout=10, follow_redirects=False) as client:
            result = client.get(url.rstrip("/") + "/api/tags")
            if result.status_code in (401, 403):
                return {"provider": "ollama", "status": "permission_denied"}
            result.raise_for_status()
            models = [entry["name"] for entry in result.json().get("models", [])]
        return {"provider": "ollama", "status": "reachable" if not model or model in models else "model_missing",
                "models": models, "inference_verified": False}
    except (httpx.HTTPError, ValueError, KeyError):
        return {"provider": "ollama", "status": "unreachable"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    config = read_env(args.env) if args.env.exists() else {}
    print(json.dumps([
        probe_ollama(os.getenv("OLLAMA_URL", config.get("OLLAMA_URL", "")), config.get("OLLAMA_MODEL", "")),
        {"provider": "chatgpt", "status": "not_connected",
         "reason": "Official transferable subscription inference requires verification; see docs/chatgpt-connection.md"},
        {"provider": "openrouter", "status": "not_configured"},
    ], indent=2))


if __name__ == "__main__":
    main()

