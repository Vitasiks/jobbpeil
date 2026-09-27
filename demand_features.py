"""Исходные признаки без итогового индекса и без сетевых запросов.

python demand_features.py sykepleier 2026-08-14 2026-09-11
Даты включительны, период определяется по published в Europe/Oslo.
"""

import argparse
import sqlite3
import subprocess
from datetime import timedelta

from market_analysis import EPOCH, analyze, load_observations, observation_facts, percent, period_bounds
from nav_monthly_cache import aliases, read_month
from job_search import normalize
from profession_regions import relevance


LOW_SAMPLE = 10  # Прозрачный предупредительный порог, не статистический критерий.
MISSING_REGION = "Fylke не указан"


def regional_population(observations):
    """Тот же набор исторических наблюдений, до фильтра по профессии."""
    regions = {}
    for uid, ad in observations.items():
        counties = {}
        for location in ad["workLocations"]:
            name = " ".join((location.get("county") or "").split())
            if name:
                counties.setdefault(name.casefold(), name)
        for key, name in (counties or {"": MISSING_REGION}).items():
            region = regions.setdefault(key, dict(fylke=name, uuids=set()))
            region["uuids"].add(uid)
    return regions


def regional_nav_context(county, official):
    context = dict(nav_new_vacancies=None, nav_unemployed=None, nav_per_100=None,
                   nav_unemployment_rate=None)
    candidates = [r for r in (official or {}).get("regions", {}).values()
                  if " ".join(county.split()).casefold() in
                  (aliases(r["name"]) | aliases(r.get("vacancies_name", "")))]
    if len(candidates) == 1:
        source = candidates[0]
        context.update(nav_new_vacancies=source["new_vacancies"],
                       nav_unemployed=source["unemployed"], nav_per_100=source["per_100"],
                       nav_unemployment_rate=source["unemployment_rate"])
    return context


def calculate_detail_region(observations, profession, county, official=None):
    """Only the selected county's disclosure fields, using the shared ad rules."""
    query = normalize(profession)
    if not query:
        raise ValueError("Введите непустую профессию")
    name = None
    ads = complete = weak = 0
    for ad in observations.values():
        names = {}
        for location in ad["workLocations"]:
            location_name = " ".join((location.get("county") or "").split())
            if location_name:
                names.setdefault(location_name.casefold(), location_name)
        if county not in names:
            continue
        if name is None:
            name = names[county]
        score = relevance(ad, query)
        if score:
            facts = observation_facts(ad, score)
            ads += 1
            complete += int(facts["complete"])
            weak += int(not facts["strong"])
    if name is None or name == MISSING_REGION:
        return None
    return dict(fylke=name, quality=percent(complete, ads) if ads else None, weak=weak,
                **regional_nav_context(name, official))


def calculate_features(observations, profession, official=None):
    query = normalize(profession)
    if not query:
        raise ValueError("Введите непустую профессию")
    # Request-local scores: no stale cache when observations change.
    scores = {uid: relevance(ad, query) for uid, ad in observations.items()}
    matched, summary = analyze(observations, profession, relevance_scores=scores)
    strong_observations = {uid: ad for uid, ad in observations.items()
                           if scores[uid] >= 10}
    strong_rows, _ = analyze(strong_observations, profession, relevance_scores=scores)
    strong_by_region = {r["fylke"].casefold(): r for r in strong_rows}
    by_region = {r["fylke"].casefold(): r for r in matched}
    features = []
    for region in regional_population(observations).values():
        source = by_region.get(region["fylke"].casefold(), {})
        ads = source.get("ads", 0)
        strong_source = strong_by_region.get(region["fylke"].casefold(), {})
        strong = strong_source.get("ads", 0)
        eligible = strong_source.get("allocated_ads", 0)
        positions = strong_source.get("positions") if eligible else None
        population = len(region["uuids"])
        features.append(dict(
            fylke=region["fylke"], ads=ads, strong=strong, population=population,
            positions=positions, allocated_ads=eligible,
            mean_positions=positions / eligible if eligible else None,
            local_share=100 * strong / population,
            quality=100 * source["complete"] / ads if ads else None,
            weak=source.get("weak", 0), ambiguous=source.get("ambiguous", 0),
            known_positions=strong_source.get("known_positions", 0),
            low_sample=strong < LOW_SAMPLE,
            **regional_nav_context(region["fylke"], official),
        ))
    return sorted(features, key=lambda r: (r["fylke"] == MISSING_REGION,
                                           r["fylke"].casefold())), summary


def display(value):
    if value is None:
        return "—"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def show_report(profession, first, last, bounds, rows, summary, metadata):
    print(f"Профессия: {profession}; published: {first} — {last}, включительно, Europe/Oslo.")
    print("Последняя содержательная сохранённая версия UUID с published в периоде; "
          "включены исторические INACTIVE. Это не снимок состояния на конец периода.")
    coverage = metadata["coverage"]
    start = coverage.get("nav_backfill_30d", {}).get("initial_since")
    end = coverage.get("nav_backfill_30d_end", {}).get("initial_since")
    if start is not None and end is not None:
        stamps = [(EPOCH + timedelta(microseconds=t)).isoformat() for t in (start, end)]
        print(f"Окно backfill Feed, UTC: [{stamps[0]}, {stamps[1]}).")
        if bounds[0] < start or bounds[1] > end:
            print("ВНИМАНИЕ: выбранный период выходит за окно backfill.")
        if coverage["nav_backfill_30d"].get("bootstrap_state") != "complete":
            print("ВНИМАНИЕ: backfill не завершён.")
    else:
        print("Границы покрытия backfill неизвестны.")
    print(f"В выборке до поиска: {metadata['observations']} UUID; найдено: {summary['total']}; "
          f"description-only: {summary['weak']}; неоднозначная география: {summary['ambiguous']}; "
          f"без fylke: {summary['missing_fylke']}.")
    print(f"Во всей базе без published: {metadata['without_published']}; masked без датированной "
          f"содержательной истории: {metadata['masked_only']}. Они не приписаны профессии или периоду.")
    print(metadata.get("official_context", "Официальная статистика не подключена."))
    print("Fylke | Объявления всего | Strong | Все в базе за период | Места strong | n среднего | Среднее мест strong | "
          "Доля в базе % | Качество % | Description-only | Неоднозначно | "
          "NAV новые | NAV безработные | NAV на 100 | NAV безработица % | Предупреждение")
    for row in rows:
        values = [row[k] for k in ("fylke", "ads", "strong", "population", "positions", "allocated_ads",
                  "mean_positions", "local_share", "quality", "weak", "ambiguous",
                  "nav_new_vacancies", "nav_unemployed", "nav_per_100", "nav_unemployment_rate")]
        warning = "low sample" if row["low_sample"] else ""
        if 0 < row["allocated_ads"] < LOW_SAMPLE:
            warning += "; low sample для среднего"
        print(" | ".join(map(display, values)) + " | " + warning.lstrip("; "))
    if not summary["total"]:
        print("Совпадений в анализируемой локальной выборке нет; это не отсутствие вакансий во всём NAV.")
    print(f"low sample: менее {LOW_SAMPLE} strong-объявлений; это условный порог предупреждения.")
    print("Места и среднее: только strong, известный positioncount с одним однозначным fylke; "
          "n среднего — число таких объявлений. Это условное среднее, не среднее по всем совпадениям. "
          "Неизвестные и многорегиональные количества не распределяются. «—» означает нет данных.")
    print("Качество: процент совпадений одновременно по профессиональным полям, со STYRK или ESCO, "
          "известным positioncount и однозначным fylke. Это полнота для анализа, не точность поиска и не score.")
    print("Можно сопоставлять внутри этой выборки: UUID × fylke, долю профессии, "
          "однозначные места и условное среднее — при одинаковых датах и с учётом качества/low sample. "
          "Доля = strong / все содержательные наблюдения того же региона и периода. "
          "Description-only не входит в числитель доли, места и среднее; weak показаны отдельно. "
          "Общий региональный знаменатель не меняется при смене профессии.")
    print("Нельзя считать эти признаки полной рыночной долей или рейтингом востребованности: "
          "история восстановлена частично, masked INACTIVE исключены, покрытие регионов неизвестно. "
          "Окно событий не гарантирует полноту публикаций. Месячную статистику NAV нельзя напрямую "
          "смешивать с другим календарным интервалом и частичной базой. NAV — отдельный региональный "
          "контекст, не знаменатель точной доли профессии и не шанс трудоустройства.")
    print("Регионы — названия county из базы, включая особые территории. UUID учитывается один раз "
          "в каждом регионе; сумма региональных объявлений может превышать число уникальных UUID. "
          "Никакого итогового score или ранжирования регионов нет.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profession", nargs="?")
    parser.add_argument("first", nargs="?")
    parser.add_argument("last", nargs="?")
    parser.add_argument("--nav-period", default="2026-08", help="Месяц офлайн-контекста NAV (YYYY-MM)")
    args = parser.parse_args()
    try:
        profession = args.profession or input("Профессия: ")
        first = (args.first or input("Начало периода (YYYY-MM-DD): ")).strip()
        last = (args.last or input("Конец периода включительно (YYYY-MM-DD): ")).strip()
        bounds = period_bounds(first, last)
        observations, metadata = load_observations(bounds)
        official = None
        try:
            official = read_month(args.nav_period)
            metadata["official_context"] = (f"Официальный контекст NAV: {official['period']}, "
                "nav_monthly_statistics.json; только офлайн. «—»: нет данных/однозначного соответствия. "
                "Сравните месяц NAV с выбранным периодом published: совпадение дат не гарантирует полноту базы.")
        except (OSError, ValueError, KeyError, TypeError) as error:
            metadata["official_context"] = f"Официальный контекст NAV недоступен офлайн: {error}"
        rows, summary = calculate_features(observations, profession, official)
        show_report(profession, first, last, bounds, rows, summary, metadata)
        return 0
    except (ValueError, OverflowError, OSError, sqlite3.Error, subprocess.SubprocessError, EOFError) as error:
        print(f"Не удалось рассчитать признаки: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
