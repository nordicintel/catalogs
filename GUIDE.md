# Guide to the files

Three files are the product. Everything else either feeds them or is derived from them.
Owners and operators are ids from [nordicintel/organisations](https://github.com/nordicintel/organisations);
this repo reads that product and never writes to it.

## The product

### `catalogs.json`

Generated. Never edit by hand; the next build overwrites it.

```json
{"generated": "2026-10-13", "count": 83, "catalog": {"statistikdatabasen.scb.se": {…}, …}}
```

One object per install, keyed by id, following `schema/catalog.schema.json`.
An install is one running catalog, database or API: SCB has one record for
Statistikdatabasen, one for hvduppdrag and will have one for its geodata.

| field | meaning | from |
|---|---|---|
| `id` | host of the canonical URL, plus the first path segment when one host carries several installs; lower case, no scheme, no `www.` | derived |
| `label` | name by language | registers, edits |
| `type` | `statistics_database`, `indicator_database`, `open_data_portal`, `geoportal`, `research_repository`, `api`, `file_collection`, `other` | edits, registers |
| `software` | id in `software.json` | edits, check |
| `owner` | organisation id the data belongs to | registers, edits |
| `operator` | organisation id that runs the install when it is not the owner (MetaSolutions for `*.entryscape.net`) | edits |
| `endpoint[]` | how to talk to it: `protocol` (id in `protocols.json`), `url`, `language[]`, optional `support` override, `checked {date, result, detail}` | registers, edits, check |
| `status` | `active`, `inactive`, `unknown`; set by the liveness check below | check |
| `homepage` | the human page | registers, edits |
| `identifier` | `dataportal` (the catalog's context on admin.dataportal.se), `data_europa` (catalogue id) | registers |
| `same_as` | other URIs that denote the same install | registers, edits |
| `source` | which registers and edits contributed | build |
| `note` | free text | edits |

A catalog says how to talk to it, never what records come out. What an
endpoint yields (tables, indicators, layers, studies, files …) is decided by the
collector that reads the protocol, and is modelled there.

### `protocols.json`

Hand-maintained vocabulary of ways to talk to a catalog, following
`schema/protocol.schema.json`. One protocol is one collector adapter: adding a
catalog never needs code unless its protocol is new.

| field | meaning |
|---|---|
| `id` | adapter name, e.g. `pxweb_v2`, `entrystore`, `wfs_2` |
| `support` | `supported` (an adapter exists), `planned`, `deferred`, `none`, `undecided` |
| `check` | the request the liveness check appends to an endpoint URL and the substring a live answer contains |

Every Swedish-owned PxWeb install is recorded, also those whose API is disabled or
broken (`pxweb_web`), and sites that show tables without any API (`web`): a scraper
for them may come, and the records are not to be lost meanwhile. Only duplicates,
dead predecessors and demo installs go in `ignore`.

The `support` column is the roadmap. The registry lists what exists in Sweden
whether or not we read it yet.

### `software.json`

Hand-maintained vocabulary of products catalogs run on, following
`schema/software.schema.json`: id, label, homepage, and the vendor's
organisation id when it is a Swedish organisation. It answers "what does it run
on"; the endpoints answer "how do we talk to it". The two are kept apart
because one product speaks several protocols (PxWeb: API 1, API 2, the web
tables) and one protocol is spoken by several products (WFS by GeoServer,
ArcGIS and QGIS Server; DCAT-AP by everything). Which protocols a software
speaks is read off `catalogs.json`, not declared here.

## The input you edit

### `edits/catalogs.json`

The only hand file for catalogs. Merged last, so it wins over every register.

```json
{"catalog": {"statistik.csn.se": {"label": {"sv": "CSN:s statistikdatabas"}, "type": "statistics_database",
                                   "software": "pxweb", "owner": "SE2021001819",
                                   "endpoint": [{"protocol": "pxweb_v1", "url": "https://statistik.csn.se/PXWeb/api/v1", "language": ["sv"]}]}},
 "ignore": ["https://example.se/dead-registration"]}
```

- A key with a full record creates the catalog; a key with a few fields patches one a register gives.
- Any field may be set except `id`, `source` and `status`. `label` and `identifier`
  merge per key, `endpoint` merges per (protocol, url), `same_as` is a union, everything else overrides.
- `ignore` lists ids or URLs a register offers that are not catalogs: dead
  registrations, duplicates, test installs, so nobody re-investigates them.
- Owner and operator must exist in `organisations.json`. If one is missing, add
  it there first.

## Registers

| register | gives |
|---|---|
| [organisations](https://github.com/nordicintel/organisations) | every organisation id with label, homepage and the URIs the portals use for it; owners and operators resolve against it by URI, then name, then registrable domain |
| [data.europa.eu](https://data.europa.eu/api/hub/search/) | the hub search for the three Swedish catalogues (oppnadata, geodata-se, nsip-se): every service host that datasets and data services point at, classified by protocol from the URL, with the publisher URIs seen there. Mostly Geodataportalen's OGC services and Atom feeds, plus the APIs registered on dataportal.se |
| [dataportal.se](https://admin.dataportal.se/store) | the federation: each registered catalog's title, publisher and homepage, the URL the portal harvests it from, and the latest harvest's status, date, dataset count and validation errors. That harvest outcome is written as the `dcat_ap` endpoint's `checked` |

A dataportal.se registration becomes a catalog only once a harvest has succeeded
with at least one dataset; the portal pre-registered a guessed URL for every public
body and most of those have never answered. The report counts them as
`registered_only`. A catalog that is already in the product stays and turns
`inactive` when its harvest fails, so a bad week does not make it vanish. A
context in a shared install (`free.entryscape.com`, `editera.dataportal.se`) is
its own catalog, keyed by host and the context's number in that install, with
MetaSolutions or Digg as operator and only the RDF export as endpoint.

## The liveness check

After the registers and edits are merged, the build asks every endpoint the question
its protocol defines (`check.path` appended to the URL, `check.expect` in the first
64 KB of the answer) and writes the outcome as the endpoint's `checked`:

| result | meaning |
|---|---|
| `ok` | answered as the protocol says |
| `restricted` | 401 or 403: alive, but behind a key |
| `error` | answered, but not as the protocol says, or a 4xx/5xx |
| `unreachable` | no answer at all |

`checked.date` is when the current result was first observed, so a weekly run that
finds nothing changed rewrites nothing. A `dcat_ap` endpoint harvested by
dataportal.se keeps the portal's own harvest outcome instead. A catalog is `active`
when any endpoint is `ok` or `restricted`, `inactive` when every checked endpoint
failed, `unknown` when nothing could be checked. When most endpoints are unreachable
the network is judged broken: previous results are kept and the report says the
check failed. `python scripts/build.py --no-check` skips it.

## Derived

| path | what |
|---|---|
| `snapshots/<register>.json` | the reduced result of the last successful fetch of each register, committed so a build still runs when a register is down |
| `dist/<product>.json`, `dist/<product>.csv` | the three product files in every published format: a copy of the JSON and a CSV with one row per record, same name, only the extension differs. Nested fields are dotted columns (`label.sv`), lists are `\|`-joined, and a list of objects gives one column per field with the items aligned by position (`endpoint.protocol`, `endpoint.url`). Derived from the JSON, so it changes exactly when the product does |
| `reports/<date>.json` | written by a build that changed a catalog or found a register with no snapshot: per register `fetched`, `stale` or `failed`, counts by type and protocol, added and removed ids, catalogs `without_owner` (the worklist for edits), registrations not yet counted as catalogs. `generated` in `catalogs.json` is the date of the last content change |

## Build and check

```sh
python scripts/build.py     # fetch registers, rewrite catalogs.json, dist/, snapshots/, reports/
python scripts/export.py catalogs.json protocols.json software.json  # rewrite dist/ alone
python scripts/validate.py  # schemas and references across all files; run before committing
```

A register that cannot be fetched is replaced by its snapshot and reported as
`stale`; only when every register fails does the build exit non-zero. Builds are
deterministic, so a diff means a register or an edit changed. The workflow runs
weekly and commits only when something changed.
