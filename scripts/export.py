"""Write the products to exports/ in every format we publish: a copy of the JSON and a CSV.

A product is a JSON file whose records sit in one dict keyed by id (``{"catalog": {…}}``
or the dict itself). The CSV holds one row per record with the same name as the JSON and
only the extension changed, so a reader picks the format, never the file. Nested
objects become dotted columns (``label.sv``), lists are joined with ``|``, and a list of
objects becomes one dotted column per field with the items' values aligned by position
(``endpoint.protocol`` and ``endpoint.url`` read pairwise). Everything is derived
deterministically from the JSON, so exports/ changes exactly when the product does.
"""
import csv
import io
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPORTS = ROOT / "exports"
LIST = "|"
INNER = ","


def records(data):
    """The id-keyed dict of records inside a product file."""
    tables = [v for v in data.values() if isinstance(v, dict) and v and all(isinstance(r, dict) for r in v.values())]
    wrapped = len(tables) == 1 and (len(data) > 1 or not all(isinstance(r, dict) for r in tables[0].values()) or "id" in next(iter(tables[0].values())))
    return tables[0] if wrapped else data


def _cell(value, sep=LIST):
    if value is None or value is False:
        return "" if value is None else "false"
    if value is True:
        return "true"
    if isinstance(value, list):
        return sep.join(_cell(v, INNER) for v in value)
    return str(value)


def flatten(record, prefix=""):
    """One record as {column: text}."""
    out = {}
    for key, value in record.items():
        column = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, column + "."))
        elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
            items = [flatten(v) for v in value]
            for sub in sorted({c for item in items for c in item}):
                out[f"{column}.{sub}"] = LIST.join(item.get(sub, "") for item in items)
        else:
            out[column] = _cell(value)
    return out


def to_csv(table):
    rows = [flatten(r) for r in table.values()]
    columns = ["id"] + sorted({c for r in rows for c in r} - {"id"})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: row.get(c, "") for c in columns})
    return buffer.getvalue()


def export(*products: Path):
    EXPORTS.mkdir(exist_ok=True)
    for path in products:
        shutil.copyfile(path, EXPORTS / path.name)
        table = records(json.loads(path.read_text(encoding="utf-8")))
        (EXPORTS / path.with_suffix(".csv").name).write_text(to_csv(table), encoding="utf-8")


if __name__ == "__main__":
    export(*(ROOT / name for name in sys.argv[1:]))
