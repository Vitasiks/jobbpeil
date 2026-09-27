"""Проверка profession × fylke × published; SQLite открывается только для чтения.

python market_analysis.py sykepleier 2026-08-14 2026-09-11
Без аргументов профессия и включительные календарные даты запрашиваются в консоли.
"""

import argparse
import os
import sqlite3
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from job_search import normalize
from profession_regions import relevance


DATABASE = Path(__file__).resolve().parent / "nav_jobs.db"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def microseconds(value):
    delta = value.astimezone(timezone.utc) - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def period_bounds(first, last):
    """Обе даты включены: [первая полночь, полночь после последней даты)."""
    first, last = date.fromisoformat(first), date.fromisoformat(last)
    if first > last:
        raise ValueError("Начальная дата позже конечной")
    days = (first, last + timedelta(days=1))
    try:
        zone = ZoneInfo("Europe/Oslo")
        values = [datetime.combine(day, time(), zone) for day in days]
    except ZoneInfoNotFoundError:
        if os.name != "nt":
            raise ValueError("В системе нет правил Europe/Oslo; период нельзя вычислить корректно")
        # Windows PowerShell/.NET используют установленную системную базу правил
        # W. Europe Standard Time (Oslo), включая переходы на летнее время.
        # В команду попадают только даты, уже проверенные date.fromisoformat.
        literals = ",".join("'" + day.isoformat() + "'" for day in days)
        script = (
            "$ErrorActionPreference='Stop';"
            "$zone=[TimeZoneInfo]::FindSystemTimeZoneById('W. Europe Standard Time');"
            f"foreach ($day in @({literals})) {{"
            "$value=[DateTime]::ParseExact($day,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture);"
            "[TimeZoneInfo]::ConvertTimeToUtc($value,$zone).ToString('o') }"
        )
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, check=True, timeout=20)
        values = [datetime.fromisoformat(line.strip().replace("Z", "+00:00"))
                  for line in result.stdout.splitlines() if line.strip()]
        if len(values) != 2 or any(value.tzinfo is None for value in values):
            raise ValueError("Не удалось получить календарные границы Europe/Oslo")
    return tuple(microseconds(value) for value in values)


def load_observations(bounds, path=DATABASE, *, county=None):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")  # Все связанные таблицы из одного согласованного чтения.
        # Select candidate UUIDs through the existing region index, then read their
        # history across ALL regions. Filtering versions by county first would
        # incorrectly resurrect an older version after a vacancy moves elsewhere.
        region_filter = ""
        parameters = bounds
        if county is not None:
            region_filter = """ AND v.job_uuid IN (
                SELECT candidate.job_uuid FROM job_locations location
                JOIN job_versions candidate ON candidate.id=location.version_id
                WHERE location.fylke_key=? AND candidate.published>=?
                  AND candidate.published<? AND candidate.completeness<>'masked')"""
            parameters = (*bounds, county, *bounds)
        versions = {}
        for row in db.execute("""SELECT v.*,j.status AS current_status FROM job_versions v
            JOIN jobs j ON j.uuid=v.job_uuid WHERE v.published>=? AND v.published<?
            AND v.completeness<>'masked'""" + region_filter + """
            ORDER BY COALESCE(v.details_modified_at,v.updated,v.fetched_at,v.recorded_at) DESC,
                     v.recorded_at DESC,v.id DESC""", parameters):
            ad = dict(row)
            ad.update(uuid=row["job_uuid"], workLocations=[], categoryList=[], occupationCategories=[])
            versions[row["id"]] = ad
        for table in ("job_locations", "job_classifications", "job_occupation_categories"):
            for row in db.execute(f"""SELECT x.* FROM {table} x JOIN job_versions v ON v.id=x.version_id
                WHERE v.published>=? AND v.published<? AND v.completeness<>'masked'""" + region_filter, parameters):
                ad = versions[row["version_id"]]
                if table == "job_locations":
                    ad["workLocations"].append(dict(county=row["fylke"], municipal=row["kommune"],
                        country=row["country"], city=row["city"], address=row["address"], postalCode=row["postal_code"]))
                elif table == "job_classifications":
                    ad["categoryList"].append(dict(categoryType=row["category_type"], code=row["code"],
                                                   name=row["name"]))
                else:
                    ad["occupationCategories"].append(dict(level1=row["level1"], level2=row["level2"]))
        observations = {}
        for ad in versions.values():
            substantive = any(ad.get(k) and ad[k].strip() for k in ("title", "jobtitle", "description"))
            substantive = substantive or bool(ad["categoryList"] or ad["occupationCategories"])
            if substantive:
                # Выбор версии ДО поиска: не подбираем старую профессию специально
                # под запрос и не объединяем поля разных версий в выдуманное объявление.
                observations.setdefault(ad["uuid"], ad)
        if county is not None:
            observations = {uid: ad for uid, ad in observations.items()
                            if any(" ".join((loc.get("county") or "").split()).casefold() == county
                                   for loc in ad["workLocations"])}
            return observations, {}  # Detail does not need database-wide metadata.
        metadata = {
            "jobs": db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
            "without_published": db.execute("""SELECT COUNT(*) FROM jobs j WHERE NOT EXISTS
                (SELECT 1 FROM job_versions v WHERE v.job_uuid=j.uuid AND v.published IS NOT NULL)""").fetchone()[0],
            "masked_only": db.execute("""SELECT COUNT(*) FROM jobs j WHERE EXISTS
                (SELECT 1 FROM job_versions v WHERE v.job_uuid=j.uuid AND v.completeness='masked')
                AND NOT EXISTS (SELECT 1 FROM job_versions v WHERE v.job_uuid=j.uuid
                    AND v.completeness<>'masked' AND v.published IS NOT NULL)""").fetchone()[0],
            "candidate_versions": len(versions), "observations": len(observations),
            "coverage": {r["stream_name"]: dict(r) for r in db.execute("""SELECT * FROM feed_cursor
                WHERE stream_name IN ('nav_backfill_30d','nav_backfill_30d_end')""")},
        }
        return observations, metadata
    finally:
        db.close()


def percent(count, total):
    return 100 * count / total if total else 0.0


def observation_facts(ad, score):
    """Shared per-ad geography and completeness rules; no regional aggregation."""
    counties = {}
    missing_location = not ad["workLocations"]
    for location in ad["workLocations"]:
        name = " ".join((location.get("county") or "").split())
        if name:
            counties.setdefault(name.casefold(), name)
        else:
            missing_location = True
    classification = ad["categoryList"]
    styrk = any(c["categoryType"].upper().startswith("STYRK") and (c.get("code") or "").strip()
                for c in classification)
    esco = any(c["categoryType"].upper() == "ESCO" and (c.get("code") or "").strip()
               for c in classification)
    known = ad["positioncount"] is not None
    ambiguous = len(counties) > 1 or (bool(counties) and missing_location)
    allocatable = len(counties) == 1 and not missing_location
    complete = score >= 10 and bool(styrk or esco) and known and allocatable
    return dict(ad=ad, counties=counties, strong=score >= 10, styrk=bool(styrk), esco=bool(esco),
                known=known, ambiguous=ambiguous, allocatable=allocatable, complete=complete)


def analyze(observations, profession, *, relevance_scores=None):
    query = normalize(profession)
    if not query:
        raise ValueError("Введите непустую профессию")
    matches, regions = {}, {}
    for uid, ad in observations.items():
        score = relevance(ad, query) if relevance_scores is None else relevance_scores[uid]
        if not score:
            continue
        item = observation_facts(ad, score)
        counties = item["counties"]
        matches[uid] = item
        # Нет произвольного распределения мест между регионами. UUID с несколькими
        # адресами внутри ОДНОГО fylke имеет один общий positioncount для этого fylke.
        for key, name in (counties or {"": "Fylke не указан"}).items():
            group = regions.setdefault(key, dict(fylke=name, uuids=set(), ads=0, known_positions=0,
                allocated_ads=0, positions=0, ambiguous=0, styrk=0, esco=0, fylke_present=0,
                complete=0, weak=0, inactive=0))
            if uid in group["uuids"]:
                continue
            group["uuids"].add(uid)
            group["ads"] += 1
            for field, value in (("known_positions", item["known"]), ("ambiguous", item["ambiguous"]), ("styrk", item["styrk"]),
                                 ("esco", item["esco"]), ("fylke_present", bool(counties)), ("complete", item["complete"]),
                                 ("weak", score < 10), ("inactive", ad["current_status"] == "INACTIVE")):
                group[field] += int(bool(value))
            if item["allocatable"] and item["known"]:
                group["allocated_ads"] += 1
                group["positions"] += ad["positioncount"]
    total = len(matches)
    summary = dict(total=total, missing_fylke=sum(not item["counties"] for item in matches.values()),
        ambiguous=sum(item["ambiguous"] for item in matches.values()),
        weak=sum(not item["strong"] for item in matches.values()),
        inactive=sum(item["ad"]["current_status"] == "INACTIVE" for item in matches.values()),
        complete=sum(item["complete"] for item in matches.values()))
    summary["fylke_percent"] = percent(total - summary["missing_fylke"], total)
    return sorted(regions.values(), key=lambda row: (row["fylke"] == "Fylke не указан", row["fylke"].casefold())), summary


def show_report(profession, first, last, bounds, rows, summary, metadata):
    print(f"Профессия: {profession}. Published: {first} — {last} включительно, Europe/Oslo.")
    print("Используется последняя содержательная сохранённая версия UUID с published в периоде; "
          "ACTIVE и исторические INACTIVE. Это не снимок на конец периода.")
    coverage = metadata["coverage"]
    if "nav_backfill_30d" in coverage and "nav_backfill_30d_end" in coverage:
        start = coverage["nav_backfill_30d"]["initial_since"]
        end = coverage["nav_backfill_30d_end"]["initial_since"]
        dates = [(EPOCH + timedelta(microseconds=t)).isoformat() for t in (start, end)]
        print(f"Окно Feed (UTC): [{dates[0]}, {dates[1]}).")
        if bounds[0] < start or bounds[1] > end:
            print("ВНИМАНИЕ: часть выбранного календарного периода вне окна backfill.")
        if coverage["nav_backfill_30d"]["bootstrap_state"] != "complete":
            print("ВНИМАНИЕ: проход Feed не завершён.")
    else:
        print("Границы покрытия backfill неизвестны.")
    print("Окно изменений Feed не гарантирует полноту публикаций: история частично восстановлена, "
          "старые INACTIVE могут быть masked, details получены позднее публикации.")
    print("Названия регионов взяты из county в SQLite; поле может содержать также особые территории. "
          "Административный статус этих названий здесь не проверяется.")
    print(f"Во всей базе без published: {metadata['without_published']}; masked без датированной "
          f"содержательной истории: {metadata['masked_only']}. Их нельзя отнести к профессии и периоду.")
    print(f"Наблюдений в периоде до поиска: {metadata['observations']}; найдено UUID: {summary['total']}; "
          f"из них сейчас INACTIVE: {summary['inactive']}; только description: {summary['weak']}.")
    print(f"Fylke заполнен у {summary['fylke_percent']:.1f}% найденных UUID; "
          f"без fylke: {summary['missing_fylke']}; неоднозначная география: {summary['ambiguous']}.")
    if not rows:
        print("Подходящих объявлений в сохранённых данных за этот период не найдено.")
        return
    print("Fylke | Объявления (вкл. слабые) | positioncount известен | Места (однозначно) | Неоднозначно | "
          "STYRK % | ESCO % | Fylke % | Полнота % | Только description")
    for row in rows:
        places = str(row["positions"]) if row["allocated_ads"] else "—"
        print(f"{row['fylke']} | {row['ads']} | {row['known_positions']} | {places} | "
              f"{row['ambiguous']} | {percent(row['styrk'],row['ads']):.1f} | "
              f"{percent(row['esco'],row['ads']):.1f} | {percent(row['fylke_present'],row['ads']):.1f} | "
              f"{percent(row['complete'],row['ads']):.1f} | {row['weak']}")
    print("Полнота = доля объявлений, одновременно имеющих совпадение по профессиональным полям, "
          "STYRK или ESCO, известный positioncount и однозначный fylke. Это не индекс востребованности "
          "и не проверка правильности классификации.")
    print("STYRK/ESCO/Fylke % рассчитаны среди объявлений строки; у именованного fylke последний "
          "процент неизбежно 100%. Общий процент выше учитывает неизвестные fylke.")
    print("UUID считается один раз в каждом fylke. Сумма объявлений регионов может превышать общий итог. "
          "Места неизвестного/неоднозначного региона в сумму не включаются; «—» означает отсутствие "
          "суммируемых данных, а не ноль мест. Description — слабое текстовое совпадение.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profession", nargs="?")
    parser.add_argument("first", nargs="?", help="Первая дата YYYY-MM-DD")
    parser.add_argument("last", nargs="?", help="Последняя дата YYYY-MM-DD включительно")
    args = parser.parse_args()
    try:
        profession = args.profession or input("Профессия: ")
        first = args.first or input("Начало периода (YYYY-MM-DD): ")
        last = args.last or input("Конец периода включительно (YYYY-MM-DD): ")
        if not normalize(profession):
            raise ValueError("Введите непустую профессию")
        bounds = period_bounds(first.strip(), last.strip())
        observations, metadata = load_observations(bounds)
        rows, summary = analyze(observations, profession)
        show_report(profession, first, last, bounds, rows, summary, metadata)
        return 0
    except (ValueError, OverflowError, OSError, sqlite3.Error, subprocess.SubprocessError, EOFError) as error:
        print(f"Не удалось выполнить анализ: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
