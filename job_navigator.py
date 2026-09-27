import sqlite3
import json
import csv
import io
import re
from pathlib import Path

from job_search import find_jobs, normalize
from profession_regions import rank_regions
import labor_market


def load_active_jobs():
    """Читает текущие ACTIVE-версии и их связи без размножения UUID."""
    path = Path(__file__).resolve().parent / "nav_jobs.db"
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN")
        rows = connection.execute("""
            SELECT v.* FROM jobs j JOIN job_versions v
              ON v.id = j.current_version_id AND v.job_uuid = j.uuid
            WHERE j.status = 'ACTIVE' AND v.status = 'ACTIVE'
        """).fetchall()
        jobs = {}
        by_version = {}
        for row in rows:
            ad = {"uuid": row["job_uuid"], "payloadHash": row["payload_hash"], "status": "ACTIVE",
                  "title": row["title"], "jobtitle": row["jobtitle"],
                  "description": row["description"], "link": row["link"],
                  "sourceurl": row["source_url"], "applicationUrl": row["application_url"],
                  "contactList": json.loads(row["contact_list_json"] or "[]"),
                  "employer": {key: row["employer_" + key]
                               for key in ("name", "orgnr", "description", "homepage")},
                  "workLocations": [], "categoryList": [], "occupationCategories": []}
            jobs[ad["uuid"]] = ad
            by_version[row["id"]] = ad
        # Отдельные запросы сохраняют связи «один ко многим» без декартова произведения.
        for table in ("job_locations", "job_classifications", "job_occupation_categories"):
            for row in connection.execute(f"""
                SELECT c.* FROM {table} c JOIN jobs j ON j.current_version_id = c.version_id
                WHERE j.status = 'ACTIVE'
            """):
                ad = by_version.get(row["version_id"])
                if ad is None:
                    continue
                if table == "job_locations":
                    ad["workLocations"].append({
                        "county": row["fylke"], "municipal": row["kommune"],
                        "country": row["country"], "city": row["city"],
                        "address": row["address"], "postalCode": row["postal_code"],
                    })
                elif table == "job_classifications":
                    ad["categoryList"].append({
                        "categoryType": row["category_type"], "code": row["code"],
                        "name": row["name"], "description": row["description"], "score": row["score"],
                    })
                else:
                    ad["occupationCategories"].append({"level1": row["level1"], "level2": row["level2"]})
        return jobs
    finally:
        connection.close()


def county_names(name):
    """Варианты официального многоязычного названия без ручного словаря fylke."""
    return {" ".join(part.split()).casefold() for part in
            [name, *re.split(r"\s+[-–]\s+", name)] if part.strip()}


def read_all_unemployed(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text), delimiter=";", strict=True)
    required = {"Fylkenr", "Fylkenavn", "Kommunenr", "Antall helt ledige"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Отсутствуют столбцы CSV NAV.")
    results = {}
    for row in reader:
        code = row["Fylkenr"].strip()
        if not code.isdigit() or int(code) == 0 or code != row["Kommunenr"].strip():
            continue
        value = row["Antall helt ledige"].strip()
        count = int(value) if value.isdigit() else None
        if code in results:
            raise ValueError("Повторный код fylke в CSV NAV.")
        results[code] = (row["Fylkenavn"].strip(), count)
    return results


def load_market_statistics():
    """Общие загрузчики NAV; соединение всех итоговых строк по коду fylke."""
    html = labor_market.download(labor_market.NAV_PAGE).decode("utf-8-sig")
    csv_url, period = labor_market.find_latest_csv(html)
    unemployed = read_all_unemployed(labor_market.download(csv_url))
    html = labor_market.download(labor_market.VACANCIES_PAGE).decode("utf-8-sig")
    xlsx_url = labor_market.find_vacancies_xlsx(html, period)
    rows, column = labor_market.read_vacancy_rows(
        labor_market.download(xlsx_url), period, "1. Antall. Fylke"
    )
    vacancies = {}
    for row in rows:
        code = str(row[1]).strip()
        if not code.isdigit() or int(code) == 0:
            continue
        code = code.zfill(2)
        if code in vacancies:
            raise ValueError("Повторный код fylke в XLSX NAV.")
        try:
            count = labor_market.vacancy_count(row[column], row[2])
        except ValueError:
            count = None
        vacancies[code] = (str(row[2]).strip(), count)
    statistics = {}
    for code in unemployed.keys() | vacancies.keys():
        if code in unemployed:
            county, count = unemployed[code]
        else:
            county, count = vacancies[code][0], None
        vacancy_name, new_jobs = vacancies.get(code, (county, None))
        ratio = new_jobs / count * 100 if count and new_jobs is not None else None
        statistics[code] = (county_names(county) | county_names(vacancy_name), count, new_jobs, ratio)
    return period, statistics


def show_region_ranking(ranking):
    statistics = {}
    try:
        period, statistics = load_market_statistics()
        complete = sum(count is not None and jobs is not None for names, count, jobs, ratio in statistics.values())
        print(f"Общая статистика NAV за {period}: полные показатели для {complete} территориальных строк.")
        print("Новые вакансии на 100 полностью безработных — общий показатель fylke, "
              "не показатель выбранной профессии. Период статистики отличается от локального снимка.")
    except (OSError, labor_market.URLError, labor_market.HTTPException, ImportError,
            ValueError, labor_market.csv.Error, labor_market.BadZipFile,
            labor_market.ParseError, KeyError, IndexError, TypeError, AttributeError):
        print("Общая статистика NAV недоступна. Поиск по локальному снимку продолжается.")

    print("Экспериментальная доля профессии = найденные ACTIVE-вакансии профессии "
          "из частичного локального снимка Stilling Feed / все новые вакансии fylke "
          "из полной месячной статистики NAV × 100%. Источники, охват и периоды "
          "различаются: это НЕ точная рыночная доля.")
    for index, (county, count) in enumerate(ranking, 1):
        line = f"{index}. {county} — вакансий профессии в снимке: {count}"
        values = [value for value in statistics.values() if " ".join(county.split()).casefold() in value[0]]
        if len(values) == 1:
            names, unemployed, vacancies, ratio = values[0]
            ratio_text = f"{ratio:.2f}" if ratio is not None else "не рассчитано (нет данных или безработных 0)"
            share_text = (f"{count / vacancies * 100:.2f}%" if vacancies is not None and vacancies > 0
                          else "не рассчитана (нет данных или новых вакансий 0)")
            line += (f"; полностью безработных: {unemployed if unemployed is not None else 'нет данных'}; "
                     f"новых вакансий всего: {vacancies if vacancies is not None else 'нет данных'}"
                     f"; новых вакансий на 100 полностью безработных: {ratio_text}"
                     f"; экспериментальная доля профессии: {share_text}")
        else:
            line += "; общая статистика: нет данных в подключённом загрузчике"
        print(line)


def main():
    print("Результаты основаны только на текущем локальном снимке NAV "
          "в nav_jobs.db и пока не представляют весь рынок Норвегии.")
    profession = input("Введите профессию: ")
    if not normalize(profession):
        print("Введите непустое название профессии.")
        return

    try:
        jobs = load_active_jobs()
        ranking, total, missing = rank_regions(jobs, profession)
        print(f"Всего найдено уникальных ACTIVE-вакансий: {total}.")
        if not total:
            print("Подходящих вакансий в локальном снимке не найдено.")
            return
        if ranking:
            show_region_ranking(ranking)
        if missing:
            print(f"Без указанного fylke: {missing} (включены в общее количество).")
        if not ranking:
            print("У найденных вакансий не указан fylke; выбрать регион невозможно.")
            return
        print("Вакансия с несколькими fylke учитывается один раз в каждом регионе, "
              "а в общем количестве — один раз по UUID.")

        counties = {county.casefold(): county for county, count in ranking}
        while True:
            selected = input("Введите название fylke из рейтинга: ").strip().casefold()
            if selected in counties:
                break
            print("Такого fylke нет в рейтинге. Введите название из списка.")

        matches = find_jobs(jobs, profession, counties[selected])
        print(f"Найдено вакансий в {counties[selected]}: {len(matches)}.")
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
    except (OSError, sqlite3.Error):
        print("Ошибка: не удалось прочитать nav_jobs.db.")
    except (ValueError, KeyError, TypeError, AttributeError):
        print("Ошибка: некорректные данные в nav_jobs.db.")


if __name__ == "__main__":
    main()
