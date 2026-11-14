import csv

from app.exports.schema import FIELDS


def safe(value):
    value = str(value)
    return (
        "'" + value
        if value.startswith(("=", "+", "-", "@", "\t", "\r"))
        or value.lstrip().startswith(("=", "+", "-", "@"))
        else value
    )


def write(path, table, rows, fields, *, bom=True, spreadsheet_safe=True):
    with path.open("w", encoding="utf-8-sig" if bom else "utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([FIELDS[table][field] for field in fields])
        for row in rows:
            writer.writerow(
                [
                    safe(row.get(field, "")) if spreadsheet_safe else str(row.get(field, ""))
                    for field in fields
                ]
            )
