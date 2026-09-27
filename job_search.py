import json
import re
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path


def normalize(text):
    text = re.sub(r"<[^>]*>", " ", unescape(text))
    text = text.casefold().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    return " ".join(re.findall(r"[^\W_]+", text))


def match_quality(query, text, allow_close=True):
    """Точная фраза, слова/раздельное написание, затем близкое написание."""
    if not isinstance(text, str) or not text:
        return 0
    text = normalize(text)
    if query == text:
        return 4
    if f" {query} " in f" {text} ":
        return 3
    words = text.split()
    terms = query.split()
    if set(terms).issubset(words):
        return 2
    if not allow_close:
        return 0
    # Сравниваем короткие фразы: musikklærer и musikk lærer,
    # формы множественного числа и небольшие опечатки.
    compact = "".join(terms)
    if len(compact) < 5 or compact.isdigit():
        return 0
    for size in range(max(1, len(terms) - 1), len(terms) + 2):
        for index in range(len(words) - size + 1):
            candidate = "".join(words[index:index + size])
            if candidate == compact:
                return 2
            if candidate[:3] == compact[:3] and SequenceMatcher(None, compact, candidate).ratio() >= 0.88:
                return 1
    return 0


def find_jobs(jobs, profession, county):
    profession = normalize(profession)
    county = county.strip().casefold()
    matches = {}
    if not profession or not county:
        return matches

    for ad in jobs.values():
        if ad.get("status") != "ACTIVE":
            continue
        locations = [
            location for location in (ad.get("workLocations") or [])
            if (location.get("county") or "").strip().casefold() == county
        ]
        if not locations:
            continue

        texts = [("title", ad.get("title"), True), ("jobtitle", ad.get("jobtitle"), True)]
        for category in ad.get("occupationCategories") or []:
            texts.extend(("occupationCategories", category.get(key), True) for key in ("level1", "level2"))
        for category in ad.get("categoryList") or []:
            if category.get("categoryType") in ("STYRK08", "STYRK08NAV", "ESCO"):
                texts.extend((category["categoryType"], category.get(key), key != "code") for key in ("name", "code"))

        reasons = {}
        for source, text, allow_close in texts:
            quality = match_quality(profession, text, allow_close=allow_close)
            if quality:
                reasons[source] = max(reasons.get(source, 0), 10 + quality)
        description_quality = match_quality(profession, ad.get("description"), allow_close=False)
        if description_quality:
            reasons["description"] = description_quality
        if reasons:
            score = max(reasons.values())
            result = (ad, locations, reasons, score)
            previous = matches.get(ad["uuid"])
            if previous is None or score > previous[3]:
                matches[ad["uuid"]] = result
    return dict(sorted(matches.items(), key=lambda item: -item[1][3]))


def main():
    profession = input("Введите профессию или название работы: ")
    county = input("Введите fylke: ")
    if not profession.strip() or not county.strip():
        print("Профессия и fylke не должны быть пустыми.")
        return

    try:
        path = Path(__file__).resolve().parent / "nav_active_jobs.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        matches = find_jobs(data["jobs"], profession, county)
    except OSError:
        print("Ошибка: не удалось прочитать nav_active_jobs.json.")
        return
    except (ValueError, KeyError, TypeError, AttributeError):
        print("Ошибка: некорректные данные в nav_active_jobs.json.")
        return

    print(f"Найдено вакансий: {len(matches)}.")
    print("Поиск выполнен по локальному снимку, который содержит только часть вакансий NAV.")
    for ad, locations, reasons, score in matches.values():
        municipalities = list(dict.fromkeys(
            location.get("municipal") or "не указано" for location in locations
        ))
        print(f"\nНазвание: {ad.get('title') or ad.get('jobtitle') or 'не указано'}")
        print(f"Работодатель: {(ad.get('employer') or {}).get('name') or 'не указан'}")
        print(f"Kommune: {', '.join(municipalities)}")
        print(f"Ссылка: {ad.get('link') or ad.get('sourceurl') or 'не указана'}")
        labels = [source + (" (близкое написание)" if value == 11 else "")
                  for source, value in sorted(reasons.items(), key=lambda item: -item[1])]
        print(f"Найдено по: {', '.join(labels)}")


if __name__ == "__main__":
    main()
