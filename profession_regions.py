import json
from pathlib import Path

from job_search import match_quality, normalize


def relevance(ad, query):
    """Те же поля и веса, что в job_search, без ограничения по fylke."""
    fields = [(ad.get("title"), True), (ad.get("jobtitle"), True)]
    for category in ad.get("occupationCategories") or []:
        fields.extend((category.get(key), True) for key in ("level1", "level2"))
    for category in ad.get("categoryList") or []:
        if category.get("categoryType") in ("STYRK08", "STYRK08NAV", "ESCO"):
            fields.extend((category.get(key), key != "code") for key in ("name", "code"))
    scores = [match_quality(query, text, allow_close) for text, allow_close in fields]
    strong = max(scores, default=0)
    if strong:
        return 10 + strong
    return match_quality(query, ad.get("description"), allow_close=False)


def rank_regions(jobs, profession):
    query = normalize(profession)
    matches = {}
    if not query:
        return [], 0, 0
    for ad in jobs.values():
        if ad.get("status") != "ACTIVE":
            continue
        score = relevance(ad, query)
        if score and (ad["uuid"] not in matches or score > matches[ad["uuid"]][1]):
            matches[ad["uuid"]] = (ad, score)

    regions = {}
    labels = {}
    missing = 0
    for uuid, (ad, score) in matches.items():
        counties = set()
        for location in ad.get("workLocations") or []:
            county = (location.get("county") or "").strip()
            if county:
                key = county.casefold()
                counties.add(key)
                labels.setdefault(key, county)
        if not counties:
            missing += 1
        for county in counties:
            regions.setdefault(county, set()).add(uuid)
    ranking = sorted(
        ((labels[key], len(uuids)) for key, uuids in regions.items()),
        key=lambda item: (-item[1], item[0].casefold()),
    )
    return ranking, len(matches), missing


def main():
    profession = input("Введите профессию: ")
    if not normalize(profession):
        print("Введите непустое название профессии.")
        return
    try:
        path = Path(__file__).resolve().parent / "nav_active_jobs.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        ranking, total, missing = rank_regions(data["jobs"], profession)
    except OSError:
        print("Ошибка: не удалось прочитать nav_active_jobs.json.")
        return
    except (ValueError, KeyError, TypeError, AttributeError):
        print("Ошибка: некорректные данные в nav_active_jobs.json.")
        return

    print("Рейтинг основан только на текущем локальном снимке nav_active_jobs.json; "
          "это пока не показатель всего рынка труда Норвегии.")
    print(f"Всего найдено уникальных ACTIVE-вакансий: {total}.")
    for index, (county, count) in enumerate(ranking, 1):
        print(f"{index}. {county} — {count}")
    if missing:
        print(f"Без указанного fylke: {missing} (включены в общее количество).")
    print("В каждом fylke UUID учитывается один раз. Вакансия с несколькими fylke "
          "входит в каждый из них, но в общем количестве учитывается один раз.")


if __name__ == "__main__":
    main()
