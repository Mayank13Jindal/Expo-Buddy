def escape(value):
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def fold(line):
    lines, part, length = [], "", 0
    for char in line:
        size = len(char.encode("utf-8"))
        if length + size > 75:
            lines.append(part)
            part, length = " ", 1
        part += char
        length += size
    return "\r\n".join([*lines, part])


def write(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as stream:
        for row in rows:
            name = row.get("full_name", "") or row.get("company_name", "") or "Unnamed contact"
            lines = [
                "BEGIN:VCARD",
                "VERSION:3.0",
                "FN:" + escape(name),
                "N:;" + escape(name) + ";;;",
            ]
            for field, prop in (
                ("company_name", "ORG"),
                ("designation", "TITLE"),
                ("notes", "NOTE"),
            ):
                if field in fields and row.get(field):
                    lines.append(prop + ":" + escape(row[field]))
            for number, channel in enumerate(row.get("_vcard_channels", []), 1):
                kind, raw, label = (
                    channel["kind"],
                    escape(channel["raw"]),
                    channel.get("label", "Work"),
                )
                prop = {"phone": "TEL", "email": "EMAIL", "web": "URL", "address": "ADR"}.get(kind)
                if not prop:
                    continue
                if kind == "address":
                    raw = ";;" + raw + ";;;;"
                label_type = (
                    "CELL"
                    if label.casefold() in ("mobile", "cell")
                    else "HOME"
                    if label.casefold() == "home"
                    else "WORK"
                )
                lines += [
                    f"item{number}.{prop};TYPE={label_type}:{raw}",
                    f"item{number}.X-ABLabel:{escape(label)}",
                ]
            if row.get("review_warning"):
                lines.append("NOTE:" + escape("Review warning: " + row["review_warning"]))
            lines.append("END:VCARD")
            stream.write("\r\n".join(fold(line) for line in lines) + "\r\n")
