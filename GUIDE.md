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
| `label` | name by language, as a register or an edit gives it; a data.europa.eu host with exactly one data service carries that service's title. Absent when nothing names the install |
| `software` | id in `software.json`; `custom` is an edit's statement that the install is a one-off. Absent when nothing says what it runs on |
| `owner` | organisation id the data belongs to | registers, edits |
| `operator` | organisation id that runs the install when it is not the owner (MetaSolutions for `*.entryscape.net`) | edits |
| `endpoint[]` | how to talk to it: `protocol` (id in `protocols.json`), `url`, `language[]`, optional `support` override, `checked {date, result, detail}` | registers, edits, check |
| `status` | the best result among the endpoints: `ok`, `restricted`, `error`, `unreachable`, `unchecked`; set by the build from the check and dataportal.se's harvest | check, dataportal |
| `description` | short text by language, as the registers give it | registers, edits |
| `license` | licence URI the catalog declares for its contents as a whole | registers, edits |
| `homepage` | the human page | registers, edits |
| `identifier` | `dataportal` (the catalog's context on admin.dataportal.se), `data_europa` (catalogue id) | registers |
| `same_as` | other URIs that denote the same install | registers, edits |
| `source` | which registers and edits contributed | build |
| `note` | free text | edits |

A catalog says what it runs on and how to talk to it, never what it is or what
records come out. There is no type field: what an endpoint yields (tables,
indicators, layers, studies, files …) is decided by the collector that reads the
protocol, and is modelled there. "Every PxWeb" is `software`, "every WFS" is
`endpoint.protocol`; a classification beyond those two would be this repo asserting
something about content it cannot see.

### `protocols.json`

Hand-maintained vocabulary of ways to talk to a catalog, following
`schema/protocol.schema.json`. One protocol is one collector adapter: adding a
catalog never needs code unless its protocol is new.

| field | meaning |
|---|---|
| `id` | adapter name, e.g. `pxweb_v2`, `entrystore`, `wfs_2` |
| `support` | `supported` (an adapter exists), `planned`, `deferred`, `none`, `undecided` |

Every Swedish-owned PxWeb install is recorded, also those whose API is disabled or
broken (`pxweb_web`), and sites that show tables without any API (`web`): a scraper
for them may come, and the records are not to be lost meanwhile. Only duplicates,
dead predecessors and demo installs go in `ignore`.

The `support` column is the roadmap. The registry lists what exists in Sweden
whether or not we read it yet.

### `software.json`

Hand-maintained vocabulary of products catalogs run on, following
`schema/software.schema.json`: id, label, the protocols an install of it exposes,
the vendor's organisation id when it is a Swedish organisation, homepage, source
repository and API documentation. It answers "what does it run on"; the endpoints
answer "how do we talk to it". The two are kept apart because one product speaks
several protocols (PxWeb: API 1, API 2, the web tables) and one protocol is spoken
by several products (WFS by GeoServer, ArcGIS and QGIS Server; DCAT-AP by
everything). The report lists every install that carries none of its software's
protocols (`without_software_protocol`): a map viewer whose services are not yet
recorded, or a misclassified install.

## The input you edit

### `edits/catalogs.json`

The only hand file for catalogs. Merged last, so it wins over every register.

```json
{"catalog": {"statistik.csn.se": {"label": {"sv": "CSN:s statistikdatabas"}, "software": "pxweb", "owner": "SE2021001819",
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
| [data.europa.eu](https://data.europa.eu/api/hub/search/) | the hub search for the three Swedish catalogues (oppnadata, geodata-se, nsip-se): every service host that datasets and data services point at, classified by protocol from the URL, with the publisher URIs seen there and, when the host carries exactly one data service, that service's title as the catalog's label. Mostly Geodataportalen's OGC services and Atom feeds, plus the APIs registered on dataportal.se |
| [dataportal.se](https://admin.dataportal.se/store) | the federation: each registered catalog's title, publisher and homepage, the URL the portal harvests it from, and the latest harvest's status, date, dataset count and validation errors. That harvest outcome is written as the `dcat_ap` endpoint's `checked` |

Every dataportal.se registration with a URL to harvest from is a catalog, also the
guessed `www.<body>.se/datasets/dcat` URLs the portal pre-registered for every
public body: what the registration is worth shows in its status. The harvest
outcome is the `dcat_ap` endpoint's `checked` (`ok` only when a harvest succeeded
with at least one dataset, `error` with the run's counts otherwise); a
registration the portal never ran is probed by the liveness check like any other
endpoint. A context in a shared install (`free.entryscape.com`,
`editera.dataportal.se`) is its own catalog, keyed by host and the context's number
in that install, with MetaSolutions or Digg as operator and only the RDF export as
endpoint. Only test registrations and duplicates go in `ignore`.

## The liveness check

After the registers and edits are merged, the build asks every endpoint the question
its protocol defines (`CHECK` in `scripts/check.py`: a path appended to the URL and a
substring expected in the first 64 KB of the answer; a protocol without an entry is
fetched as is) and writes the outcome as the endpoint's `checked`:

| result | meaning |
|---|---|
| `ok` | answered as the protocol says |
| `restricted` | 401 or 403: alive, but behind a key |
| `error` | answered, but not as the protocol says, or a 4xx/5xx |
| `unreachable` | no answer at all |

`checked.date` is when the current result was first observed, so a weekly run that
finds nothing changed rewrites nothing. A `dcat_ap` endpoint harvested by
dataportal.se keeps the portal's own harvest outcome instead. The catalog's `status`
is the best result among its endpoints in the order above, or `unchecked`. When most
endpoints are unreachable the network is judged broken: previous results are kept
and the report says the check failed. `python scripts/build.py --no-check` skips it
and keeps the previous results.

## Derived

| path | what |
|---|---|
| `snapshots/<register>.json` | the reduced result of the last successful fetch of each register, committed so a build still runs when a register is down |
| `dist/<product>.json`, `dist/<product>.csv` | the three product files in every published format: a copy of the JSON and a CSV with one row per record, same name, only the extension differs. Nested fields are dotted columns (`label.sv`), lists are `\|`-joined, and a list of objects gives one column per field with the items aligned by position (`endpoint.protocol`, `endpoint.url`). Derived from the JSON, so it changes exactly when the product does |
| `reports/<date>.json` | written by a build that changed a catalog or found a register with no snapshot: per register `fetched`, `stale` or `failed`, counts by software, protocol and status, added and removed ids, catalogs `without_owner`, `without_label`, `without_software` and `without_software_protocol` (the worklists for edits). `generated` in `catalogs.json` is the date of the last content change |

## Build and check

```sh
python scripts/build.py     # fetch registers, rewrite catalogs.json, dist/, snapshots/, reports/
python scripts/export.py catalogs.json protocols.json software.json  # rewrite dist/ alone
python scripts/validate.py  # schemas and references across all files; run before committing
```

Failures are contained at three levels. A request that gets a rate limit, a gateway
error or a network failure is retried a few times with a growing pause. A row a
register cannot read, or that the build cannot apply, is skipped and logged, counted
as `skipped` under that register in the report, and the other rows go through; a
dataportal.se pipeline whose resource cannot be read keeps the URL the last snapshot
had. A register that still cannot be fetched is replaced by its snapshot and reported
as `stale`; only when every register fails does the build exit non-zero. The `dist/`
export failing never fails the build; the report says so. Builds are deterministic,
so a diff means a register or an edit changed. The workflow runs weekly and commits
only when something changed.
