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
import check  # noqa: E402
import export  # noqa: E402
from sources import data_europa, dataportal, organisations  # noqa: E402
from sources.organisations import domain, name  # noqa: E402
from sources.common import load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Installs many publishers share; each publisher's context is its own catalog there.
METASOLUTIONS = "SE5568540701"
METRIA = "SE5567992242"
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
    ap.add_argument("--no-check", action="store_true", help="skip the liveness check (keeps previous results)")
    args = ap.parse_args()
    cache = Path(args.cache)
    products = load_json(ROOT / "software.json", {"software": {}})["software"]

    edits = load_json(ROOT / "edits" / "catalogs.json", {"catalog": {}, "ignore": []})
    previous_output = load_json(OUTPUT, {})
    previous = previous_output.get("catalog", {})
    report = {"date": date.today().isoformat(), "register": {}}
    registers = report["register"]

    registry = fetch("organisations", lambda: organisations.fetch(cache), registers)
    orgs, by_uri, by_domain, by_name = (registry.get(k, {}) for k in ("organisation", "uri", "domain", "name"))
    federation = fetch("dataportal", lambda: dataportal.fetch(cache), registers)
    hub = fetch("data_europa", lambda: data_europa.fetch(cache), registers)

    def owner_of(title, *uris):
        for uri in uris:
            if uri in by_uri:
                return by_uri[uri]
        if name(title) in by_name:
            return by_name[name(title)]
        # Myndighetsregistret cuts names at 48 characters: a title that is the start of exactly one
        # long label ("Förvaltningsrätten i Stockholm" / "… och Migrationsdom") names that body.
        if len(name(title)) >= 20:
            starts = {k for n, k in by_name.items() if n.startswith(name(title))}
            if len(starts) == 1:
                return next(iter(starts))
        for uri in uris:
            if uri and domain(uri) in by_domain:
                return by_domain[domain(uri)]
        return None

    catalogs = {}
    unresolved = []
    for context, row in federation.items():
        source = row["source"].strip()
        if not source.startswith("http") or " " in source:
            continue  # no URL to harvest from, so nothing to check or read
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
        # Every registration is a record, also the guessed URLs dataportal.se pre-registered for
        # every public body: the harvest outcome, or our own probe when there is none, is the status.
        e = {"protocol": "dcat_ap", "url": source}
        if row["run"]:
            ok = row["run"]["status"] == "Success" and row["run"]["datasets"] > 0
            e["checked"] = {"date": row["run"]["date"], "result": "ok" if ok else "error",
                            "detail": f"dataportal.se harvest {row['run']['status']}, {row['run']['datasets']} datasets, {row['run']['errors']} validation errors"}
        endpoints = [e]
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
        record = {"id": key, "label": {"sv": row["title"]} if row["title"] else {}, "catalog_type": "open_data_portal", "software": software,
                  "endpoint": endpoints, "status": "unknown", "source": ["dataportal"],
                  "identifier": {"dataportal": f"https://admin.dataportal.se/store/{context}"}}
        if row["homepage"]:
            record["homepage"] = row["homepage"]
        if row.get("description"):
            record["description"] = {"sv": row["description"]}
        if row.get("license", "").startswith("http"):
            record["license"] = row["license"]
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
    # data.europa.eu: service hosts behind the Swedish catalogues' datasets and data services.
    GEO = {"wms_1_3", "wfs_2", "arcgis_rest", "atom", "csw_2", "ogc_features"}
    for host, row in hub.items():
        key = host.removeprefix("www.")
        if key in edits["ignore"]:
            continue
        endpoints = [{"protocol": proto, "url": url} for proto, urls in row["protocol"].items() for url in urls]
        spoken = set(row["protocol"])
        bases = " ".join(url for urls in row["protocol"].values() for url in urls)
        if spoken & {"pxweb_v1", "pxweb_v2"}:
            catalog_type, software = "statistics_database", "pxweb"
        elif "entrystore" in spoken:
            catalog_type, software = "open_data_portal", "entryscape"
        elif spoken & GEO:
            catalog_type = "geoportal"
            software = "geoserver" if "/geoserver" in bases else "arcgis" if "arcgis_rest" in spoken else "custom"
        else:
            catalog_type, software = "api", "custom"
        record = {"id": key, "label": {}, "catalog_type": catalog_type, "software": software, "endpoint": endpoints, "status": "unknown", "source": ["data_europa"]}
        owner = owner_of("", *row["publisher"], f"https://{host}/")
        if owner:
            record["owner"] = owner
        elif key not in catalogs and key not in edits["catalog"]:
            unresolved.append({"id": key, "title": "", "publisher": ", ".join(row["publisher"])})
        if key.endswith(".metria.se"):
            record["operator"] = METRIA
        if key in catalogs:
            patch = {"endpoint": endpoints}
            if "owner" not in catalogs[key] and owner:
                patch["owner"] = owner
            merge(catalogs[key], patch)
            catalogs[key]["source"].append("data_europa")
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
        unique = {(e["protocol"], e["url"].rstrip("/").lower()): e for e in sorted(r["endpoint"], key=lambda e: (e["protocol"], e["url"]))}
        r["endpoint"] = sorted(unique.values(), key=lambda e: (e["protocol"], e["url"]))
        for e in r["endpoint"]:
            old = next((o for o in previous.get(r["id"], {}).get("endpoint", []) if (o["protocol"], o["url"]) == (e["protocol"], e["url"])), None)
            if "checked" not in e and old and old.get("checked"):
                e["checked"] = old["checked"]  # carried until the next check overwrites it
        if not r["label"]:
            owner = orgs[r["owner"]]["label"] if r.get("owner") in orgs else r["id"]
            r["label"]["sv"] = {"geoportal": f"{owner} geodatatjänster", "api": f"{owner} API"}.get(r["catalog_type"], owner)

    catalogs = dict(sorted(catalogs.items()))
    if args.no_check:
        for r in catalogs.values():
            r["status"] = check.status(r)
    else:
        registers["check"] = check.run(catalogs, previous, report["date"])
    for r in catalogs.values():  # a carried result is still a result the check gave
        r["source"] = sorted(set(r["source"]) | ({"check"} if any(e.get("checked") for e in r["endpoint"]) else set()))
    generated = previous_output.get("generated", report["date"]) if catalogs == previous else report["date"]
    dump(OUTPUT, {"generated": generated, "count": len(catalogs), "catalog": catalogs})
    export.export(OUTPUT, ROOT / "protocols.json", ROOT / "software.json")

    added = sorted(set(catalogs) - set(previous))
    removed = sorted(set(previous) - set(catalogs))
    changed = sorted(k for k in set(catalogs) & set(previous) if catalogs[k] != previous[k])
    report.update({"count": len(catalogs), "added": added, "removed": removed, "changed": len(changed),
                   "catalog_type": dict(Counter(r.get("catalog_type", "none") for r in catalogs.values())),
                   "protocol": dict(Counter(e["protocol"] for r in catalogs.values() for e in r["endpoint"])),
                   "status": dict(Counter(r["status"] for r in catalogs.values())),
                   "without_owner": sorted(unresolved, key=lambda u: u["id"]),
                   "without_software_protocol": sorted(k for k, r in catalogs.items() if products[r["software"]].get("protocol")
                                                       and not {e["protocol"] for e in r["endpoint"]} & set(products[r["software"]]["protocol"]))})
    if added or removed or changed or any(v["status"] == "failed" for v in registers.values()):
        dump(ROOT / "reports" / f"{report['date']}.json", report)
    print(f"{len(catalogs)} catalogs: +{len(added)} -{len(removed)} ~{len(changed)}; "
          + ", ".join(f"{k} {v['status']}" for k, v in registers.items()), file=sys.stderr)
    sys.exit(2 if registers and all(v["status"] == "failed" for v in registers.values()) else 0)


if __name__ == "__main__":
    main()
