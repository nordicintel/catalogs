"""Build catalogs.json and a report from the registers and edits/.

Usage: python scripts/build.py [--cache DIR]

Each register is fetched into the cache and reduced to a committed snapshot in
snapshots/<register>.json. When a register cannot be fetched, the committed
snapshot is used instead and the report says so. One register failing never stops
the build. Edits are merged last and win.
"""
import argparse
import json
import sys
import traceback
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sources import organisations  # noqa: E402
from sources.common import load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "snapshots"
OUTPUT = ROOT / "catalogs.json"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch(name, producer, report):
    """Run one register's fetch; fall back to its committed snapshot on any error."""
    path = SNAPSHOTS / f"{name}.json"
    try:
        data = producer()
        dump(path, data)
        report[name] = {"status": "fetched", "rows": len(data)}
        return data
    except Exception as error:  # noqa: BLE001 - any failure must not stop the build
        print(f"{name}: {error}", file=sys.stderr)
        traceback.print_exc()
        data = load_json(path, {})
        report[name] = {"status": "stale" if data else "failed", "rows": len(data), "error": str(error)[:200]}
        return data


def merge(record, patch):
    """Apply an edits patch: label and identifier per key, endpoint per (protocol, url), same_as union, else override."""
    for field, value in patch.items():
        if field in ("label", "identifier"):
            record.setdefault(field, {}).update(value)
        elif field == "endpoint":
            current = {(e["protocol"], e["url"]): e for e in record.get("endpoint", [])}
            for e in value:
                current.setdefault((e["protocol"], e["url"]), {}).update(e)
            record["endpoint"] = sorted(current.values(), key=lambda e: (e["protocol"], e["url"]))
        elif field == "same_as":
            record["same_as"] = sorted(set(record.get("same_as", [])) | set(value))
        else:
            record[field] = value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / ".cache"))
    cache = Path(ap.parse_args().cache)

    edits = load_json(ROOT / "edits" / "catalogs.json", {"catalog": {}, "ignore": []})
    previous_output = load_json(OUTPUT, {})
    previous = previous_output.get("catalog", {})
    report = {"date": date.today().isoformat(), "register": {}}
    registers = report["register"]

    orgs = fetch("organisations", lambda: organisations.fetch(cache), registers)

    catalogs = {}
    for key, patch in edits["catalog"].items():
        if key in edits["ignore"]:
            continue
        record = catalogs.setdefault(key, {"id": key, "label": {}, "endpoint": [], "status": "unknown", "source": []})
        merge(record, patch)
        record["source"].append("edits")

    for r in catalogs.values():
        r["source"] = sorted(set(r["source"]))
        r["endpoint"] = sorted(r["endpoint"], key=lambda e: (e["protocol"], e["url"]))
        if not r["label"] and r.get("owner") in orgs:
            r["label"]["sv"] = orgs[r["owner"]]["label"]

    catalogs = dict(sorted(catalogs.items()))
    generated = previous_output.get("generated", report["date"]) if catalogs == previous else report["date"]
    dump(OUTPUT, {"generated": generated, "count": len(catalogs), "catalog": catalogs})

    added = sorted(set(catalogs) - set(previous))
    removed = sorted(set(previous) - set(catalogs))
    changed = sorted(k for k in set(catalogs) & set(previous) if catalogs[k] != previous[k])
    report.update({"count": len(catalogs), "added": added, "removed": removed, "changed": len(changed),
                   "type": dict(Counter(r.get("type", "none") for r in catalogs.values())),
                   "protocol": dict(Counter(e["protocol"] for r in catalogs.values() for e in r["endpoint"]))})
    if added or removed or changed or any(v["status"] == "failed" for v in registers.values()):
        dump(ROOT / "reports" / f"{report['date']}.json", report)
    print(f"{len(catalogs)} catalogs: +{len(added)} -{len(removed)} ~{len(changed)}; "
          + ", ".join(f"{k} {v['status']}" for k, v in registers.items()), file=sys.stderr)
    sys.exit(2 if registers and all(v["status"] == "failed" for v in registers.values()) else 0)


if __name__ == "__main__":
    main()
