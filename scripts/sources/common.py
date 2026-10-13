import json
import sys
import urllib.request
from pathlib import Path

UA = "nordicintel-catalogs/0.1 (+https://github.com/nordicintel/catalogs)"


def http(url, *, headers=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def cached(cache: Path, name: str, producer):
    path = cache / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching {name}", file=sys.stderr)
        path.write_bytes(producer())
    return path


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
