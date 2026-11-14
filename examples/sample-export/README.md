# Fictional sample exports

Everything in these files is generated demonstration data. Names, companies, email addresses, numbers, notes, cards and brochures are fictional. The `example.invalid` links intentionally do not resolve.

- `fictional-sample.xlsx`: Contacts, Companies, Documents and Info sheets, with two people and a second company that has a brochure but no people.
- `fictional-sample.csv`: Contacts in the same field order, UTF-8 with BOM and spreadsheet-safe quoting/prefixes.
- `fictional-sample.vcf`: Two vCard 3.0 records with labelled mobile/office numbers and work emails.

Personal notes are deliberately selected in this sample. A leading-zero office number, multiline note, comma and literal `=SUM(1)` designation demonstrate text handling. Excel stores the designation as text; safe CSV prefixes formula-like values with an apostrophe. Deselecting table fields does not redact information printed on originals or in brochure source text.

Generate all formats, including the ZIP with fictional originals, using `make sample-export` after `make dev-install`. The generator uses an isolated temporary SQLite database and generated source files; it never connects to the configured database, provider or library storage. It verifies package hashes and counts before copying these outputs here. UUIDs and creation timestamps change on regeneration.
