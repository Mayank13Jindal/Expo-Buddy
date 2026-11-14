import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from app.exports.schema import FIELDS


def write(path, tables, fields, *, info=True):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for table, rows in tables.items():
        sheet = workbook.create_sheet(table.title())
        sheet.append([FIELDS[table][field] for field in fields[table]])
        for row in rows:
            sheet.append(
                [
                    re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(row.get(field, "")))
                    for field in fields[table]
                ]
            )
            for cell in sheet[sheet.max_row]:
                cell.data_type = "s"  # Never let a printed/user value become a formula.
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="205C47")
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                60, max(18, len(str(column[0].value)) + 5)
            )
    if info:
        sheet = workbook.create_sheet("Export info")
        sheet.append(["Expo Buddy", "Private snapshot; all source strings are text cells."])
        sheet.append(
            ["Multi-value separator", " | ; values retain labels. Personal notes use newlines."]
        )
        sheet.append(["Source links", "App links need login. ZIP originals are not redacted."])
        sheet.column_dimensions["A"].width = 26
        sheet.column_dimensions["B"].width = 85
    workbook.save(path)
