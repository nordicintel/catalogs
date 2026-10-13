"""The organisations registry, read from nordicintel/organisations on GitHub.

Every organisation record as published, plus a map from every URI the portals use for an organisation (its dataportal.se agent
URI, same_as URIs and the links/ file) to its id, so publishers resolve to owners.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from .common import cached, http, skip

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
    out = {"generated": data.get("generated", ""), "organisation": {}, "uri": {}, "domain": {}, "name": {}}
    domains, names = {}, {}
    for k, r in data["organisation"].items():
        try:
            out["organisation"][k] = r  # the whole record: the build ships the referenced ones in exports/
            for uri in [r.get("identifier", {}).get("dataportal", "")] + r.get("same_as", []):
                if uri:
                    out["uri"][uri] = k
            if r.get("homepage"):
                domains.setdefault(domain(r["homepage"]), set()).add(k)
            for value in list(r["label"].values()) + r.get("alias", []) + [r.get("registered_label", "")]:
                if value:
                    names.setdefault(name(value), set()).add(k)
        except Exception as error:  # noqa: BLE001
            skip("organisations", k, error)
    for uri, k in links.items():
        if k:
            out["uri"].setdefault(uri, k)
    # Only unambiguous domains and names resolve; a body and its same-named predecessor count as one when one succeeded the other.
    out["domain"] = {d: next(iter(ks)) for d, ks in domains.items() if len(ks) == 1}
    def successor(k, depth=0):
        """The body a wound-up one became, followed to the end; None when it split or the chain is unknown."""
        nxt = data["organisation"][k].get("succeeded_by", [])
        if not nxt:
            return k
        return successor(nxt[0], depth + 1) if len(nxt) == 1 and nxt[0] in data["organisation"] and depth < 5 else None

    for n, ks in names.items():
        current = [k for k in ks if not data["organisation"][k].get("succeeded_by")]
        if len(current) == 1:
            out["name"][n] = current[0]
        elif not current and len(ks) == 1 and successor(next(iter(ks))):
            # A registration under a wound-up body's name (Stockholms läns landsting) belongs to its successor.
            out["name"][n] = successor(next(iter(ks)))
    return out
