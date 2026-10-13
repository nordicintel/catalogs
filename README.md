# catalogs

Registry of the catalogs, APIs and services that publish Swedish statistics and data: what each one runs on, how to reach it, whether it answers, and which organisation owns it.

- `catalogs.json` is the registry: one record per install with software, owner, endpoints by protocol, and the result of the last check.
- `protocols.json` is the vocabulary of ways to talk to a catalog; one protocol is one collector adapter, and its `support` value is the roadmap.
- `software.json` is the vocabulary of products catalogs run on.
- `dist/` holds the three products as JSON and CSV.

Owners are ids from [nordicintel/organisations](https://github.com/nordicintel/organisations). Built weekly by a workflow, standard library only, no API keys. Every file and field: [GUIDE.md](GUIDE.md).
