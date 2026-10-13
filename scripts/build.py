"""Build catalogs.json and a report from the registers and edits/.

Usage: python scripts/build.py [--cache DIR]

Each register is fetched into the cache and reduced to a committed snapshot in
snapshots/<register>.json. When a register cannot be fetched, the committed
snapshot is used instead and the report says so. One register failing never stops
the build. Edits are merged last and win.
"""
import argparse
import json
import re
import sys
import traceback
from collections import Counter
from urllib.parse import urlparse
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sources import dataportal, organisations  # noqa: E402
from sources.organisations import domain, name  # noqa: E402
from sources.common import load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Installs many publishers share; each publisher's context is its own catalog there.
METASOLUTIONS = "SE5568540701"
DIGG = "SE2021006883"
SHARED_HOSTS = {"free.entryscape.com": METASOLUTIONS, "editera.dataportal.se": DIGG, "admin.dataportal.se": DIGG,
                "registrera.oppnadata.se": DIGG}
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

    registry = fetch("organisations", lambda: organisations.fetch(cache), registers)
    orgs, by_uri, by_domain, by_name = (registry.get(k, {}) for k in ("organisation", "uri", "domain", "name"))
    federation = fetch("dataportal", lambda: dataportal.fetch(cache), registers)

    def owner_of(title, *uris):
        for uri in uris:
            if uri in by_uri:
                return by_uri[uri]
        if name(title) in by_name:
            return by_name[name(title)]
        for uri in uris:
            if uri and domain(uri) in by_domain:
                return by_domain[domain(uri)]
        return None

    catalogs = {}
    unresolved, registered_only = [], []
    for context, row in federation.items():
        source = row["source"].strip()
        if not source.startswith("http") or " " in source:
            continue  # registered but never harvested, or a URL that cannot be fetched
        parsed = urlparse(source)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if host in SHARED_HOSTS:
            # One context in a shared install: its number in that install's store, read from the harvested URL.
            own = re.search(r"/store/(\d+)/", parsed.path)
            key = f"{host}/{own.group(1) if own else context}"
        else:
            key = host
        if key in edits["ignore"] or source in edits["ignore"]:
            continue
        harvested = bool(row["run"]) and row["run"]["status"] == "Success" and row["run"]["datasets"] > 0
        if not harvested and key not in previous and key not in edits["catalog"]:
            # A registration whose harvest has never succeeded is not a catalog yet; dataportal.se
            # pre-registered a guessed URL for every public body. Listed in the report, not the product.
            registered_only.append({"id": key, "title": row["title"], "source": source,
                                    "run": (row["run"] or {}).get("status", "never")})
            continue
        endpoints = []
        if source:
            e = {"protocol": "dcat_ap", "url": source}
            if row["run"]:
                ok = row["run"]["status"] == "Success"
                e["checked"] = {"date": row["run"]["date"], "result": "ok" if ok else "error",
                                "detail": f"dataportal.se harvest {row['run']['status']}, {row['run']['datasets']} datasets, {row['run']['errors']} validation errors"}
            endpoints.append(e)
        software = "custom"
        root = f"{parsed.scheme}://{parsed.hostname}"
        if host in SHARED_HOSTS:
            software = "entryscape"  # one context in somebody else's install; the RDF export is its only endpoint
        elif "/store/" in parsed.path or host.endswith(".entryscape.net"):
            software = "entryscape"
            endpoints.append({"protocol": "entrystore", "url": root})
        elif "/api/3/" in parsed.path or parsed.path.endswith("catalog.rdf"):
            software = "ckan"
            endpoints.append({"protocol": "ckan_v3", "url": root})
        elif host.endswith("hub.arcgis.com") or parsed.path.endswith("data.json"):
            software = "arcgis"
            endpoints.append({"protocol": "arcgis_hub", "url": root})
        record = {"id": key, "label": {"sv": row["title"]} if row["title"] else {}, "type": "open_data_portal", "software": software,
                  "endpoint": endpoints, "status": "unknown", "source": ["dataportal"],
                  "identifier": {"dataportal": f"https://admin.dataportal.se/store/{context}"}}
        if row["run"]:
            record["status"] = "active" if row["run"]["status"] == "Success" else "inactive"
        if row["homepage"]:
            record["homepage"] = row["homepage"]
        owner = owner_of(row["title"], row["publisher"], row["homepage"], source if host not in SHARED_HOSTS else "")
        if owner:
            record["owner"] = owner
        else:
            unresolved.append({"id": key, "title": row["title"], "publisher": row["publisher"]})
        if host in SHARED_HOSTS:
            record["operator"] = SHARED_HOSTS[host]
        elif host.endswith(".entryscape.net"):
            record["operator"] = METASOLUTIONS
        if key in catalogs:
            # Several contexts on one host: keep the first, add the rest as endpoints and identifiers.
            merge(catalogs[key], {"endpoint": endpoints, "same_as": [f"https://admin.dataportal.se/store/{context}"]})
        else:
            catalogs[key] = record
    for key, patch in edits["catalog"].items():
        if key in edits["ignore"]:
            continue
        record = catalogs.setdefault(key, {"id": key, "label": {}, "endpoint": [], "status": "unknown", "source": []})
        merge(record, patch)
        record["source"].append("edits")
        if "owner" in record:
            unresolved = [u for u in unresolved if u["id"] != key]

    for r in catalogs.values():
        r["source"] = sorted(set(r["source"]))
        r["endpoint"] = sorted(r["endpoint"], key=lambda e: (e["protocol"], e["url"]))
        if not r["label"]:
            r["label"]["sv"] = orgs[r["owner"]]["label"] if r.get("owner") in orgs else r["id"]

    catalogs = dict(sorted(catalogs.items()))
    generated = previous_output.get("generated", report["date"]) if catalogs == previous else report["date"]
    dump(OUTPUT, {"generated": generated, "count": len(catalogs), "catalog": catalogs})

    added = sorted(set(catalogs) - set(previous))
    removed = sorted(set(previous) - set(catalogs))
    changed = sorted(k for k in set(catalogs) & set(previous) if catalogs[k] != previous[k])
    report.update({"count": len(catalogs), "added": added, "removed": removed, "changed": len(changed),
                   "type": dict(Counter(r.get("type", "none") for r in catalogs.values())),
                   "protocol": dict(Counter(e["protocol"] for r in catalogs.values() for e in r["endpoint"])),
                   "without_owner": sorted(unresolved, key=lambda u: u["id"]),
                   "registered_only": len(registered_only)})
    if added or removed or changed or any(v["status"] == "failed" for v in registers.values()):
        dump(ROOT / "reports" / f"{report['date']}.json", report)
    print(f"{len(catalogs)} catalogs: +{len(added)} -{len(removed)} ~{len(changed)}; "
          + ", ".join(f"{k} {v['status']}" for k, v in registers.items()), file=sys.stderr)
    sys.exit(2 if registers and all(v["status"] == "failed" for v in registers.values()) else 0)


if __name__ == "__main__":
    main()
