from uuid import UUID

from pydantic import BaseModel, Field, model_validator

FIELDS = {
    "contacts": {
        "expo": "Expo",
        "company_name": "Company",
        "full_name": "Person",
        "designation": "Designation",
        "department": "Department",
        "phones": "Phones",
        "emails": "Emails",
        "websites": "Websites",
        "addresses": "Addresses",
        "products": "Products",
        "services": "Services",
        "categories": "Categories",
        "business_role": "Business role",
        "description": "Description",
        "notes": "Personal notes",
        "tags": "Tags",
        "files": "Source links",
        "id": "Contact ID",
    },
    "companies": {
        "expo": "Expo",
        "company_name": "Company",
        "phones": "Phones",
        "emails": "Emails",
        "websites": "Websites",
        "addresses": "Addresses",
        "products": "Products",
        "services": "Services",
        "categories": "Categories",
        "business_role": "Business role",
        "description": "Description",
        "notes": "Personal notes",
        "tags": "Tags",
        "files": "Source links",
        "id": "Company ID",
    },
    "documents": {
        "expo": "Expo",
        "company_name": "Company",
        "title": "Title",
        "type": "Document type",
        "processing_state": "Processing",
        "review_state": "Review",
        "notes": "Personal notes",
        "tags": "Tags",
        "files": "Source links",
        "id": "Document ID",
    },
}


for table in FIELDS.values():
    table["review_warning"] = "Review warning"


class Selection(BaseModel):
    allow_unreviewed: bool = False
    scope: str = Field(default="active", pattern="^(active|expos|selected|all|search)$")
    expo_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=20000)
    company_ids: list[UUID] = Field(default_factory=list, max_length=10000)
    query: str = Field(default="", max_length=500)
    filters: dict = Field(default_factory=dict)
    tables: list[str] = Field(default=["contacts"], min_length=1, max_length=3)
    fields: dict[str, list[str]] = Field(
        default={
            "contacts": ["expo", "company_name", "full_name", "designation", "phones", "emails"]
        }
    )
    format: str = Field(default="xlsx", pattern="^(xlsx|csv|vcf|zip)$")
    csv_bom: bool = True
    csv_safe: bool = True
    include_csv: bool = True
    include_vcard: bool = False
    info_sheet: bool = True

    @model_validator(mode="after")
    def valid_selection(self):
        self.tables = list(dict.fromkeys(self.tables))
        if any(
            table not in FIELDS
            or not self.fields.get(table)
            or len(self.fields[table]) > len(FIELDS[table])
            or len(set(self.fields[table])) != len(self.fields[table])
            or any(field not in FIELDS[table] for field in self.fields[table])
            for table in self.tables
        ):
            raise ValueError("Choose valid tables and fields without duplicates.")
        if self.format == "csv" and len(self.tables) != 1:
            raise ValueError("Choose one table for CSV, or ZIP for multiple tables.")
        if (self.format == "vcf" or self.include_vcard) and "contacts" not in self.tables:
            raise ValueError("Include the Contacts table for a vCard export.")
        if self.scope == "expos" and not self.expo_ids:
            raise ValueError("Choose at least one expo.")
        if self.scope == "selected" and not (self.document_ids or self.company_ids):
            raise ValueError("Select some records first.")
        if self.scope == "search" and not self.query.strip():
            raise ValueError("Enter a search query.")
        return self
