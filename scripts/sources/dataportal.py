"""dataportal.se's federation: every registered catalog, the URL the portal harvests it from,
and how the last harvest went.

dataportal.se is an EntryScape install. Each registered catalog has its own context in
the store with a dcat:Catalog entry (title, publisher, homepage), a Pipeline whose fetch
step carries the harvested URL, and PipelineResult entries, the latest tagged "latest",
with the run's status, date, dataset count and validation errors. The catalog entry also
gives description, language, license and spatial coverage; description and license are kept. The reduced result is
keyed by context id.
"""
import json
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import cached, http, skip

STORE = "https://admin.dataportal.se/store"
ACCEPT = {"Accept": "application/json"}
ES = "http://entrystore.org/terms/"
PR = ES + "pipelineresult#"


def _search(query, limit=100):
    out, offset = [], 0
    while True:
        url = f"{STORE}/search?" + urllib.parse.urlencode({"type": "solr", "limit": limit, "offset": offset, "query": query})
        page = json.loads(http(url, headers=ACCEPT)).get("resource", {}).get("children", [])
        out += page
        if len(page) < limit:
            return out
        offset += limit


def _first(graph, predicate):
    for po in graph.values():
        for p, values in po.items():
            if p.endswith(predicate) and values:
                return values[0]["value"]
    return ""


def _source_url(context, entry):
    """The fetch step's source argument of a pipeline, read from its resource."""
    graph = json.loads(http(f"{STORE}/{context}/resource/{entry}", headers=ACCEPT))
    arguments = {}
    for node, po in graph.items():
        if _first({node: po}, "transformArgumentKey") == "source":
            arguments[node] = _first({node: po}, "transformArgumentValue")
    for po in graph.values():
        if _first({"": po}, "transformType") == "fetch":
            for a in po.get(ES + "transformArgument", []):
                if arguments.get(a["value"]):
                    return arguments[a["value"]]
    return ""


def _raw(previous):
    catalogs = _search(r"rdfType:http\://www.w3.org/ns/dcat#Catalog")
    pipelines = _search("graphType:Pipeline")
    results = _search("graphType:PipelineResult AND tag.literal:latest")
    sources = {}

    def source(e):
        try:
            return _source_url(e["contextId"], e["entryId"])
        except Exception as error:  # noqa: BLE001 - keep the URL the last build knew for this context
            skip("dataportal pipeline", e.get("contextId"), error)
            return previous[e["contextId"]]["source"] if e.get("contextId") in previous else None

    # One resource per pipeline, several hundred of them: read a few at a time, in order.
    with ThreadPoolExecutor(max_workers=8) as pool:
        for e, url in zip(pipelines, pool.map(source, pipelines)):
            if url is not None:
                sources[e["contextId"]] = url
    return json.dumps({"catalogs": catalogs, "pipelines": pipelines, "results": results, "sources": sources},
                      ensure_ascii=False).encode()


def fetch(cache: Path, previous=None):
    """``previous`` is the last snapshot: a pipeline whose resource cannot be read keeps its URL from there."""
    raw = json.loads(cached(cache, "dataportal_store.json", lambda: _raw(previous or {})).read_text(encoding="utf-8"))
    out = {}
    for e in raw["catalogs"]:
        try:
            md = e.get("metadata") or {}
            types = [v["value"] for po in md.values() for v in po.get("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", [])]
            if "http://www.w3.org/ns/dcat#Catalog" not in types:
                continue
            out[e["contextId"]] = {"title": _first(md, "dc/terms/title"), "description": _first(md, "dc/terms/description"),
                                   "publisher": _first(md, "dc/terms/publisher"), "homepage": _first(md, "foaf/0.1/homepage"),
                                   "license": _first(md, "dc/terms/license"), "source": "", "run": None}
        except Exception as error:  # noqa: BLE001
            skip("dataportal catalog", e.get("contextId"), error)
    for e in raw["pipelines"]:
        try:
            entry = out.setdefault(e["contextId"], {"title": _first(e.get("metadata") or {}, "dc/terms/title"), "description": "",
                                                    "publisher": "", "homepage": "", "license": "", "source": "", "run": None})
            entry["source"] = entry["source"] or raw["sources"].get(e["contextId"], "")
        except Exception as error:  # noqa: BLE001
            skip("dataportal pipeline", e.get("contextId"), error)
    for e in raw["results"]:
        try:
            info, md = e.get("info") or {}, e.get("metadata") or {}
            run = {"status": _first(info, ES + "status").rsplit("/", 1)[-1], "date": _first(info, "dc/terms/modified")[:10],
                   "datasets": int(_first(md, PR + "mergeMainResourceCount") or 0),
                   "errors": int(_first(md, PR + "validateErrors") or 0) + int(_first(md, PR + "validateMandatoryMissing") or 0)}
            entry = out.get(e["contextId"])
            if entry and (not entry["run"] or run["date"] > entry["run"]["date"]):
                entry["run"] = run
        except Exception as error:  # noqa: BLE001
            skip("dataportal result", e.get("contextId"), error)
    return dict(sorted(out.items(), key=lambda kv: (not kv[0].isdigit(), int(kv[0]) if kv[0].isdigit() else 0, kv[0])))
