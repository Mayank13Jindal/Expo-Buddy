from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.api.dependencies import aware
from app.db.library import Owner, now
from app.db.operations import Backup
from app.domain.jobs import enqueue

DEFAULTS = {"enabled": True, "hour": 2, "minute": 0, "daily_keep": 7, "weekly_keep": 4}


def configuration(db):
    owner = db.scalar(select(Owner))
    return {**DEFAULTS, **(owner.settings.get("backup", {}) if owner else {})}


def queue(db, *, trigger="manual"):
    row = Backup(trigger=trigger)
    db.add(row)
    db.flush()
    enqueue(db, "backup", row.id, 1)
    return row


def status(db):
    latest = db.scalar(select(Backup).order_by(Backup.created_at.desc()).limit(1))
    complete = db.scalar(
        select(Backup)
        .where(Backup.state == "complete", Backup.finished_at.is_not(None))
        .order_by(Backup.finished_at.desc())
        .limit(1)
    )
    return {
        "state": latest.state if latest else "never_run",
        "last_success": complete.finished_at if complete else None,
        "last_error": latest.error if latest and latest.state == "failed" else None,
        "warning": not complete
        or aware(complete.finished_at) < now() - timedelta(days=7)
        or bool(latest and latest.state == "failed"),
    }


def schedule(db, settings, current=None):
    current = current or now()
    config = configuration(db)
    if not config["enabled"] or not db.scalar(select(Owner.id)):
        return None
    local = current.astimezone(ZoneInfo(settings.app_timezone))
    if (local.hour, local.minute) < (config["hour"], config["minute"]):
        return None
    today = local.date()
    for row in db.scalars(
        select(Backup)
        .where(Backup.trigger == "nightly")
        .order_by(Backup.created_at.desc())
        .limit(10)
    ):
        if aware(row.created_at).astimezone(ZoneInfo(settings.app_timezone)).date() == today:
            return None
    row = queue(db, trigger="nightly")
    row.created_at = current
    return row


def retained(rows, daily=7, weekly=4):
    keep, days, weeks = set(), set(), set()
    for row in sorted(rows, key=lambda item: aware(item.finished_at), reverse=True):
        date = aware(row.finished_at).date()
        week = date.isocalendar()[:2]
        if date not in days and len(days) < daily:
            keep.add(row.id)
            days.add(date)
        if week not in weeks and len(weeks) < weekly:
            keep.add(row.id)
            weeks.add(week)
    return keep
