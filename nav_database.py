"""Инициализация SQLite и явный локальный импорт JSON; без сетевых запросов."""

import sqlite3
import json
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parent / "nav_jobs.db"

# Временные метки — INTEGER: микросекунды UTC. Неизвестные значения — NULL.
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    uuid TEXT PRIMARY KEY NOT NULL CHECK (length(uuid) > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE', 'UNKNOWN')),
    status_modified_at INTEGER,
    current_version_id INTEGER,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    FOREIGN KEY (uuid, current_version_id)
        REFERENCES job_versions(job_uuid, id) DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS job_versions (
    id INTEGER PRIMARY KEY,
    job_uuid TEXT NOT NULL REFERENCES jobs(uuid),
    details_modified_at INTEGER,
    fetched_at INTEGER,
    recorded_at INTEGER NOT NULL,
    payload_hash TEXT NOT NULL CHECK (length(payload_hash) > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE', 'UNKNOWN')),
    title TEXT,
    jobtitle TEXT,
    description TEXT,
    employer_name TEXT,
    employer_orgnr TEXT,
    employer_description TEXT,
    employer_homepage TEXT,
    positioncount INTEGER CHECK (positioncount IS NULL OR positioncount >= 0),
    positioncount_raw TEXT,
    published INTEGER,
    updated INTEGER,
    expires INTEGER,
    application_due INTEGER,
    published_raw TEXT,
    updated_raw TEXT,
    expires_raw TEXT,
    application_due_raw TEXT,
    application_url TEXT,
    link TEXT,
    source_url TEXT,
    contact_list_json TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('feed', 'json_import')),
    completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'partial', 'masked')),
    UNIQUE (job_uuid, id)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_versions_known
    ON job_versions(job_uuid, details_modified_at, payload_hash)
    WHERE details_modified_at IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_versions_unknown
    ON job_versions(job_uuid, payload_hash) WHERE details_modified_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_jobs_active ON jobs(uuid) WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS ix_versions_published ON job_versions(published, job_uuid);
CREATE INDEX IF NOT EXISTS ix_versions_history ON job_versions(job_uuid, details_modified_at);

CREATE TABLE IF NOT EXISTS job_locations (
    version_id INTEGER NOT NULL REFERENCES job_versions(id) ON DELETE CASCADE,
    location_no INTEGER NOT NULL CHECK (location_no >= 0),
    country TEXT,
    fylke TEXT,
    kommune TEXT,
    fylke_key TEXT,
    kommune_key TEXT,
    city TEXT,
    postal_code TEXT,
    address TEXT,
    PRIMARY KEY (version_id, location_no)
);
CREATE INDEX IF NOT EXISTS ix_locations_region
    ON job_locations(fylke_key, kommune_key, version_id);

CREATE TABLE IF NOT EXISTS job_classifications (
    version_id INTEGER NOT NULL REFERENCES job_versions(id) ON DELETE CASCADE,
    category_type TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    description TEXT,
    score REAL,
    PRIMARY KEY (version_id, category_type, code)
);
CREATE INDEX IF NOT EXISTS ix_classifications_profession
    ON job_classifications(category_type, code, version_id);

CREATE TABLE IF NOT EXISTS job_occupation_categories (
    version_id INTEGER NOT NULL REFERENCES job_versions(id) ON DELETE CASCADE,
    level1 TEXT NOT NULL DEFAULT '',
    level2 TEXT NOT NULL DEFAULT '',
    CHECK (level1 <> '' OR level2 <> ''),
    PRIMARY KEY (version_id, level1, level2)
);
CREATE INDEX IF NOT EXISTS ix_occupation_categories
    ON job_occupation_categories(level1, level2, version_id);

CREATE TABLE IF NOT EXISTS feed_events (
    id INTEGER PRIMARY KEY,
    job_uuid TEXT NOT NULL REFERENCES jobs(uuid),
    source_event_id TEXT,
    event_modified_at INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE', 'UNKNOWN')),
    details_url TEXT,
    page_id TEXT,
    item_index INTEGER CHECK (item_index IS NULL OR item_index >= 0),
    received_at INTEGER,
    recorded_at INTEGER NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('feed', 'json_import')),
    event_fingerprint TEXT NOT NULL UNIQUE CHECK (length(event_fingerprint) > 0),
    UNIQUE (job_uuid, id)
);
CREATE INDEX IF NOT EXISTS ix_events_history ON feed_events(job_uuid, event_modified_at);

CREATE TABLE IF NOT EXISTS details_queue (
    job_uuid TEXT PRIMARY KEY NOT NULL REFERENCES jobs(uuid),
    requested_event_id INTEGER,
    requested_modified_at INTEGER,
    details_url TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK (state IN ('pending', 'in_progress', 'done', 'unavailable')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_retry_at INTEGER,
    lease_until INTEGER,
    last_error TEXT,
    last_http_status INTEGER,
    FOREIGN KEY (job_uuid, requested_event_id) REFERENCES feed_events(job_uuid, id)
);
CREATE INDEX IF NOT EXISTS ix_queue_retry ON details_queue(state, next_retry_at);
CREATE INDEX IF NOT EXISTS ix_queue_lease ON details_queue(state, lease_until);

CREATE TABLE IF NOT EXISTS feed_cursor (
    stream_name TEXT PRIMARY KEY NOT NULL,
    initial_since INTEGER NOT NULL,
    last_page_id TEXT,
    last_page_url TEXT,
    next_url TEXT,
    etag TEXT,
    last_modified TEXT,
    committed_at INTEGER,
    bootstrap_state TEXT NOT NULL DEFAULT 'not_started'
        CHECK (bootstrap_state IN ('not_started', 'in_progress', 'complete')),
    import_snapshot_id TEXT
);

CREATE TABLE IF NOT EXISTS vakt_subscriptions (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL,
    profession_query TEXT NOT NULL,
    profession_query_key TEXT NOT NULL,
    fylke TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    verified_at TEXT,
    verification_token TEXT NOT NULL,
    verification_expires_at TEXT,
    unsubscribe_token TEXT NOT NULL,
    last_checked_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vakt_verification_token
    ON vakt_subscriptions(verification_token);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vakt_unsubscribe_token
    ON vakt_subscriptions(unsubscribe_token);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vakt_subscription_identity
    ON vakt_subscriptions(email, profession_query_key, fylke);
CREATE INDEX IF NOT EXISTS ix_vakt_active_fylke
    ON vakt_subscriptions(active, fylke);

CREATE TABLE IF NOT EXISTS vakt_sent_jobs (
    id INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES vakt_subscriptions(id),
    vacancy_uuid TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE(subscription_id, vacancy_uuid)
);
CREATE INDEX IF NOT EXISTS ix_vakt_sent_jobs_subscription
    ON vakt_sent_jobs(subscription_id, vacancy_uuid);
"""


def initialize_database(path=DATABASE_PATH):
    connection = sqlite3.connect(path)
    try:
        # Настройка действует на соединение: будущие подключения должны включать её также.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("BEGIN;\n" + SCHEMA + "\nCOMMIT;")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(job_versions)")}
        if "contact_list_json" not in columns:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE job_versions ADD COLUMN contact_list_json TEXT")
            connection.commit()
        vakt_columns = {row[1] for row in connection.execute("PRAGMA table_info(vakt_subscriptions)")}
        if "verification_expires_at" not in vakt_columns:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ALTER TABLE vakt_subscriptions ADD COLUMN verification_expires_at TEXT")
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=48)).isoformat()
            connection.execute(
                "UPDATE vakt_subscriptions SET verification_expires_at=? "
                "WHERE active=0 AND verified_at IS NULL AND verification_expires_at IS NULL",
                (expires_at,),
            )
            connection.commit()
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("Нарушены внешние ключи базы.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def utc_microseconds(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if date.tzinfo is None:
        return None
    delta = date.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def insert_record(connection, table, record):
    # Имена таблиц и столбцов задаются только кодом этого модуля.
    columns = ", ".join(record)
    placeholders = ", ".join("?" for _ in record)
    return connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                              tuple(record.values())).lastrowid


def import_json(path=DATABASE_PATH, source_directory=None):
    directory = Path(source_directory) if source_directory else Path(__file__).resolve().parent
    snapshot = json.loads((directory / "nav_active_jobs.json").read_text(encoding="utf-8"))
    position = json.loads((directory / "nav_feed_position.json").read_text(encoding="utf-8"))
    if not snapshot.get("snapshot_id") or snapshot["snapshot_id"] != position.get("snapshot_id"):
        raise ValueError("JSON относятся к разным снимкам.")
    if not position.get("initial_load_complete") or snapshot["saved_at"] != position["saved_at"]:
        raise ValueError("Снимок не завершён или даты сохранения не совпадают.")
    jobs, versions = snapshot["jobs"], position["versions"]
    if not isinstance(jobs, dict) or not isinstance(versions, dict):
        raise ValueError("Некорректная структура JSON.")
    for uid, ad in jobs.items():
        if ad["uuid"] != uid or ad["status"] != "ACTIVE" or versions[uid]["status"] != "ACTIVE":
            raise ValueError("Несогласованная ACTIVE-вакансия.")
    saved = utc_microseconds(snapshot["saved_at"])
    since = utc_microseconds(position["since"])
    if saved is None or since is None:
        raise ValueError("Неизвестное время снимка или начала Feed.")
    now = utc_microseconds(datetime.now(timezone.utc).isoformat())
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT import_snapshot_id FROM feed_cursor WHERE stream_name='nav'").fetchone()
        if existing:
            if existing[0] != snapshot["snapshot_id"]:
                raise ValueError("В базе уже есть другая позиция: начальный импорт не должен её перезаписывать.")
            connection.rollback()
            return False
        if connection.execute("SELECT count(*) FROM jobs").fetchone()[0]:
            raise ValueError("Начальный импорт ожидает пустую базу.")

        for uid, technical in versions.items():
            event_time = utc_microseconds(technical.get("event_modified"))
            detail_time = utc_microseconds(technical.get("detail_modified"))
            insert_record(connection, "jobs", {
                "uuid": uid, "status": technical["status"],
                "status_modified_at": max(t for t in (event_time, detail_time) if t is not None)
                    if event_time is not None or detail_time is not None else None,
                # Это первое/последнее наблюдение данным хранилищем, не история NAV.
                "first_seen_at": now, "last_seen_at": now,
            })
            if event_time is not None:
                insert_record(connection, "feed_events", {
                    "job_uuid": uid, "source_event_id": technical.get("event_id"),
                    "event_modified_at": event_time, "status": technical["status"],
                    "recorded_at": now, "origin": "json_import",
                    # JSON хранит техническое последнее состояние, не исходное событие.
                    "event_fingerprint": fingerprint(["json_import", uid, technical]),
                })

        for uid, ad in jobs.items():
            employer = ad.get("employer") or {}
            record = {
                "job_uuid": uid, "details_modified_at": utc_microseconds(versions[uid].get("detail_modified")),
                "fetched_at": None, "recorded_at": now, "payload_hash": fingerprint(ad),
                "status": "ACTIVE", "title": ad.get("title"), "jobtitle": ad.get("jobtitle"),
                "description": ad.get("description"), "origin": "json_import", "completeness": "partial",
                "application_url": ad.get("applicationUrl"), "link": ad.get("link"),
                "source_url": ad.get("sourceurl"),
                "contact_list_json": json.dumps(ad.get("contactList") or [], ensure_ascii=False,
                                                separators=(",", ":")),
            }
            for key in ("name", "orgnr", "description", "homepage"):
                record["employer_" + key] = employer.get(key)
            for target, source in (("published", "published"), ("updated", "updated"),
                                   ("expires", "expires"), ("application_due", "applicationDue")):
                record[target] = utc_microseconds(ad.get(source))
                record[target + "_raw"] = ad.get(source)
            raw_count = ad.get("positioncount")
            record["positioncount_raw"] = str(raw_count) if raw_count is not None else None
            record["positioncount"] = int(str(raw_count)) if str(raw_count).isdigit() else None
            version_id = insert_record(connection, "job_versions", record)
            connection.execute("UPDATE jobs SET current_version_id=? WHERE uuid=?", (version_id, uid))
            for number, location in enumerate(ad.get("workLocations") or []):
                fylke, kommune = location.get("county"), location.get("municipal")
                insert_record(connection, "job_locations", {
                    "version_id": version_id, "location_no": number,
                    "country": location.get("country"), "fylke": fylke, "kommune": kommune,
                    "fylke_key": " ".join(fylke.split()).casefold() if fylke else None,
                    "kommune_key": " ".join(kommune.split()).casefold() if kommune else None,
                    "city": location.get("city"), "postal_code": location.get("postalCode"),
                    "address": location.get("address"),
                })
            classifications = {}
            for category in ad.get("categoryList") or []:
                key = (category["categoryType"], category["code"])
                if key in classifications and classifications[key] != category:
                    raise ValueError("Конфликт повторных классификаций в JSON.")
                classifications[key] = category
            for (kind, code), category in classifications.items():
                insert_record(connection, "job_classifications", {
                    "version_id": version_id, "category_type": kind, "code": code,
                    "name": category.get("name"), "description": category.get("description"),
                    "score": category.get("score"),
                })
            pairs = {(c.get("level1") or "", c.get("level2") or "")
                     for c in ad.get("occupationCategories") or []}
            for level1, level2 in pairs:
                insert_record(connection, "job_occupation_categories", {
                    "version_id": version_id, "level1": level1, "level2": level2,
                })

        insert_record(connection, "feed_cursor", {
            "stream_name": "nav", "initial_since": since,
            "last_page_id": position.get("last_page_id"), "last_page_url": position.get("last_page_url"),
            "next_url": position.get("next_url"), "etag": position.get("etag"),
            "last_modified": position.get("last_modified"), "committed_at": saved,
            "bootstrap_state": "complete", "import_snapshot_id": snapshot["snapshot_id"],
        })
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("Нарушены внешние ключи.")
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        initialize_database()
        if "--import-json" in sys.argv[1:]:
            imported = import_json()
            print("JSON импортированы." if imported else "Этот снимок уже импортирован; изменений нет.")
        else:
            print(f"SQLite-хранилище инициализировано: {DATABASE_PATH}")
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Ошибка инициализации SQLite: {error}")
        raise SystemExit(1)
