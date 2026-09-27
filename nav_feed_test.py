import json
import re
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.client import HTTPException
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


BASE_URL = "https://pam-stilling-feed.nav.no"


def request_text(url, headers=None):
    request = Request(url, headers=headers or {})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8-sig")


def get_public_token():
    text = request_text(BASE_URL + "/api/publicToken")
    tokens = re.findall(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", text)
    if len(tokens) != 1:
        raise ValueError("NAV не вернул однозначный публичный токен.")
    return tokens[0]


def get_json(url, token, extra_headers=None):
    if urlsplit(url).scheme != "https" or urlsplit(url).netloc != urlsplit(BASE_URL).netloc:
        raise ValueError("Ссылка на подробности ведёт за пределы API NAV.")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    headers.update(extra_headers or {})
    data = json.loads(request_text(url, headers))
    if not isinstance(data, dict):
        raise ValueError("Некорректная структура ответа NAV.")
    return data


def show_vacancy(ad):
    print(f"\nНазвание: {ad['title']}")
    locations = ad.get("workLocations") or []
    if not locations:
        print("Fylke: не указано; kommune: не указано")
    for location in locations:
        print(f"Fylke: {location.get('county') or 'не указано'}; "
              f"kommune: {location.get('municipal') or 'не указано'}")
    occupations = ad.get("occupationCategories") or []
    print("Профессиональные категории:")
    if not occupations:
        print("  Не указаны")
    for occupation in occupations:
        print("  " + " / ".join(
            occupation[key] for key in ("level1", "level2") if occupation.get(key)
        ))
    classifications = [
        category for category in (ad.get("categoryList") or [])
        if category.get("categoryType") in ("STYRK08", "STYRK08NAV", "ESCO")
    ]
    print("STYRK/ESCO:")
    if not classifications:
        print("  Не указаны")
    for category in classifications:
        print(f"  {category['categoryType']}: {category['code']} — {category['name']}")


def latest_events(items):
    """UUID вакансии отличается от id отдельного события ленты."""
    latest = {}
    for item in items:
        vacancy_id = item["_feed_entry"]["uuid"]
        if not isinstance(vacancy_id, str) or not vacancy_id:
            raise ValueError("Отсутствует UUID вакансии.")
        timestamp = datetime.fromisoformat(item["date_modified"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Дата события не содержит часового пояса.")
        if vacancy_id not in latest or timestamp >= latest[vacancy_id][0]:
            latest[vacancy_id] = (timestamp, item)
    return {key: value[1] for key, value in latest.items()}


def current_vacancy(vacancy_id, item, token):
    try:
        detail = get_json(urljoin(BASE_URL, item["url"]), token)
        if detail["uuid"] != vacancy_id or detail["status"] not in ("ACTIVE", "INACTIVE"):
            raise ValueError("Некорректный UUID или статус.")
        if detail["status"] == "ACTIVE":
            ad = detail["ad_content"]
            if not isinstance(ad, dict) or not isinstance(ad.get("title"), str):
                raise ValueError("Нет содержимого активной вакансии.")
        return detail, None
    except HTTPError as error:
        return None, f"HTTP {error.code}"
    except (URLError, OSError, HTTPException):
        return None, "ошибка сети"
    except (ValueError, KeyError, TypeError, AttributeError):
        return None, "некорректный ответ NAV"


def matches_test_search(ad):
    """Текстовый поиск без ручного сопоставления профессий и кодов."""
    if not any(
        (location.get("county") or "").strip().casefold() == "agder"
        for location in (ad.get("workLocations") or [])
    ):
        return False
    texts = [ad.get("title"), ad.get("jobtitle"), ad.get("description")]
    for occupation in ad.get("occupationCategories") or []:
        texts.extend(occupation.get(key) for key in ("level1", "level2"))
    for category in ad.get("categoryList") or []:
        if category.get("categoryType") in ("STYRK08", "STYRK08NAV", "ESCO"):
            texts.extend(category.get(key) for key in ("name", "description", "code"))
    return any(
        "musikklærer" in unescape(text).casefold()
        for text in texts if isinstance(text, str)
    )


def show_test_search(active):
    matches = {}
    for detail in active:
        if detail["status"] == "ACTIVE" and matches_test_search(detail["ad_content"]):
            matches[detail["uuid"]] = detail["ad_content"]
    print(f"\nТестовый поиск: musikklærer, Agder. Найдено: {len(matches)}.")
    print("Поиск по текстовому совпадению в полях вакансии и классификациях NAV.")
    print("Обработана только часть Feed. Ноль совпадений не означает отсутствие "
          "таких вакансий во всём NAV.")
    for ad in matches.values():
        show_vacancy(ad)
        print(f"Работодатель: {(ad.get('employer') or {}).get('name') or 'не указан'}")
        print(f"Ссылка: {ad.get('link') or ad.get('sourceurl') or 'не указана'}")


def get_feed_pages(token):
    """Первые пять страниц от прежней начальной точки: сутки назад."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    url = BASE_URL + "/api/v1/feed"
    headers = {"If-Modified-Since": format_datetime(since, usegmt=True)}
    items = []
    seen_pages = set()
    for _ in range(5):
        page = get_json(url, token, headers)
        page_id = page["id"]
        if not isinstance(page_id, str) or not page_id or page_id in seen_pages:
            raise ValueError("NAV вернул некорректную или повторную страницу.")
        if not isinstance(page["items"], list):
            raise ValueError("NAV вернул некорректный список вакансий.")
        seen_pages.add(page_id)
        items.extend(page["items"])
        print(f"Получена страница {len(seen_pages)}: {len(page['items'])} событий.", flush=True)
        next_url = page["next_url"]
        if next_url is None:
            break
        if not isinstance(next_url, str) or not next_url:
            raise ValueError("NAV вернул некорректный next_url.")
        url = urljoin(BASE_URL, next_url)
        # Дату задаём только для выбора начальной страницы.
        headers = None
    return items, len(seen_pages)


def test_search_main():
    try:
        token = get_public_token()
        items, page_count = get_feed_pages(token)
        unique = latest_events(items)
        print(f"Получено событий: {len(items)}.")
        print(f"Обработано страниц: {page_count} (лимит 5, начало — сутки назад).")
        print(f"Уникальных вакансий на обработанных страницах: {len(unique)}.")
        print("Проверка текущих статусов уникальных вакансий через API подробностей...", flush=True)
        # Даже последнее событие страницы может устареть: проверяем каждый UUID,
        # включая вакансии, которые в полученной странице помечены INACTIVE.
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(current_vacancy, key, item, token)
                       for key, item in unique.items()]
            checked = [future.result() for future in futures]
        active = [detail for detail, error in checked
                  if detail is not None and detail["status"] == "ACTIVE"]
        failures = sum(error is not None for detail, error in checked)
        print(f"Уникальных ACTIVE по ответам API при проверке: {len(active)}.")
        if failures:
            print(f"Не удалось проверить: {failures}. Точное число ACTIVE неизвестно; "
                  "указано только подтверждённое количество.")
        print(f"Это вакансии {page_count} страниц, а не весь NAV. Статусы проверены "
              "в ходе запуска и могут измениться; единого снимка на один момент времени нет.")
        for detail in active[:5]:
            try:
                show_vacancy(detail["ad_content"])
            except (ValueError, KeyError, TypeError, AttributeError):
                print("Ошибка: некорректные подробности вакансии в ответе NAV.")
        show_test_search(active)
    except HTTPError as error:
        print(f"Ошибка API NAV: HTTP {error.code}.")
    except (URLError, OSError, HTTPException):
        print("Ошибка: не удалось подключиться к API NAV.")
    except (ValueError, KeyError, TypeError, AttributeError):
        print("Ошибка: NAV вернул некорректный токен или ответ API.")


def collect_initial_events(token, checkpoint=None):
    """Первый запуск: три дня; последующие: сохранённая последняя страница."""
    since = datetime.now(timezone.utc) - timedelta(days=3)
    url = BASE_URL + "/api/v1/feed"
    headers = {
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        "If-Modified-Since": format_datetime(since, usegmt=True),
    }
    if checkpoint:
        since = datetime.fromisoformat(checkpoint["since"])
        url = checkpoint["last_page_url"]
        headers.pop("If-Modified-Since", None)
        if checkpoint.get("etag"):
            headers["If-None-Match"] = checkpoint["etag"]
        elif checkpoint.get("last_modified"):
            headers["If-Modified-Since"] = checkpoint["last_modified"]
        print(f"Продолжение с сохранённой страницы: {url}", flush=True)
    else:
        print(f"Первоначальное окно: последние 3 дня, с {since.isoformat()}", flush=True)
    latest = {}
    seen = set()
    event_count = 0
    while True:
        if urlsplit(url).scheme != "https" or urlsplit(url).netloc != urlsplit(BASE_URL).netloc:
            raise ValueError("Ссылка страницы ведёт за пределы API NAV.")
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                page = json.load(response)
                etag = response.headers.get("ETag")
                modified = response.headers.get("Last-Modified")
        except HTTPError as error:
            if error.code == 304 and checkpoint and not seen:
                print("HTTP 304: сохранённая страница не изменилась.")
                return {}, checkpoint
            raise
        page_id = page["id"]
        if not isinstance(page_id, str) or not page_id or page_id in seen:
            raise ValueError("Некорректная или повторная страница NAV.")
        if not isinstance(page["items"], list):
            raise ValueError("Некорректный список событий NAV.")
        seen.add(page_id)
        for key, item in latest_events(page["items"]).items():
            if item["_feed_entry"]["status"] not in ("ACTIVE", "INACTIVE"):
                raise ValueError("Неизвестный статус события NAV.")
            timestamp = datetime.fromisoformat(item["date_modified"].replace("Z", "+00:00"))
            saved = (checkpoint or {}).get("versions", {}).get(key)
            if saved:
                saved_time = datetime.fromisoformat(saved["event_modified"].replace("Z", "+00:00"))
                if timestamp < saved_time or (timestamp == saved_time and item["id"] == saved["event_id"]):
                    continue
                detail_time = saved.get("detail_modified")
                if detail_time and timestamp < datetime.fromisoformat(detail_time.replace("Z", "+00:00")):
                    continue
            previous = latest.get(key)
            if previous is None or timestamp >= datetime.fromisoformat(
                previous["date_modified"].replace("Z", "+00:00")
            ):
                latest[key] = item
        event_count += len(page["items"])
        print(f"Страниц: {len(seen)}; событий: {event_count}; UUID: {len(latest)}.", flush=True)
        next_url = page["next_url"]
        if next_url is None:
            return latest, {
                "since": since.isoformat(), "last_page_id": page_id,
                "last_page_url": urljoin(BASE_URL, page["feed_url"]),
                "next_url": None, "etag": etag, "last_modified": modified,
                "page_count": len(seen), "event_count": event_count,
            }
        if not isinstance(next_url, str) or not next_url:
            raise ValueError("Некорректная ссылка next_url.")
        url = urljoin(BASE_URL, next_url)
        headers.pop("If-Modified-Since", None)
        headers.pop("If-None-Match", None)


def build_active_state(latest, token):
    """INACTIVE исключаются, ACTIVE сверяются с текущими подробностями NAV."""
    active = {}
    versions = {
        key: {"event_modified": item["date_modified"],
              "event_id": item["id"], "status": item["_feed_entry"]["status"]}
        for key, item in latest.items()
    }
    candidates = [(key, item) for key, item in latest.items()
                  if item["_feed_entry"]["status"] == "ACTIVE"]
    fields = (
        "title", "jobtitle", "employer", "description", "workLocations",
        "occupationCategories", "categoryList", "applicationUrl", "applicationDue",
        "published", "updated", "expires", "link", "sourceurl", "contactList",
    )
    print(f"Проверка подробностей для {len(candidates)} кандидатов ACTIVE...", flush=True)
    with ThreadPoolExecutor(max_workers=5) as executor:
        # Небольшие пакеты не создают очередь из сотен тысяч запросов.
        for start in range(0, len(candidates), 50):
            batch = candidates[start:start + 50]
            futures = [executor.submit(current_vacancy, key, item, token) for key, item in batch]
            for (key, item), future in zip(batch, futures):
                detail, error = future.result()
                if error:
                    raise ValueError(f"Не удалось проверить UUID {key}: {error}. Снимок не сохранён.")
                versions[key]["status"] = detail["status"]
                versions[key]["detail_modified"] = detail["sistEndret"]
                if detail["status"] == "ACTIVE":
                    ad = detail["ad_content"]
                    if ad.get("uuid") != key:
                        raise ValueError("UUID содержимого не совпадает с UUID вакансии.")
                    active[key] = {field: ad.get(field) for field in fields}
                    active[key].update(uuid=key, status="ACTIVE")
            print(f"Проверено кандидатов: {min(start + 50, len(candidates))}; "
                  f"ACTIVE: {len(active)}.", flush=True)
    return active, versions


def save_initial_state(active, position, versions, directory=None):
    directory = Path(directory) if directory is not None else Path(__file__).resolve().parent
    snapshot_id = str(uuid4())
    saved_at = datetime.now(timezone.utc).isoformat()
    jobs = {"snapshot_id": snapshot_id, "saved_at": saved_at, "jobs": active}
    checkpoint = dict(position, snapshot_id=snapshot_id, saved_at=saved_at,
                      versions=versions, initial_load_complete=True)
    # Позицию записываем после данных. Идентификатор позволяет обнаружить
    # несовпадение файлов при прерывании между двумя заменами.
    for filename, content in (("nav_active_jobs.json", jobs), ("nav_feed_position.json", checkpoint)):
        target = directory / filename
        temporary = target.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(content, file, ensure_ascii=False, indent=2)
        temporary.replace(target)


def load_local_state():
    directory = Path(__file__).resolve().parent
    jobs_path = directory / "nav_active_jobs.json"
    position_path = directory / "nav_feed_position.json"
    if not jobs_path.exists() and not position_path.exists():
        return {}, None
    if not jobs_path.exists() or not position_path.exists():
        raise ValueError("Неполная пара JSON-файлов: продолжение невозможно.")
    jobs = json.loads(jobs_path.read_text(encoding="utf-8"))
    checkpoint = json.loads(position_path.read_text(encoding="utf-8"))
    if jobs["snapshot_id"] != checkpoint["snapshot_id"] or not checkpoint["initial_load_complete"]:
        raise ValueError("JSON-файлы относятся к разным или незавершённым снимкам.")
    for key, ad in jobs["jobs"].items():
        if ad["uuid"] != key or ad["status"] != "ACTIVE":
            raise ValueError("Некорректная запись в активном наборе.")
    return jobs["jobs"], checkpoint


def main():
    try:
        active, checkpoint = load_local_state()
        token = get_public_token()
        latest, position = collect_initial_events(token, checkpoint)
        updates, new_versions = build_active_state(latest, token)
        versions = dict((checkpoint or {}).get("versions", {}))
        for key in latest:
            active.pop(key, None)
        active.update(updates)
        versions.update(new_versions)
        save_initial_state(active, position, versions)
        print(f"Сохранено уникальных ACTIVE-вакансий: {len(active)}.")
        print("Это частичный набор: первоначальное окно — 3 дня. "
              "Следующий запуск продолжит с сохранённой позиции.")
    except HTTPError as error:
        print(f"Ошибка API NAV: HTTP {error.code}. Загрузка не завершена.")
    except (URLError, OSError, HTTPException):
        print("Ошибка сети или записи JSON. Загрузка не завершена.")
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"Ошибка данных: {error}")


if __name__ == "__main__":
    main()
