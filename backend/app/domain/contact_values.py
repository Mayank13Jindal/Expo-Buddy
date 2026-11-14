"""Contact syntax and identity checks; these do not prove ownership or deliverability."""

import re

import phonenumbers
from email_validator import EmailNotValidError, validate_email


def normalise_channel(kind: str, raw: str, region: str | None = None) -> str:
    raw = raw.strip()
    if kind == "phone":
        international = "+" + raw[2:] if raw.startswith("00") else raw
        try:
            number = phonenumbers.parse(international, region or None)
            if (
                phonenumbers.is_possible_number_with_reason(number)
                == phonenumbers.ValidationResult.IS_POSSIBLE
            ):
                value = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
                return value + ("x" + number.extension if number.extension else "")
        except phonenumbers.NumberParseException:
            pass
        return re.sub(r"\D", "", raw)
    if kind == "email":
        try:
            return validate_email(raw, check_deliverability=False).normalized.casefold()
        except EmailNotValidError:
            return raw.casefold()
    return " ".join(raw.casefold().split())


def channel_issue(value: dict, region: str | None = None) -> str:
    kind, raw = value.get("kind"), value.get("raw", "")
    if not isinstance(raw, str) or not raw.strip():
        return "Empty contact value."
    if kind == "email":
        try:
            validate_email(raw.strip(), check_deliverability=False)
        except EmailNotValidError:
            return "Invalid email syntax. Correct it against the source before accepting."
    elif kind == "phone":
        digits = re.sub(r"\D", "", raw)
        if not 7 <= len(digits) <= 15:
            return "Phone number has an implausible length. Check the source and country code."
        if raw.strip().startswith(("+", "00")) or region:
            try:
                if not phonenumbers.is_possible_number(
                    phonenumbers.parse(
                        "+" + raw.strip()[2:] if raw.strip().startswith("00") else raw,
                        region or None,
                    )
                ):
                    return "Phone number is not possible for this country code."
            except phonenumbers.NumberParseException:
                return "Phone number could not be parsed. Check the country code."
    elif kind == "web":
        from urllib.parse import urlsplit

        try:
            url = urlsplit(raw if "://" in raw else "https://" + raw)
        except ValueError:
            return "Invalid website address."
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or "." not in url.hostname
            or any(char.isspace() for char in raw)
        ):
            return "Invalid website address."
    elif kind != "address":
        return "Unsupported contact field."
    return ""


def channel_key(value: dict, region: str | None = None):
    return value.get("kind"), normalise_channel(value.get("kind", ""), value.get("raw", ""), region)


def contact_owner_issue(db, owner_type, owner_id, value, region=None):
    if owner_type != "contact" or value.get("kind") not in ("phone", "email"):
        return ""
    from sqlalchemy import select

    from app.db.intelligence import Contact

    target = db.get(Contact, owner_id)
    for other in db.scalars(
        select(Contact).where(
            Contact.company_id == target.company_id,
            Contact.id != owner_id,
            Contact.deleted_at.is_(None),
        )
    ):
        if any(
            channel_key(channel, region) == channel_key(value, region) for channel in other.channels
        ):
            return f"Already assigned to {other.full_name or 'another person'}. Check ownership beside the source and correct the person records before accepting."
    return ""


def person_evidence_issue(db, person, value):
    if value.get("kind") not in ("phone", "email") or not person.source_document_id:
        return ""
    from sqlalchemy import select

    from app.db.intelligence import Contact

    people = list(
        db.scalars(
            select(Contact).where(
                Contact.source_document_id == person.source_document_id,
                Contact.deleted_at.is_(None),
            )
        )
    )
    if len(people) < 2:
        return ""
    quote = " ".join(value.get("evidence", {}).get("quote", "").casefold().split())
    name = " ".join(person.full_name.casefold().split())
    if (
        not name
        or name not in quote
        or any(
            other.id != person.id
            and other.full_name
            and " ".join(other.full_name.casefold().split()) in quote
            for other in people
        )
    ):
        return "Person-specific evidence is missing on this multi-person card. Keep this value unassigned and correct the person beside the source after checking ownership."
    return ""
