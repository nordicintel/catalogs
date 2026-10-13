"""Liveness check: ask every endpoint the question its protocol defines and record the answer.

Each protocol in protocols.json carries a ``check``: a path appended to the endpoint URL
and a substring a live answer contains. The first 64 KB of the response are enough to
tell. Results land on the endpoint as ``checked`` and decide the catalog's ``status``:
active when any endpoint answers (also with 401 or 403: alive but behind a key), inactive when every checked endpoint fails, unknown
when nothing could be checked.

``checked.date`` is the date the current result was first observed, so a weekly run that
finds nothing changed rewrites nothing. The report carries the run date.

A ``dcat_ap`` endpoint whose ``checked`` came from dataportal.se's own harvest keeps it:
the portal fetched the whole file, which is a stronger check than ours. When most
endpoints are unreachable the network, not the catalogs, is down: the previous results
are kept and the report says the check failed.
"""
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from sources.common import UA

TIMEOUT = 20
WORKERS = 16
READ = 65536
HARVEST = "dataportal.se harvest"
FAILED_RUN = 0.8  # share of unreachable endpoints above which the run itself is judged broken


def probe(url, check):
    """(result, detail) for one endpoint."""
    target = url + check.get("path", "")
    headers = {"User-Agent": UA, "Accept": check.get("accept") or "*/*"}
    try:
        with urllib.request.urlopen(urllib.request.Request(target, headers=headers), timeout=TIMEOUT) as resp:
            body = resp.read(READ).decode("utf-8", "replace")
            expect = check.get("expect", "")
            if expect and expect not in body:
                return "error", f"HTTP {resp.status} without {expect!r}"
            return "ok", f"HTTP {resp.status}"
    except urllib.error.HTTPError as error:
        # 401 and 403 mean the service is there but wants a key: alive, not ours to read.
        return ("restricted" if error.code in (401, 403) else "error"), f"HTTP {error.code}"
    except Exception as error:  # noqa: BLE001 - any failure is the answer
        reason = getattr(error, "reason", error)
        return "unreachable", f"{type(reason).__name__}: {reason}"[:120]


def run(catalogs, protocols, previous, today):
    """Check every endpoint in place. Returns a summary for the report."""
    before = {(k, e["protocol"], e["url"]): e.get("checked") for k, r in previous.items() for e in r.get("endpoint", [])}
    work = [(key, e) for key, r in catalogs.items() for e in r["endpoint"]
            if not (e.get("checked") or {}).get("detail", "").startswith(HARVEST)]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda item: probe(item[1]["url"], protocols[item[1]["protocol"]].get("check", {})), work))

    unreachable = sum(1 for result, _ in results if result == "unreachable")
    if work and unreachable / len(work) > FAILED_RUN:
        for (key, e), _ in zip(work, results):
            if before.get((key, e["protocol"], e["url"])):
                e["checked"] = before[(key, e["protocol"], e["url"])]
        summary = {"status": "failed", "endpoints": len(work), "unreachable": unreachable}
    else:
        for (key, e), (result, detail) in zip(work, results):
            old = before.get((key, e["protocol"], e["url"])) or {}
            date = old["date"] if old.get("result") == result and old.get("detail") == detail else today
            e["checked"] = {"date": date, "result": result, "detail": detail}
        summary = {"status": "fetched", "endpoints": len(work),
                   "ok": sum(1 for r, _ in results if r == "ok"), "restricted": sum(1 for r, _ in results if r == "restricted"),
                   "error": sum(1 for r, _ in results if r == "error"),
                   "unreachable": unreachable}

    for r in catalogs.values():
        outcomes = [e["checked"]["result"] for e in r["endpoint"] if e.get("checked")]
        r["status"] = "active" if {"ok", "restricted"} & set(outcomes) else "inactive" if outcomes else "unknown"
    print(f"check: {summary}", file=sys.stderr)
    return summary
