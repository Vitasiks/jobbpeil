"""Офлайн-сравнение отдельных признаков, без Demand Score и весов."""
import math
import sqlite3
import subprocess
from itertools import combinations

from demand_features import calculate_features, display, LOW_SAMPLE
from market_analysis import load_observations, period_bounds
from nav_monthly_cache import read_month

PROFESSIONS = ("sykepleier", "renholder", "butikkmedarbeider", "musikklærer")
DEMAND = ("strong", "positions", "mean_positions", "local_share")
CONTEXT = ("nav_new_vacancies", "nav_unemployed", "nav_per_100", "nav_unemployment_rate")
CONFIDENCE = ("quality", "ads")
LABELS = dict(strong="Сильные", positions="Места", mean_positions="Среднее мест",
              local_share="Локальная доля %", nav_new_vacancies="NAV новые",
              nav_unemployed="NAV безработные", nav_per_100="NAV на 100",
              nav_unemployment_rate="Безработица %", quality="Полнота %", ads="Размер выборки")


def ranks(values):
    """Средние ранги для совпадающих значений; 1 соответствует большему."""
    ordered = sorted(range(len(values)), key=lambda i: -values[i])
    result = [None] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        for i in ordered[start:end]:
            result[i] = (start + 1 + end) / 2
        start = end
    return result


def pearson(x, y):
    if len(x) < 3:
        return None
    mx, my = sum(x)/len(x), sum(y)/len(y)
    dx, dy = [v-mx for v in x], [v-my for v in y]
    denominator = math.sqrt(sum(v*v for v in dx)*sum(v*v for v in dy))
    return sum(a*b for a, b in zip(dx, dy))/denominator if denominator else None


def compare(rows, left, right):
    pairs = [(r[left], r[right]) for r in rows
             if r[left] is not None and r[right] is not None]
    x, y = zip(*pairs) if pairs else ((), ())
    rx, ry = ranks(x), ranks(y)
    return dict(n=len(pairs), pearson=pearson(x, y), spearman=pearson(rx, ry),
                moved=sum(a != b for a, b in zip(rx, ry)),
                max_shift=max((abs(a-b) for a, b in zip(rx, ry)), default=0))


def report(profession, observations, official):
    rows, summary = calculate_features(observations, profession, official)
    print(f"\n{profession}: {summary['total']} UUID, сильных {summary['total']-summary['weak']}, "
          f"description-only {summary['weak']}, неоднозначных {summary['ambiguous']}.")
    for title, fields in (("1. Наблюдаемые признаки профессии", DEMAND),
                          ("2. Общий контекст NAV, август 2026", CONTEXT),
                          ("3. Качество/confidence", CONFIDENCE + ("allocated_ads", "weak", "ambiguous"))):
        print(title)
        print("Fylke | " + " | ".join(LABELS.get(f, f) for f in fields) + " | Предупреждение")
        for row in rows:
            warning = "low sample" if row["ads"] < LOW_SAMPLE or row["strong"] < LOW_SAMPLE else ""
            print(row["fylke"] + " | " + " | ".join(display(row[f]) for f in fields) + " | " + warning)
    if profession == "musikklærer":
        print("low sample: корреляции и сравнительные ранги не интерпретируются; это тест малой выборки.")
        return rows
    # Единая сопоставляемая выборка для всех пар: однозначно связанные с NAV регионы,
    # достаточное число сильных и количественно распределяемых наблюдений.
    eligible = [r for r in rows if r["strong"] >= LOW_SAMPLE and r["allocated_ads"] >= LOW_SAMPLE
                and all(r[k] is not None for k in CONTEXT)]
    print(f"Описательное сравнение: {len(eligible)} регионов; исключены: "
          + ", ".join(r["fylke"] for r in rows if r not in eligible))
    print("Без p-values и причинных выводов. Все ранги по убыванию значения, НЕ от лучшего к худшему.")
    for field in DEMAND + CONTEXT + CONFIDENCE:
        values = ranks([r[field] for r in eligible])
        order = sorted(zip(eligible, values), key=lambda item: (item[1], item[0]["fylke"]))
        print(LABELS[field] + ": " + "; ".join(f"{display(rank)} {r['fylke']}" for r, rank in order))
    print("Все пары: n | Pearson r | Spearman rho | изменили ранг | максимальный сдвиг")
    for left, right in combinations(DEMAND + CONTEXT + CONFIDENCE, 2):
        stats = compare(eligible, left, right)
        marker = " [|rho| >= 0.8: возможное дублирование]" if stats["spearman"] is not None and abs(stats["spearman"]) >= .8 else ""
        print(f"{LABELS[left]} / {LABELS[right]}: " + " | ".join(display(stats[k])
              for k in ("n", "pearson", "spearman", "moved", "max_shift")) + marker)
    return rows


def main():
    try:
        observations, metadata = load_observations(period_bounds("2026-08-14", "2026-09-11"))
        official = read_month("2026-08")
        print("Локальные published: 14.08–11.09.2026 включительно, Europe/Oslo; NAV: август 2026.")
        print(f"Содержательных UUID: {len(observations)}; во всей базе без published: "
              f"{metadata['without_published']}; masked без датированной истории: {metadata['masked_only']}.")
        print("Последняя содержательная версия UUID с published в периоде, включая исторические INACTIVE. "
              "Это частично восстановленная история, не полный рынок и не снимок на конец периода.")
        print("Места, среднее и числитель доли учитывают только strong; description-only показаны "
              "отдельно и не входят в профессиональные показатели спроса.")
        print("Среднее = однозначные места / allocated_ads; неизвестные количества не заменяются нулями. "
              "Доля = strong / все локальные наблюдения региона за тот же период. "
              "UUID считается один раз на fylke, межрегиональные места не размножаются.")
        print("Полнота = доля сильных совпадений со STYRK/ESCO, известным positioncount и однозначным fylke; "
              "это не вероятность корректности. low sample: менее 10 наблюдений/сильных совпадений.")
        for profession in PROFESSIONS:
            report(profession, observations, official)
        print("\nРекомендации: оставить сильные UUID и локальную долю; однозначные места — "
              "кандидат вместо количества объявлений, а не автоматический дополнительный вес. "
              "Среднее оставить диагностикой: места = среднее × allocated_ads.")
        print("Общие NAV новые/безработные отражают также размер региона; NAV на 100 и уровень "
              "безработицы — только контекст. Все они одинаковы для профессий и не измеряют их спрос.")
        print("Размер выборки, полнота, слабые совпадения, географическая неоднозначность и allocated_ads "
              "использовать только для confidence; не поощрять полноту как спрос.")
        print("До формулы: собрать несколько полных одинаковых календарных периодов, оценить masked-пропуски "
              "и покрытие fylke, проверить точность профессиональных совпадений "
              "и устойчивость корреляций по месяцам. Не объединять "
              "разные периоды искусственными отношениями. Score и веса не рассчитаны.")
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(f"Ошибка локального сравнения: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
