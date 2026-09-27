"""Одна страница NAV Feed или возобновляемый backfill за 30 дней в SQLite.

python nav_feed_sqlite.py
python nav_feed_sqlite.py --recheck-last  # проверить ту же страницу, не идти дальше
python nav_feed_sqlite.py --backfill-30-days  # фиксированное окно, с продолжением

Схема и JSON не меняются. История details — реально полученные версии,
а не реконструкция всех исторических состояний объявления.
"""

import json
import sqlite3
import sys
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import format_datetime
from html.parser import HTMLParser
from http.client import HTTPException, HTTPSConnection
from threading import local
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from nav_database import DATABASE_PATH, fingerprint, insert_record, utc_microseconds
from nav_feed_test import BASE_URL, get_public_token


TABLES = ("jobs", "job_versions", "job_locations", "job_classifications",
          "job_occupation_categories", "feed_events", "details_queue", "feed_cursor")
BACKFILL = "nav_backfill_30d"
BACKFILL_END = "nav_backfill_30d_end"
_http_local = local()
_public_http_local = local()
PUBLIC_JOB_URL = "https://arbeidsplassen.nav.no/stillinger/stilling/"
PUBLIC_HTML_LIMIT = 5 * 1024 * 1024


def now_us():
    return utc_microseconds(datetime.now(timezone.utc).isoformat())


@contextmanager
def transaction(db):
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def connect(path=DATABASE_PATH):
    # mode=rw запрещает незаметно создать пустую базу вместо существующей.
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def nav_url(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Отсутствует ссылка NAV")
    url = urljoin(BASE_URL, value)
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc != urlsplit(BASE_URL).netloc:
        raise ValueError("Ссылка ведёт за пределы официального API NAV")
    return url


def request_reused_json(url, headers):
    """Одно HTTPS-соединение на worker, не более четырёх запросов/с на worker."""
    parts = urlsplit(nav_url(url))
    delay = 0.25 - (monotonic() - getattr(_http_local, "last_request", 0))
    if delay > 0:
        sleep(delay)
    _http_local.last_request = monotonic()
    connection = getattr(_http_local, "connection", None)
    if connection is None:
        connection = HTTPSConnection(parts.netloc, timeout=30)
        _http_local.connection = connection
    try:
        target = parts.path + ("?" + parts.query if parts.query else "")
        connection.request("GET", target, headers=headers)
        response = connection.getresponse()
        raw = response.read()  # Полностью читаем тело перед повторным использованием.
        if response.status == 304:
            return None, {}
        if response.status != 200:
            raise HTTPError(url, response.status, response.reason, response.headers, None)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Ответ NAV должен быть объектом JSON")
        return data, dict(response.getheaders())
    except (OSError, HTTPException):
        connection.close()
        _http_local.connection = None
        raise


def request_json(url, token, headers=None, keep_alive=False):
    if keep_alive:
        return request_reused_json(url, {
            "Authorization": "Bearer " + token, "Accept": "application/json", **(headers or {})})
    request = Request(nav_url(url), headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
        **(headers or {}),
    })
    try:
        with urlopen(request, timeout=30) as response:
            data = json.load(response)
            if not isinstance(data, dict):
                raise ValueError("Ответ NAV должен быть объектом JSON")
            return data, dict(response.headers.items())
    except HTTPError as error:
        if error.code == 304:
            return None, {}
        raise


class PublicDetailHTML(HTMLParser):
    """Collect inline Next.js data without interpreting page markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and not dict(attrs).get("src"):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append("".join(self.current))
            self.current = None


def parse_public_ad_html(raw, uid):
    """Read the same adData object rendered by the official Arbeidsplassen detail page."""
    parser = PublicDetailHTML()
    parser.feed(raw)
    parser.close()
    prefix = "self.__next_f.push("
    for script in parser.scripts:
        if not script.startswith(prefix) or not script.endswith(")"):
            continue
        item = json.loads(script[len(prefix):-1])
        if len(item) < 2 or not isinstance(item[1], str):
            continue
        marker = '"adData":'
        if marker not in item[1]:
            continue
        start = item[1].index(marker) + len(marker)
        ad, _ = json.JSONDecoder().raw_decode(item[1][start:])
        if not isinstance(ad, dict) or ad.get("id") != uid:
            raise ValueError("Public detail returned another vacancy")
        return ad
    raise ValueError("Public detail does not contain adData")


def request_public_ad(uid):
    """Fetch official public detail once during ingestion/refresh, never during page render."""
    url = PUBLIC_JOB_URL + uid
    delay = 0.25 - (monotonic() - getattr(_public_http_local, "last_request", 0))
    if delay > 0:
        sleep(delay)
    _public_http_local.last_request = monotonic()
    request = Request(url, headers={
        "Accept": "text/html", "User-Agent": "JobbPeil local snapshot refresh",
    })
    with urlopen(request, timeout=30) as response:
        raw = response.read(PUBLIC_HTML_LIMIT + 1)
        if len(raw) > PUBLIC_HTML_LIMIT:
            raise ValueError("Public detail response is too large")
        charset = response.headers.get_content_charset() or "utf-8"
    return parse_public_ad_html(raw.decode(charset, "replace"), uid)


def merge_contacts(*groups, application_email=None):
    """Keep source ordering and values; application email leads only when explicitly supplied."""
    contacts, seen = [], set()
    for group in groups:
        for value in group or []:
            if not isinstance(value, dict):
                continue
            contact = {key: value.get(key) for key in ("name", "email", "phone", "role", "title")}
            key = tuple(str(contact[field] or "").strip().casefold()
                        for field in ("name", "email", "phone", "role", "title"))
            if any(key) and key not in seen:
                contacts.append(contact)
                seen.add(key)
    email = application_email.strip() if isinstance(application_email, str) else ""
    if email:
        index = next((i for i, contact in enumerate(contacts)
                      if str(contact.get("email") or "").strip().casefold() == email.casefold()), None)
        if index is None:
            contacts.insert(0, {"name": None, "email": email, "phone": None,
                                "role": None, "title": None})
        elif index:
            contacts.insert(0, contacts.pop(index))
    return contacts


def enriched_application_data(uid, feed_ad, public_ad=None):
    """Map official Feed + public detail fields into the existing DB columns."""
    application_url = feed_ad.get("applicationUrl")
    contacts = feed_ad.get("contactList") or []
    if public_ad:
        application = public_ad.get("application") or {}
        public_url = application.get("applicationUrl")
        if isinstance(public_url, str) and public_url.strip():
            application_url = public_url.strip()
        elif application.get("hasSuperraskSoknad") is True:
            application_url = PUBLIC_JOB_URL + uid + "/superrask-soknad"
        contacts = merge_contacts(public_ad.get("contactList"), contacts,
                                  application_email=application.get("applicationEmail"))
    else:
        contacts = merge_contacts(contacts)
    return application_url, json.dumps(contacts, ensure_ascii=False, separators=(",", ":"))


def cursor(db, stream="nav"):
    rows = db.execute("SELECT * FROM feed_cursor WHERE stream_name=?", (stream,)).fetchall()
    if len(rows) != 1 or (stream == "nav" and not rows[0]["last_page_url"]):
        raise ValueError("Нет сохранённой позиции NAV; историческая загрузка запрещена")
    return dict(rows[0])


def apply_page(db, page, headers, expected_cursor, bounds=None, final_page=False):
    """Вся страница, очередь и курсор фиксируются или откатываются вместе."""
    page_id = page["id"]
    if not isinstance(page_id, str) or not page_id or not isinstance(page["items"], list):
        raise ValueError("Некорректная страница Feed")
    page_url = nav_url(page["feed_url"])
    next_url = nav_url(page["next_url"]) if page["next_url"] is not None else None
    if next_url == page_url:
        raise ValueError("next_url ссылается на текущую страницу")
    received = now_us()
    inserted, touched, changed = 0, set(), set()
    with transaction(db):
        stream = expected_cursor["stream_name"]
        if cursor(db, stream) != expected_cursor:
            raise ValueError("Курсор изменён другим запуском; повторите синхронизацию")
        for index, item in enumerate(page["items"]):
            entry = item["_feed_entry"]
            uid, status = entry["uuid"], entry["status"]
            stamp = utc_microseconds(item["date_modified"])
            # Обе даты Feed могут запаздывать относительно sistEndret details.
            # Для сравнения версий details используем только даты других details.
            version_time = utc_microseconds(entry.get("sistEndret")) or stamp
            if not isinstance(uid, str) or not uid or status not in ("ACTIVE", "INACTIVE") or stamp is None:
                raise ValueError("Некорректные UUID, статус или дата события")
            if bounds is not None and not bounds[0] <= stamp < bounds[1]:
                continue
            details_url = nav_url(item["url"])
            touched.add(uid)
            key = fingerprint([uid, item["id"], stamp, status])
            # Импортированные события имеют другой fingerprint, но реальные id/даты.
            duplicate = db.execute("""SELECT id FROM feed_events WHERE event_fingerprint=?
                OR (job_uuid=? AND source_event_id IS ? AND event_modified_at=? AND status=?)
                LIMIT 1""", (key, uid, item["id"], stamp, status)).fetchone()
            if duplicate:
                # Обогащаем импортированную техническую запись только фактическими
                # реквизитами прочитанного события, не создавая второе событие.
                db.execute("""UPDATE feed_events SET page_id=COALESCE(page_id,?),
                    item_index=COALESCE(item_index,?),details_url=COALESCE(details_url,?)
                    WHERE id=?""", (page_id, index, details_url, duplicate["id"]))
                continue
            db.execute("""INSERT INTO jobs(uuid,status,first_seen_at,last_seen_at)
                VALUES (?,'UNKNOWN',?,?) ON CONFLICT(uuid) DO NOTHING""", (uid, received, received))
            event_id = insert_record(db, "feed_events", {
                "job_uuid": uid, "source_event_id": item["id"], "event_modified_at": stamp,
                "status": status, "details_url": details_url, "page_id": page_id,
                "item_index": index, "received_at": received, "recorded_at": received,
                "origin": "feed", "event_fingerprint": key,
            })
            inserted += 1
            job = db.execute("SELECT * FROM jobs WHERE uuid=?", (uid,)).fetchone()
            db.execute("UPDATE jobs SET last_seen_at=? WHERE uuid=?", (received, uid))
            if job["status_modified_at"] is not None and stamp <= job["status_modified_at"]:
                queued = db.execute("SELECT state FROM details_queue WHERE job_uuid=?", (uid,)).fetchone()
                # В реальном Feed встречаются разные статусы с одной датой.
                # Пока details не получены, последнее событие прохода решает ничью.
                # Уже подтверждённое details состояние здесь не перезаписываем.
                if not (stamp == job["status_modified_at"] and queued is not None
                        and queued["state"] in ("pending", "in_progress") and status != job["status"]):
                    continue
            changed.add(uid)
            db.execute("""UPDATE jobs SET status=?,status_modified_at=?,
                current_version_id=CASE WHEN ?='ACTIVE' THEN NULL ELSE current_version_id END
                WHERE uuid=?""", (status, stamp, status, uid))
            db.execute("""INSERT INTO details_queue
                (job_uuid,requested_event_id,requested_modified_at,details_url)
                VALUES (?,?,?,?) ON CONFLICT(job_uuid) DO UPDATE SET
                requested_event_id=excluded.requested_event_id,
                requested_modified_at=excluded.requested_modified_at,
                details_url=excluded.details_url,state='pending',
                next_retry_at=NULL,lease_until=NULL,last_error=NULL,last_http_status=NULL""",
                (uid, event_id, version_time, details_url))
        normalized_headers = {k.lower(): v for k, v in headers.items()}
        db.execute("""UPDATE feed_cursor SET last_page_id=?,last_page_url=?,next_url=?,
            etag=?,last_modified=?,committed_at=?,bootstrap_state=? WHERE stream_name=?""",
            (page_id, page_url, next_url, normalized_headers.get("etag"),
             normalized_headers.get("last-modified"), received,
             "complete" if final_page or next_url is None else "in_progress", stream))
    return {"received_events": len(page["items"]), "inserted_events": inserted,
            "page_uuids": len(touched), "changed_uuids": changed}


def save_version(db, uid, detail, fetched, public_ad=None):
    """Вызывается внутри транзакции; повторный payload не дублирует версию."""
    stamp = utc_microseconds(detail["sistEndret"])
    payload_hash = fingerprint(detail)
    existing = db.execute("""SELECT id FROM job_versions WHERE job_uuid=?
        AND details_modified_at IS ? AND payload_hash=?""", (uid, stamp, payload_hash)).fetchone()
    ad = detail.get("ad_content") or {}
    application_url, contact_list_json = enriched_application_data(uid, ad, public_ad)
    if existing:
        db.execute("UPDATE job_versions SET application_url=?,contact_list_json=? WHERE id=?",
                   (application_url, contact_list_json, existing["id"]))
        return existing["id"]
    employer = ad.get("employer") or {}
    raw_count = ad.get("positioncount")
    count = None
    if isinstance(raw_count, (str, int)) and not isinstance(raw_count, bool):
        try:
            count = int(raw_count)
            if count < 0:
                count = None
        except ValueError:
            pass
    row = dict(job_uuid=uid, details_modified_at=stamp, fetched_at=fetched,
               recorded_at=now_us(), payload_hash=payload_hash, status=detail["status"],
               origin="feed", completeness="complete" if ad else "masked",
               positioncount=count, positioncount_raw=None if raw_count is None else str(raw_count))
    for field in ("title", "jobtitle", "description", "link"):
        row[field] = ad.get(field)
    for field in ("name", "orgnr", "description", "homepage"):
        row["employer_" + field] = employer.get(field)
    for column, field in (("published", "published"), ("updated", "updated"),
                          ("expires", "expires"), ("application_due", "applicationDue")):
        row[column + "_raw"] = ad.get(field)
        row[column] = utc_microseconds(ad.get(field))
    row.update(application_url=application_url, source_url=ad.get("sourceurl"),
               contact_list_json=contact_list_json)
    version_id = insert_record(db, "job_versions", row)
    for index, location in enumerate(ad.get("workLocations") or []):
        fylke, kommune = location.get("county"), location.get("municipal")
        insert_record(db, "job_locations", dict(
            version_id=version_id, location_no=index, country=location.get("country"),
            fylke=fylke, kommune=kommune, fylke_key=fylke.strip().casefold() if fylke else None,
            kommune_key=kommune.strip().casefold() if kommune else None,
            city=location.get("city"), postal_code=location.get("postalCode"), address=location.get("address")))
    categories = {}
    for category in ad.get("categoryList") or []:
        key = category["categoryType"], category["code"]
        if key in categories and categories[key] != category:
            raise ValueError("Противоречивые классификации одного кода")
        categories[key] = category
    for (kind, code), category in categories.items():
        insert_record(db, "job_classifications", dict(version_id=version_id,
            category_type=kind, code=code, name=category.get("name"),
            description=category.get("description"), score=category.get("score")))
    for level1, level2 in {(c.get("level1") or "", c.get("level2") or "")
                           for c in ad.get("occupationCategories") or []}:
        if level1 or level2:
            insert_record(db, "job_occupation_categories",
                          dict(version_id=version_id, level1=level1, level2=level2))
    return version_id


def claim_details(db, uid):
    with transaction(db):
        now = now_us()
        row = db.execute("""SELECT * FROM details_queue WHERE job_uuid=? AND
            ((state='pending' AND (next_retry_at IS NULL OR next_retry_at<=?)) OR
             (state='in_progress' AND (lease_until IS NULL OR lease_until<=?)))""",
            (uid, now, now)).fetchone()
        if row is None:
            return None
        lease = now + 120_000_000
        db.execute("""UPDATE details_queue SET state='in_progress',attempts=attempts+1,
            lease_until=? WHERE job_uuid=?""", (lease, uid))
        return dict(row, lease_until=lease)


def owns_claim(db, claim):
    return db.execute("""SELECT 1 FROM details_queue WHERE job_uuid=?
        AND requested_event_id IS ? AND lease_until=? AND state='in_progress'""",
        (claim["job_uuid"], claim["requested_event_id"], claim["lease_until"])).fetchone() is not None


def commit_details(db, claim, detail, fetched, public_ad=None):
    uid = claim["job_uuid"]
    if not isinstance(detail, dict) or detail.get("uuid") != uid or detail.get("status") not in ("ACTIVE", "INACTIVE"):
        raise ValueError("Некорректные UUID/статус details")
    stamp = utc_microseconds(detail.get("sistEndret"))
    ad = detail.get("ad_content")
    if stamp is None or (ad is not None and (not isinstance(ad, dict) or ad.get("uuid") != uid)):
        raise ValueError("Некорректная версия/содержимое details")
    if detail["status"] == "ACTIVE" and (not ad or not isinstance(ad.get("title"), str)):
        raise ValueError("Нет содержимого ACTIVE-вакансии")
    with transaction(db):
        if not owns_claim(db, claim):
            return False  # Новое событие или другой worker уже заменили это задание.
        latest = db.execute("SELECT MAX(details_modified_at) FROM job_versions WHERE job_uuid=?", (uid,)).fetchone()[0]
        if latest is not None and stamp < latest:
            raise ValueError("Запоздавшая версия details; состояние не перезаписано")
        event = db.execute("SELECT status FROM feed_events WHERE id=?",
                           (claim["requested_event_id"],)).fetchone()
        if (event and event["status"] != detail["status"]
                and stamp <= (claim["requested_modified_at"] or 0)):
            raise ValueError("Details не подтверждают более новый статус события")
        conflicting = db.execute("""SELECT 1 FROM job_versions WHERE job_uuid=?
            AND details_modified_at=? AND status<>? LIMIT 1""",
            (uid, stamp, detail["status"])).fetchone()
        if conflicting:
            raise ValueError("Статус уже сохранённой версии details отличается")
        version_id = save_version(db, uid, detail, fetched, public_ad)
        db.execute("""UPDATE jobs SET status=?,current_version_id=?,
            status_modified_at=MAX(COALESCE(status_modified_at,0),?),last_seen_at=? WHERE uuid=?""",
            (detail["status"], version_id, stamp, fetched, uid))
        db.execute("""UPDATE details_queue SET state='done',lease_until=NULL,
            next_retry_at=NULL,last_error=NULL,last_http_status=200 WHERE job_uuid=?""", (uid,))
    return True


def fail_details(db, claim, message, http_status=None):
    with transaction(db):
        if owns_claim(db, claim):
            db.execute("""UPDATE details_queue SET state='pending',lease_until=NULL,
                next_retry_at=?,last_error=?,last_http_status=? WHERE job_uuid=?""",
                (now_us() + 300_000_000, message, http_status, claim["job_uuid"]))


def process_queue(db, token, workers=1, job_ids=None):
    # Снимок очереди: одна попытка на UUID за запуск, без бесконечных ретраев.
    now = now_us()
    candidates = [r[0] for r in db.execute("""SELECT job_uuid FROM details_queue WHERE
        (state='pending' AND (next_retry_at IS NULL OR next_retry_at<=?)) OR
        (state='in_progress' AND (lease_until IS NULL OR lease_until<=?))
        ORDER BY requested_modified_at,job_uuid""", (now, now))]
    if job_ids is not None:
        candidates = [uid for uid in candidates if uid in job_ids]
    requests, succeeded, failed, stop = 0, set(), 0, False
    # Только HTTP выполняется параллельно. Все транзакции SQLite — в главном потоке.
    # Маленькие пакеты не оставляют большую очередь запросов при остановке.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(candidates), workers):
            batch = []
            for uid in candidates[start:start + workers]:
                claim = claim_details(db, uid)
                if claim is not None:
                    batch.append((claim, pool.submit(request_detail_with_application,
                                                    claim["details_url"], uid, token,
                                                    workers > 1)))
            for claim, future in batch:
                requests += 1
                try:
                    detail, public_ad = future.result()
                    if commit_details(db, claim, detail, now_us(), public_ad):
                        succeeded.add(claim["job_uuid"])
                except HTTPError as error:
                    fail_details(db, claim, f"HTTP {error.code}", error.code)
                    failed += 1
                    stop = stop or error.code in (401, 403, 429)
                except (URLError, OSError, HTTPException) as error:
                    fail_details(db, claim, f"Ошибка сети: {type(error).__name__}")
                    failed += 1
                    stop = True
                except (ValueError, TypeError, KeyError, AttributeError, sqlite3.IntegrityError) as error:
                    fail_details(db, claim, f"{type(error).__name__}: {error}")
                    failed += 1
                    if failed == 1:
                        print(f"Details не приняты: {type(error).__name__}: {error}", flush=True)
                if requests % (100 if workers > 1 else 25) == 0:
                    print(f"Details: {requests}/{len(candidates)}; ошибок: {failed}", flush=True)
            if stop or failed >= 5:
                break
    return requests, succeeded, failed


def request_detail_with_application(url, uid, token, keep_alive=False):
    """Fetch Feed detail and public application data before one durable DB commit."""
    detail, _ = request_json(url, token, keep_alive=keep_alive)
    ad = detail.get("ad_content") or {}
    public_ad = None
    if detail.get("status") == "ACTIVE" and not ad.get("applicationUrl"):
        try:
            candidate = request_public_ad(uid)
            if (candidate.get("status") == "ACTIVE"
                    and utc_microseconds(candidate.get("updated")) == utc_microseconds(detail.get("sistEndret"))):
                public_ad = candidate
        except (HTTPError, URLError, OSError, HTTPException, ValueError, KeyError,
                TypeError, json.JSONDecodeError):
            # The authoritative Feed detail is still stored; refresh can retry public enrichment later.
            pass
    return detail, public_ad


def counts(db):
    result = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
    result["statuses"] = dict(db.execute("SELECT status,COUNT(*) FROM jobs GROUP BY status"))
    result["queue_states"] = dict(db.execute("SELECT state,COUNT(*) FROM details_queue GROUP BY state"))
    return result


def sync_one_page(db, token, recheck_last=False):
    position = cursor(db)
    url = position["last_page_url"] if recheck_last else (position["next_url"] or position["last_page_url"])
    headers = {}
    if url == position["last_page_url"]:
        if position["etag"]:
            headers["If-None-Match"] = position["etag"]
        elif position["last_modified"]:
            headers["If-Modified-Since"] = position["last_modified"]
    print(f"Одна страница: {url}", flush=True)
    page, response_headers = request_json(url, token, headers)
    result = {"received_events": 0, "inserted_events": 0, "page_uuids": 0, "changed_uuids": set()}
    if page is None:
        print("HTTP 304: страница не изменилась; события повторно не обрабатываются.", flush=True)
    else:
        if nav_url(page["feed_url"]) != nav_url(url):
            raise ValueError("Ответ не соответствует запрошенной сохранённой странице")
        result = apply_page(db, page, response_headers, position)
        print(f"Получено событий: {result['received_events']}; новых: {result['inserted_events']}; "
              f"UUID страницы: {result['page_uuids']}; обновлений состояния: "
              f"{len(result['changed_uuids'])}.", flush=True)
    requests, confirmed, failed = process_queue(db, token)
    changed = result.pop("changed_uuids")
    result.update(changed_uuids=len(changed), details_requests=requests, details_errors=failed,
                  confirmed_active=0, inactive=0)
    for uid in changed | confirmed:
        status = db.execute("SELECT status FROM jobs WHERE uuid=?", (uid,)).fetchone()[0]
        if status == "ACTIVE" and uid in confirmed:
            result["confirmed_active"] += 1
        elif status == "INACTIVE":
            result["inactive"] += 1
    return result


def initialize_backfill(db, token):
    """Две позиции: прогресс прохода и неизменная конечная страница.

    initial_since конечной позиции хранит верхнюю границу времени. Это отдельные
    строки существующей таблицы; позиция обычного потока nav не изменяется.
    """
    if db.execute("SELECT 1 FROM feed_cursor WHERE stream_name=?", (BACKFILL,)).fetchone():
        return cursor(db, BACKFILL), cursor(db, BACKFILL_END)
    end = now_us()
    page, headers = request_json(BASE_URL + "/api/v1/feed?last", token)
    if not page or not isinstance(page.get("id"), str) or not page["id"]:
        raise ValueError("Не удалось зафиксировать конечную страницу backfill")
    stop_url = nav_url(page["feed_url"])
    normalized = {k.lower(): v for k, v in headers.items()}
    with transaction(db):
        # Другой процесс мог успеть создать те же контрольные точки.
        if not db.execute("SELECT 1 FROM feed_cursor WHERE stream_name=?", (BACKFILL,)).fetchone():
            insert_record(db, "feed_cursor", dict(stream_name=BACKFILL,
                initial_since=end - 30 * 86400 * 1_000_000, bootstrap_state="not_started"))
            insert_record(db, "feed_cursor", dict(stream_name=BACKFILL_END,
                initial_since=end, last_page_id=page["id"], last_page_url=stop_url,
                etag=normalized.get("etag"), last_modified=normalized.get("last-modified"),
                committed_at=now_us(), bootstrap_state="complete"))
    return cursor(db, BACKFILL), cursor(db, BACKFILL_END)


def backfill_scope(db, bounds):
    return {r[0] for r in db.execute("""SELECT DISTINCT job_uuid FROM feed_events
        WHERE event_modified_at>=? AND event_modified_at<?""", bounds)}


def prepare_backfill_details(db, scope):
    """После всех страниц — максимум одно актуальное задание на UUID.

    Старые события не откатывают jobs. Для JSON-версий запрашиваем реальные
    details, поскольку импорт не содержал positioncount и точного fetched_at.
    """
    with transaction(db):
        for uid in sorted(scope):
            row = db.execute("""SELECT j.status,j.current_version_id,v.origin,v.status AS version_status
                FROM jobs j LEFT JOIN job_versions v ON v.id=j.current_version_id
                WHERE j.uuid=?""", (uid,)).fetchone()
            if row["origin"] == "feed" and row["status"] == row["version_status"]:
                continue
            event = db.execute("""SELECT * FROM feed_events WHERE job_uuid=? AND details_url IS NOT NULL
                ORDER BY event_modified_at DESC,id DESC LIMIT 1""", (uid,)).fetchone()
            if event is None:
                raise ValueError("Нет фактической ссылки details для UUID из периода")
            queued = db.execute("SELECT * FROM details_queue WHERE job_uuid=?", (uid,)).fetchone()
            if queued is not None and queued["state"] == "pending":
                # Восстановление очереди, созданной до поддержки одинаковых дат.
                # id отражает порядок записи событий последовательного backfill.
                old_event = db.execute("SELECT * FROM feed_events WHERE id=?",
                                       (queued["requested_event_id"],)).fetchone()
                job_time = db.execute("SELECT status_modified_at FROM jobs WHERE uuid=?", (uid,)).fetchone()[0]
                if (old_event is not None and old_event["event_modified_at"] == event["event_modified_at"]
                        and old_event["id"] < event["id"] and old_event["status"] != event["status"]
                        and job_time == event["event_modified_at"]):
                    db.execute("UPDATE jobs SET status=? WHERE uuid=?", (event["status"], uid))
                    db.execute("""UPDATE details_queue SET requested_event_id=?,requested_modified_at=?,
                        details_url=?,next_retry_at=NULL,last_error=NULL WHERE job_uuid=?""",
                        (event["id"], event["event_modified_at"], event["details_url"], uid))
            db.execute("""INSERT INTO details_queue
                (job_uuid,requested_event_id,requested_modified_at,details_url)
                VALUES (?,?,?,?) ON CONFLICT(job_uuid) DO UPDATE SET
                requested_event_id=excluded.requested_event_id,
                requested_modified_at=excluded.requested_modified_at,details_url=excluded.details_url,
                state='pending',lease_until=NULL,next_retry_at=NULL,last_error=NULL,last_http_status=NULL
                WHERE details_queue.state IN ('done','unavailable')""",
                (uid, event["id"], event["event_modified_at"], event["details_url"]))


def backfill_report(db, bounds):
    scope = backfill_scope(db, bounds)
    report = dict(zip(("events", "pages_with_events", "event_min", "event_max"),
        db.execute("""SELECT COUNT(*),COUNT(DISTINCT page_id),MIN(event_modified_at),MAX(event_modified_at)
            FROM feed_events WHERE event_modified_at>=? AND event_modified_at<?""", bounds).fetchone()))
    report.update(unique_uuids=len(scope), statuses={}, fields={}, pending_details=0)
    for uid in scope:
        row = db.execute("""SELECT j.status,v.published,v.positioncount,
            EXISTS(SELECT 1 FROM job_locations l WHERE l.version_id=v.id AND trim(COALESCE(l.fylke,''))<>'') AS fylke,
            EXISTS(SELECT 1 FROM job_classifications x WHERE x.version_id=v.id AND x.category_type LIKE 'STYRK%' AND trim(x.code)<>'') AS styrk,
            EXISTS(SELECT 1 FROM job_classifications x WHERE x.version_id=v.id AND x.category_type='ESCO' AND trim(x.code)<>'') AS esco,
            EXISTS(SELECT 1 FROM job_occupation_categories o WHERE o.version_id=v.id) AS occupations
            FROM jobs j LEFT JOIN job_versions v ON v.id=j.current_version_id WHERE j.uuid=?""", (uid,)).fetchone()
        report["statuses"][row["status"]] = report["statuses"].get(row["status"], 0) + 1
        for name in ("published", "positioncount", "fylke", "styrk", "esco", "occupations"):
            present = row[name] is not None if name in ("published", "positioncount") else bool(row[name])
            report["fields"][name] = report["fields"].get(name, 0) + int(present)
        pending = db.execute("SELECT state FROM details_queue WHERE job_uuid=?", (uid,)).fetchone()
        report["pending_details"] += int(pending is not None and pending["state"] != "done")
    return report


def backfill_30_days(db, token):
    normal_position = cursor(db)
    position, boundary = initialize_backfill(db, token)
    bounds = position["initial_since"], boundary["initial_since"]
    if bounds[1] - bounds[0] != 30 * 86400 * 1_000_000:
        raise ValueError("Сохранённое окно не равно 30 дням")
    dates = [datetime.fromtimestamp(t / 1_000_000, timezone.utc).isoformat() for t in bounds]
    print(f"Фиксированное окно событий UTC: [{dates[0]}, {dates[1]}).", flush=True)
    print(f"Продолжение backfill: {position['bootstrap_state']}; {position['last_page_id']}", flush=True)
    pages, received, inserted = 0, 0, 0
    seen = set()
    stop_event = None
    if position["bootstrap_state"] != "complete":
        # Страницы NAV — срезы от курсора, а не фиксированные блоки:
        # страница ?last может начинаться ВНУТРИ очередного блока next_url.
        # Её первое событие остаётся точной контрольной границей прохода.
        terminal, _ = request_json(boundary["last_page_url"], token)
        if not terminal or not terminal.get("items"):
            raise ValueError("Недоступно зафиксированное конечное событие")
        stop_event = terminal["items"][0]
    def event_key(item):
        return (item["id"], item["_feed_entry"]["uuid"],
                utc_microseconds(item["date_modified"]), item["_feed_entry"]["status"])
    while position["bootstrap_state"] != "complete":
        first = position["last_page_url"] is None
        url = BASE_URL + "/api/v1/feed" if first else position["next_url"]
        if not url:
            raise ValueError("Нет next_url до сохранённой конечной страницы")
        headers = {}
        if first:
            since = datetime.fromtimestamp(bounds[0] / 1_000_000, timezone.utc)
            headers["If-Modified-Since"] = format_datetime(since, usegmt=True)
        page, response_headers = request_json(url, token, headers)
        if page is None or page["id"] in seen:
            raise ValueError("Нет новой страницы backfill; контрольная точка сохранена")
        if not first and nav_url(page["feed_url"]) != nav_url(url):
            raise ValueError("NAV вернул другую страницу вместо next_url")
        seen.add(page["id"])
        final = any(event_key(item) == event_key(stop_event) for item in page["items"])
        if not final and page["next_url"] is None:
            raise ValueError("Feed закончился до зафиксированной конечной страницы")
        result = apply_page(db, page, response_headers, position, bounds=bounds, final_page=final)
        pages += 1
        received += result["received_events"]
        inserted += result["inserted_events"]
        position = cursor(db, BACKFILL)
        if pages % 10 == 0 or final:
            print(f"Feed: страниц {pages}; событий в ответах {received}; новых в окне {inserted}.", flush=True)
    scope = backfill_scope(db, bounds)
    prepare_backfill_details(db, scope)
    print(f"История событий прочитана. UUID в окне: {len(scope)}. Обработка очереди details...", flush=True)
    starting_attempts = {r["job_uuid"]: r["attempts"] for r in db.execute("SELECT * FROM details_queue")}
    requests, failed, no_progress = 0, 0, 0
    while True:
        # Максимум три попытки на задание за запуск. Уже выполненные задания
        # исключаются; при обрыве соединения остальные UUID продолжают обработку.
        remaining = [r for r in db.execute("SELECT * FROM details_queue WHERE state<>'done'")
                     if r["job_uuid"] in scope]
        eligible = {r["job_uuid"] for r in remaining
                    if r["state"] in ("pending", "in_progress")
                    and r["attempts"] - starting_attempts.get(r["job_uuid"], 0) < 3}
        if not eligible:
            break
        attempted, _, errors = process_queue(db, token, workers=5, job_ids=eligible)
        requests += attempted
        failed += errors
        if attempted:
            no_progress = no_progress + 1 if errors == attempted else 0
        if no_progress >= 3:
            print("Три прохода без успешных details; очередь сохранена для продолжения.", flush=True)
            break
        blocked = [r for r in db.execute("""SELECT * FROM details_queue
            WHERE state='pending' AND last_http_status IN (401,403,429)""") if r["job_uuid"] in scope]
        if any(r["last_http_status"] in (401, 403) for r in blocked):
            print("NAV отклонил токен; повторный запуск получит новый токен.", flush=True)
            break
        if blocked:
            until = max(r["next_retry_at"] or 0 for r in blocked)
            while until > now_us():
                seconds = min(30, (until - now_us()) / 1_000_000)
                print(f"NAV ограничил частоту запросов; пауза {seconds:.0f} с.", flush=True)
                sleep(seconds)
        if attempted == 0:
            waits = [(r["lease_until"] if r["state"] == "in_progress" else r["next_retry_at"]) or 0
                     for r in remaining if r["job_uuid"] in eligible]
            seconds = max(0.1, min(30, (min(waits) - now_us()) / 1_000_000))
            print(f"Ожидание повторной попытки: {seconds:.0f} с; осталось {len(remaining)} заданий.", flush=True)
            sleep(seconds)
    report = backfill_report(db, bounds)
    report.update(pages_this_run=pages, received_events_this_run=received,
                  inserted_events_this_run=inserted, details_requests_this_run=requests,
                  details_errors=failed, period_utc=dates)
    if cursor(db) != normal_position:
        raise ValueError("Курсор обычной синхронизации изменён другим процессом")
    print("Backfill:", json.dumps(report, ensure_ascii=False), flush=True)
    print("Это частично восстановленная история: masked-поля INACTIVE не восстанавливаются.")
    return report


def refresh_active_data(db, token, job_ids=None, workers=5):
    """Re-fetch current local ACTIVE UUIDs and rebuild their saved current detail versions."""
    parameters = []
    restriction = ''
    if job_ids:
        restriction = ' AND j.uuid IN (' + ','.join('?' for _ in job_ids) + ')'
        parameters.extend(sorted(job_ids))
    rows = db.execute("""SELECT j.uuid,v.id,v.details_modified_at,q.details_url
        FROM jobs j JOIN job_versions v ON v.id=j.current_version_id AND v.job_uuid=j.uuid
        JOIN details_queue q ON q.job_uuid=j.uuid
        WHERE j.status='ACTIVE' AND v.status='ACTIVE' AND q.details_url IS NOT NULL""" + restriction,
        parameters).fetchall()
    report = {"checked": 0, "updated": 0, "unchanged": 0, "inactive": 0,
              "older_source": 0, "errors": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(rows), workers):
            batch = rows[start:start + workers]
            futures = [pool.submit(request_detail_with_application, row["details_url"], row["uuid"],
                                   token, workers > 1)
                       for row in batch]
            for row, future in zip(batch, futures):
                report["checked"] += 1
                try:
                    detail, public_ad = future.result()
                    if (not isinstance(detail, dict) or detail.get("uuid") != row["uuid"]
                            or detail.get("status") not in ("ACTIVE", "INACTIVE")):
                        raise ValueError("Details do not describe the saved vacancy")
                    stamp = utc_microseconds(detail.get("sistEndret"))
                    if stamp is None:
                        raise ValueError("Details have no version timestamp")
                    if stamp < row["details_modified_at"]:
                        report["older_source"] += 1
                        continue
                    with transaction(db):
                        current = db.execute("SELECT current_version_id FROM jobs WHERE uuid=?",
                                             (row["uuid"],)).fetchone()
                        if current is None or current["current_version_id"] != row["id"]:
                            raise ValueError("Current version changed during refresh")
                        version_id = save_version(db, row["uuid"], detail, now_us(), public_ad)
                        checked_at = now_us()
                        db.execute("""UPDATE jobs SET status=?,current_version_id=?,
                            status_modified_at=MAX(COALESCE(status_modified_at,0),?),last_seen_at=?
                            WHERE uuid=?""", (detail["status"], version_id, stamp, checked_at, row["uuid"]))
                    if detail["status"] == "INACTIVE":
                        report["inactive"] += 1
                    elif version_id == row["id"]:
                        report["unchanged"] += 1
                    else:
                        report["updated"] += 1
                except (HTTPError, URLError, OSError, HTTPException, ValueError, KeyError, TypeError):
                    report["errors"] += 1
            if report["checked"] % 100 == 0:
                print(f"ACTIVE refresh: {report['checked']}/{len(rows)}; "
                      f"updated: {report['updated']}; inactive: {report['inactive']}; "
                      f"errors: {report['errors']}", flush=True)
    return report


def refresh_active_contacts(db, token, job_ids=None, workers=5):
    """Backward-compatible name for the complete ACTIVE application/contact refresh."""
    return refresh_active_data(db, token, job_ids=job_ids, workers=workers)


def main():
    if sys.argv[1:] not in ([], ["--recheck-last"], ["--backfill-30-days"],
                            ["--refresh-active-contacts"], ["--refresh-active-data"]):
        print("Использование: python nav_feed_sqlite.py [--recheck-last | --backfill-30-days | "
              "--refresh-active-data]")
        return 1
    db = None
    try:
        db = connect()
        cursor(db)
        print("До:", json.dumps(counts(db), ensure_ascii=False), flush=True)
        backfill = sys.argv[1:] == ["--backfill-30-days"]
        contacts_refresh = sys.argv[1:] in (["--refresh-active-contacts"], ["--refresh-active-data"])
        token = get_public_token()
        if contacts_refresh:
            result = refresh_active_data(db, token)
        else:
            result = backfill_30_days(db, token) if backfill else sync_one_page(db, token, bool(sys.argv[1:]))
        print("Результат:", json.dumps(result, ensure_ascii=False))
        print("После:", json.dumps(counts(db), ensure_ascii=False))
        foreign_keys = [tuple(r) for r in db.execute("PRAGMA foreign_key_check")]
        integrity = [r[0] for r in db.execute("PRAGMA integrity_check")]
        print("foreign_key_check:", foreign_keys, "integrity_check:", integrity)
        if not backfill and not contacts_refresh:
            print("Обработана максимум одна страница. Это частичная синхронизация NAV.")
        return int(bool(foreign_keys) or integrity != ["ok"]
                   or (not backfill and not contacts_refresh and bool(result["details_errors"]))
                   or bool(result.get("pending_details")) or bool(result.get("errors")))
    except HTTPError as error:
        print(f"Ошибка NAV: HTTP {error.code}; продолжение — с сохранённой позиции.")
    except (URLError, OSError, HTTPException):
        print("Ошибка сети/файла; сохранённые страницы и очередь остаются в SQLite.")
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error) as error:
        print(f"Ошибка синхронизации: {error}")
    finally:
        if db is not None:
            db.close()
    return 1


if __name__ == "__main__":
    sys.exit(main())
