from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

OSLO_TIMEZONE = ZoneInfo("Europe/Oslo")


def alert_sent_today(subscription_id, database, now=None):
    now = now or datetime.now(timezone.utc)
    oslo_today = now.astimezone(OSLO_TIMEZONE).date()
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        timestamps = connection.execute(
            "SELECT sent_at FROM vakt_sent_jobs WHERE subscription_id=?",
            (subscription_id,),
        ).fetchall()
    for (sent_at,) in timestamps:
        try:
            timestamp = datetime.fromisoformat(sent_at)
        except (TypeError, ValueError, OverflowError):
            continue
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            continue
        if timestamp.astimezone(OSLO_TIMEZONE).date() == oslo_today:
            return True
    return False