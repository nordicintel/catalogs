"""data.europa.eu's hub search for the Swedish catalogues: every service host that datasets
and data services point at, with the protocol each speaks and who publishes there.

The hub files Swedish content under three catalogues (oppnadata = dataportal.se,
geodata-se = Geodataportalen, nsip-se = the high-value-data single point). dataportal.se is
already a register of its own, so its datasets are skipped here; its data services are
not, since they name APIs and OGC services the federation itself does not. The reduced
result is keyed by host: publisher URIs seen, dataset count, and one entry per protocol
with the endpoint base URLs the URLs collapse to.
"""
import json
import os.path
import re
import urllib.parse
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from .common import cached, http

SEARCH = "https://data.europa.eu/api/hub/search/search?"
CATALOGUES = ("oppnadata", "geodata-se", "nsip-se")
DATASET_CATALOGUES = ("geodata-se", "nsip-se")
PAGE = 500
MAX_BASES = 3  # more distinct service bases than this on one host collapse to their common path


def _search(filter_, catalogue):
    out, page = [], 0
    while True:
        url = SEARCH + urllib.parse.urlencode({"filter": filter_, "facets": json.dumps({"catalog": [catalogue]}), "limit": PAGE, "page": page})
        rows = json.loads(http(url, timeout=300))["result"]["results"]
        out += rows
        if len(rows) < PAGE:
            return out
        page += 1


def _raw():
    data = {"dataservice": {c: _search("dataservice", c) for c in CATALOGUES},
            "dataset": {c: _search("dataset", c) for c in DATASET_CATALOGUES}}
    return json.dumps(data, ensure_ascii=False).encode()


def normalise(url):
    p = urlparse(url.strip())
    host = (p.hostname or "").lower()
    if not host:
        return ""
    return urlunparse((p.scheme.lower() or "https", host, p.path.rstrip("/"), "", "", ""))


def classify(url):
    """(protocol, endpoint base) for a distribution or service URL, or None for a web page."""
    p = urlparse(url)
    path, query = p.path.lower(), parse_qs(p.query.lower())
    service = (query.get("service") or [""])[0]
    base = normalise(url)
    if "/arcgis/" in path:
        return "arcgis_rest", re.sub(r"(?i)(/arcgis/rest/services|/arcgis/services|/arcgis).*", r"\1", base).replace("/arcgis/services", "/arcgis/rest/services")
    if "/store/" in path and ("entryscape" in path or "/store/search" in path or re.search(r"/store/\d+/", path)):
        return "entrystore", re.sub(r"/store/.*", "", base)
    if re.search(r"/pxweb/api/v1|/api/v1/(sv|en)/", path):
        return "pxweb_v1", re.sub(r"(?i)(/api/v1).*", r"\1", base)
    if "/api/v2" in path and "pxweb" in path:
        return "pxweb_v2", re.sub(r"(?i)(/api/v2).*", r"\1", base)
    if service == "wms" or re.search(r"/wms(/|$|\?)|/wmsserver", path):
        return "wms_1_3", base
    if service == "wfs" or re.search(r"/wfs(\.axd)?(/|$)", path):
        return "wfs_2", base
    if re.search(r"/ows(/|$)", path):
        return "ows", base
    if service == "csw" or path.endswith("/csw"):
        return "csw_2", base
    if path.endswith(".atom") or "/atom" in path or re.search(r"/feeds?/[^/]+\.xml$", path):
        return "atom", base
    if re.search(r"swagger|openapi|/api/|/api$", path) and not re.search(r"\.(html|pdf)$", path):
        return "api", base
    return None


def common_prefix(bases):
    parts = [b.split("/") for b in bases]
    prefix = parts[0]
    for q in parts[1:]:
        n = 0
        while n < min(len(prefix), len(q)) and prefix[n] == q[n]:
            n += 1
        prefix = prefix[:n]
    return "/".join(prefix) if len(prefix) > 3 else "/".join(parts[0][:3])


def fetch(cache: Path):
    raw = json.loads(cached(cache, "data_europa_hub.json", _raw).read_text(encoding="utf-8"))
    hosts = {}

    def note(url, publisher, catalogue, is_dataset):
        found = classify(url)
        if not found:
            return
        protocol, base = found
        host = urlparse(base).hostname
        entry = hosts.setdefault(host, {"publisher": [], "catalogue": [], "datasets": 0, "services": 0, "protocol": {}})
        if publisher and publisher not in entry["publisher"]:
            entry["publisher"].append(publisher)
        if catalogue not in entry["catalogue"]:
            entry["catalogue"].append(catalogue)
        entry["datasets" if is_dataset else "services"] += 1
        for proto in (("wms_1_3", "wfs_2") if protocol == "ows" else (protocol,)):
            entry["protocol"].setdefault(proto, set()).add(base)

    for catalogue, rows in raw["dataset"].items():
        for r in rows:
            publisher = ((r.get("publisher") or {}).get("resource") or "")
            for d in r.get("distributions") or []:
                for key in ("access_url", "download_url"):
                    values = d.get(key) or []
                    for url in (values if isinstance(values, list) else [values]):
                        note(url, publisher, catalogue, True)
    for catalogue, rows in raw["dataservice"].items():
        for r in rows:
            publisher = ((r.get("publisher") or {}).get("resource") or "")
            for url in r.get("endpoint_url") or []:
                note(url, publisher, catalogue, False)

    for entry in hosts.values():
        entry["publisher"].sort()
        entry["catalogue"].sort()
        for proto, bases in list(entry["protocol"].items()):
            bases = sorted(bases)
            bases = bases if len(bases) <= MAX_BASES else [common_prefix(bases)]
            # GeoServer answers every OGC service at /ows; a collapsed base needs that to be checkable.
            entry["protocol"][proto] = [b + "/ows" if b.endswith("/geoserver") and proto in ("wms_1_3", "wfs_2") else b for b in bases]
        entry["protocol"] = dict(sorted(entry["protocol"].items()))
    return dict(sorted(hosts.items()))
