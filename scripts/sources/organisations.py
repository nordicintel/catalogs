"""The organisations registry, read from nordicintel/organisations on GitHub.

Reduced to what this build needs: every id, its Swedish label and whether it still
exists, so owner and operator references can be validated and labelled.
"""
import json
from pathlib import Path

from .common import cached, http

URL = "https://raw.githubusercontent.com/nordicintel/organisations/main/organisations.json"


def fetch(cache: Path):
    data = json.loads(cached(cache, "organisations.json", lambda: http(URL)).read_text(encoding="utf-8"))
    return {k: {"label": r["label"].get("sv") or next(iter(r["label"].values())), "status": r["status"], "slug": r.get("slug", "")}
            for k, r in data["organisation"].items()}
