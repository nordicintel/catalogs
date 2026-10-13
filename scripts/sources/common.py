import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "nordicintel-catalogs/0.1 (+https://github.com/nordicintel/catalogs)"
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF = (10, 30, 60)  # seconds between attempts; a Retry-After header wins when it is longer


def http(url, *, headers=None, timeout=120, attempts=4):
    """GET, retrying rate limits, gateway errors and network failures a few times."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS or attempt == attempts - 1:
                raise
            wait = max(BACKOFF[min(attempt, len(BACKOFF) - 1)], int(error.headers.get("Retry-After") or 0))
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == attempts - 1:
                raise
            wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
        print(f"retrying {url[:80]} in {wait}s", file=sys.stderr)
        time.sleep(wait)


def skip(name, row, error):
    """Log a row a source could not read; the caller carries on with the next one."""
    print(f"{name}: row skipped, {type(error).__name__}: {error}; {str(row)[:120]}", file=sys.stderr)


def cached(cache: Path, name: str, producer):
    path = cache / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching {name}", file=sys.stderr)
        path.write_bytes(producer())
    return path


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
