"""Check catalogs.json, protocols.json, software.json and edits/catalogs.json against the schemas and each other.

Standard library only: required keys, enums, patterns, unknown fields, and every reference
(protocol, software, owner, operator) resolves. Owner and operator are checked against the
organisations snapshot. Exit 1 on any error.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
errors = []


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def check(obj, schema, where, defs=None):
    defs = defs or schema.get("$defs", {})
    if "$ref" in schema:
        schema = defs[schema["$ref"].rsplit("/", 1)[-1]]
    t = schema.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            errors.append(f"{where}: expected object"); return
        for key in schema.get("required", []):
            if key not in obj:
                errors.append(f"{where}: missing {key}")
        props = schema.get("properties", {})
        for key, value in obj.items():
            if key in props:
                check(value, props[key], f"{where}.{key}", defs)
            elif "additionalProperties" in schema and schema["additionalProperties"] is not False:
                if isinstance(schema["additionalProperties"], dict):
                    check(value, schema["additionalProperties"], f"{where}.{key}", defs)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{where}: unknown field {key}")
        if "minProperties" in schema and len(obj) < schema["minProperties"]:
            errors.append(f"{where}: needs at least {schema['minProperties']} entries")
    elif t == "array":
        if not isinstance(obj, list):
            errors.append(f"{where}: expected array"); return
        if "minItems" in schema and len(obj) < schema["minItems"]:
            errors.append(f"{where}: needs at least {schema['minItems']} items")
        for i, item in enumerate(obj):
            check(item, schema.get("items", {}), f"{where}[{i}]", defs)
    elif t == "string":
        if not isinstance(obj, str):
            errors.append(f"{where}: expected string"); return
        if "enum" in schema and obj not in schema["enum"]:
            errors.append(f"{where}: {obj!r} not in {schema['enum']}")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], obj):
            errors.append(f"{where}: {obj!r} does not match {schema['pattern']}")
        if schema.get("format") == "uri" and not re.match(r"^https?://", obj):
            errors.append(f"{where}: {obj!r} is not an http(s) URI")
        if schema.get("format") == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", obj):
            errors.append(f"{where}: {obj!r} is not a date")


catalog_schema = read("schema/catalog.schema.json")
protocol_schema = read("schema/protocol.schema.json")
software_schema = read("schema/software.schema.json")
edits_schema = read("schema/edits.schema.json")

protocols = read("protocols.json")["protocol"]
software = read("software.json")["software"]
catalogs = read("catalogs.json")["catalog"] if (ROOT / "catalogs.json").exists() else {}
edits = read("edits/catalogs.json") if (ROOT / "edits/catalogs.json").exists() else {"catalog": {}, "ignore": []}
orgs = read("snapshots/organisations.json").get("organisation", {}) if (ROOT / "snapshots/organisations.json").exists() else {}

for key, p in protocols.items():
    if key != p.get("id"):
        errors.append(f"protocols.json: key {key} != id {p.get('id')}")
    check(p, protocol_schema, f"protocols.json {key}")
for key, s in software.items():
    if key != s.get("id"):
        errors.append(f"software.json: key {key} != id {s.get('id')}")
    check(s, software_schema, f"software.json {key}")
    for proto in s.get("protocol", []):
        if proto not in protocols:
            errors.append(f"software.json {key}: protocol {proto} not in protocols.json")
    if s.get("vendor") and orgs and s["vendor"] not in orgs:
        errors.append(f"software.json {key}: vendor {s['vendor']} not in organisations")

seen_urls = {}
for key, c in catalogs.items():
    if key != c.get("id"):
        errors.append(f"catalogs.json: key {key} != id {c.get('id')}")
    check(c, catalog_schema, f"catalogs.json {key}")
    if c.get("software") and c["software"] not in software:
        errors.append(f"catalogs.json {key}: software {c['software']} not in software.json")
    for field in ("owner", "operator"):
        if c.get(field) and orgs and c[field] not in orgs:
            errors.append(f"catalogs.json {key}: {field} {c[field]} not in organisations")
    for e in c.get("endpoint", []):
        if e.get("protocol") not in protocols:
            errors.append(f"catalogs.json {key}: protocol {e.get('protocol')} not in protocols.json")
        url = (e.get("protocol"), e.get("url", "").rstrip("/").lower())
        if url in seen_urls:
            errors.append(f"catalogs.json {key}: endpoint {url} also in {seen_urls[url]}")
        seen_urls[url] = key

check(edits, edits_schema, "edits/catalogs.json")
for key, patch in edits.get("catalog", {}).items():
    for field in patch:
        if field not in catalog_schema["properties"] or field in ("id", "source", "status"):
            errors.append(f"edits/catalogs.json {key}: field {field} not allowed")

for e in errors:
    print(e)
print(f"{len(catalogs)} catalogs, {len(protocols)} protocols, {len(software)} software, {len(errors)} errors", file=sys.stderr)
sys.exit(1 if errors else 0)
