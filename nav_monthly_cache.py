"""Явное обновление отдельного кэша NAV: python nav_monthly_cache.py 2026-08.

Импорт модуля и read_month работают только локально, без сети.
"""
import argparse
import csv
import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import labor_market as nav

CACHE = Path(__file__).resolve().with_name("nav_monthly_statistics.json")


def aliases(name):
    return {" ".join(part.split()).casefold() for part in
            [name, *re.split(r"\s+[-–]\s+", name)] if part.strip()}


def read_month(period, path=CACHE):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Неизвестная версия кэша NAV")
    month = data["months"].get(period)
    if month is None:
        raise ValueError(f"В кэше нет NAV за {period}")
    return month


def fetch_month(period):
    date = datetime.strptime(period, "%Y-%m")
    if date.strftime("%Y-%m") != period:
        raise ValueError("Период должен быть YYYY-MM")
    nav_period = date.strftime("%m.%Y")
    parser = nav.LinkParser()
    parser.feed(nav.download(nav.NAV_PAGE).decode("utf-8-sig"))
    expected = f"{nav.MONTHS[date.month-1]} {date.year}"
    links = {urljoin(nav.NAV_PAGE, href) for href, label in parser.links
             if "helt ledige etter fylke og kommune" in label.lower()
             and expected in " ".join(label.lower().split())
             and urlsplit(href).path.lower().endswith(".csv")}
    if len(links) != 1:
        raise ValueError("Не найдена однозначная ссылка CSV нужного месяца")
    csv_url = links.pop()
    xlsx_url = nav.find_vacancies_xlsx(
        nav.download(nav.VACANCIES_PAGE).decode("utf-8-sig"), nav_period)
    raw = nav.download(csv_url)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    reader = csv.DictReader(io.StringIO(text), delimiter=";", strict=True)
    required = {"Fylkenr", "Fylkenavn", "Kommunenr", "Antall helt ledige"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Отсутствуют столбцы CSV NAV")
    regions = {}
    for row in reader:
        if None in row or any(v is None for v in row.values()):
            raise ValueError("Неполная строка CSV")
        code = row["Fylkenr"].strip()
        if not code.isdigit() or int(code) == 0 or code != row["Kommunenr"].strip():
            continue
        code = code.zfill(2)
        if code in regions:
            raise ValueError("Повторный код fylke")
        count = row["Antall helt ledige"].strip()
        percent = row.get("Helt ledige i prosent av arbeidsstyrken", "").strip()
        missing = {"", ":", "..", "-", "*"}
        count = None if count in missing else int(count)
        percent = None if percent in missing else float(percent.replace(",", "."))
        if count is not None and count < 0:
            raise ValueError("Отрицательное число безработных")
        if percent is not None and (not math.isfinite(percent) or not 0 <= percent <= 100):
            raise ValueError("Некорректный уровень безработицы")
        regions[code] = dict(name=row["Fylkenavn"].strip(), unemployed=count,
                             unemployment_rate=percent, new_vacancies=None)
    rows, column = nav.read_vacancy_rows(nav.download(xlsx_url), nav_period, "1. Antall. Fylke")
    seen = set()
    for row in rows:
        code = str(row[1]).strip()
        if not code.isdigit() or int(code) == 0:
            continue
        code = code.zfill(2)
        if code in seen:
            raise ValueError("Повторный код XLSX")
        seen.add(code)
        name = str(row[2]).strip()
        region = regions.setdefault(code, dict(name=name, unemployed=None, unemployment_rate=None))
        region["vacancies_name"] = name
        value = row[column]
        region["new_vacancies"] = (None if value is None or str(value).strip() in {"", ":", "..", "-", "*"}
                                   else nav.vacancy_count(value, name))
    if not regions or not seen:
        raise ValueError("Нет региональных данных")
    for region in regions.values():
        count, vacancies = region["unemployed"], region["new_vacancies"]
        region["per_100"] = vacancies / count * 100 if count and vacancies is not None else None
    return dict(period=period, fetched_at=datetime.now(timezone.utc).isoformat(),
                sources={"unemployed": {"url": csv_url, "indicator": "Helt ledige", "unit": "persons"},
                         "unemployment_rate": {"url": csv_url, "indicator": "Helt ledige i prosent av arbeidsstyrken", "unit": "percent"},
                         "new_vacancies": {"url": xlsx_url, "indicator": "Tilgang ledige stillinger. Fylke", "unit": "positions"},
                         "per_100": {"type": "derived", "formula": "new_vacancies / unemployed * 100"}},
                regions=regions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("period")
    args = parser.parse_args()
    month = fetch_month(args.period)
    data = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {"schema_version": 1, "months": {}}
    if data.get("schema_version") != 1:
        raise ValueError("Неизвестная версия кэша")
    data["months"][args.period] = month
    temporary = CACHE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(CACHE)
    print(f"Сохранено: {CACHE.name}, {args.period}, регионов: {len(month['regions'])}")


if __name__ == "__main__":
    main()
