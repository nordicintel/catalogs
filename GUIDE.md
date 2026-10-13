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
| `status` | `active`, `inactive`, `unknown`; set by the liveness check | check |
| `homepage` | the human page | registers, edits |
| `identifier` | `dataportal` (the catalog's context on admin.dataportal.se), `data_europa` (catalogue id) | registers |
| `same_as` | other URIs that denote the same install | registers, edits |
| `source` | which registers and edits contributed | build |
| `note` | free text | edits |

A catalog has protocols, never kinds. What kind of record an endpoint yields
(table, indicator, layer, study, file …) is the protocol's business and is set
by the collector that reads it.

### `protocols.json`

Hand-maintained vocabulary of ways to talk to a catalog, following
`schema/protocol.schema.json`. One protocol is one collector adapter: adding a
catalog never needs code unless its protocol is new.

| field | meaning |
|---|---|
| `id` | adapter name, e.g. `pxweb_v2`, `entrystore`, `wfs_2` |
| `kind[]` | what a collector reading it produces: `table`, `indicator`, `timeseries`, `layer`, `study`, `file`, `collection`, `dataset` |
| `support` | `supported` (an adapter exists), `planned`, `deferred`, `none`, `undecided` |
| `check` | the request the liveness check appends to an endpoint URL and the substring a live answer contains |

The `support` column is the roadmap. The registry lists what exists in Sweden
whether or not we read it yet.

### `software.json`

Hand-maintained vocabulary of products catalogs run on, following
`schema/software.schema.json`: id, label, the protocols an install normally
exposes, and the vendor's organisation id when it is a Swedish organisation.
It is a lookup, not a product model.

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

## Derived

| path | what |
|---|---|
| `snapshots/<register>.json` | the reduced result of the last successful fetch of each register, committed so a build still runs when a register is down |
| `reports/<date>.json` | written by a build that changed a catalog or found a register with no snapshot: per register `fetched`, `stale` or `failed`, counts by type and protocol, added and removed ids. `generated` in `catalogs.json` is the date of the last content change |

## Build and check

```sh
python scripts/build.py     # fetch registers, rewrite catalogs.json, snapshots/, reports/
python scripts/validate.py  # schemas and references across all files; run before committing
```

A register that cannot be fetched is replaced by its snapshot and reported as
`stale`; only when every register fails does the build exit non-zero. Builds are
deterministic, so a diff means a register or an edit changed. The workflow runs
weekly and commits only when something changed.
