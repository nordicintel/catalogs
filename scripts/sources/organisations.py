"""The organisations registry, read from nordicintel/organisations on GitHub.

Reduced to what this build needs: every id with its Swedish label, status and homepage,
plus a map from every URI the portals use for an organisation (its dataportal.se agent
URI, same_as URIs and the links/ file) to its id, so publishers resolve to owners.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .common import cached, http

BASE = "https://raw.githubusercontent.com/nordicintel/organisations/main/"


def domain(url):
    """The registrable domain of a URL: catalog.alingsas.se and www.alingsas.se both give alingsas.se."""
    host = (urlparse(url.strip()).hostname or "").lower()
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def name(value):
    return re.sub(r"\s+", " ", value.casefold()).strip()


def fetch(cache: Path):
    data = json.loads(cached(cache, "organisations.json", lambda: http(BASE + "organisations.json")).read_text(encoding="utf-8"))
    links = json.loads(cached(cache, "organisations_links_dataportal.json", lambda: http(BASE + "links/dataportal.json")).read_text(encoding="utf-8"))
    out = {"organisation": {}, "uri": {}, "domain": {}, "name": {}}
    domains, names = {}, {}
    for k, r in data["organisation"].items():
        out["organisation"][k] = {"label": r["label"].get("sv") or next(iter(r["label"].values())), "status": r["status"],
                                  "homepage": r.get("homepage", "")}
        for uri in [r.get("identifier", {}).get("dataportal", "")] + r.get("same_as", []):
            if uri:
                out["uri"][uri] = k
        if r.get("homepage"):
            domains.setdefault(domain(r["homepage"]), set()).add(k)
        for value in list(r["label"].values()) + r.get("alias", []) + [r.get("registered_label", "")]:
            if value:
                names.setdefault(name(value), set()).add(k)
    for uri, k in links.items():
        if k:
            out["uri"].setdefault(uri, k)
    # Only unambiguous domains and names resolve; a body and its same-named predecessor count as one when one succeeded the other.
    out["domain"] = {d: next(iter(ks)) for d, ks in domains.items() if len(ks) == 1}
    for n, ks in names.items():
        current = [k for k in ks if not data["organisation"][k].get("succeeded_by")]
        if len(current) == 1:
            out["name"][n] = current[0]
    return out
