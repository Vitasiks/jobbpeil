import json
from urllib.error import URLError
from urllib.request import Request, urlopen


def main():
    url = "https://data.ssb.no/api/v0/en/table/11652"
    regions = {"42": "Agder", "11": "Rogaland", "46": "Vestland"}

    try:
        with urlopen(url, timeout=30) as response:
            metadata = json.load(response)

        variables = {item["code"]: item for item in metadata["variables"]}
        latest_period = max(variables["Tid"]["values"])
        selections = {
            "Region": list(regions),
            "Kjonn": ["0"],  # Оба пола.
            "Alder": ["999A"],  # Все возрасты.
            "ContentsCode": ["Lonsstakere"],  # Количество работников.
            "Tid": [latest_period],
        }
        query = {
            "query": [
                {"code": code, "selection": {"filter": "item", "values": values}}
                for code, values in selections.items()
            ],
            "response": {"format": "json"},
        }
        request = Request(
            url,
            data=json.dumps(query).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=30) as response:
            result = json.load(response)

        dimensions = [column["code"] for column in result["columns"] if column["type"] != "c"]
        counts = {}
        for row in result["data"]:
            if len(row["key"]) != len(dimensions) or len(row["values"]) != 1:
                raise ValueError("Некорректная структура строки")
            key = dict(zip(dimensions, row["key"]))
            if any(key[code] not in selections[code] for code in dimensions):
                raise ValueError("Ответ не соответствует запросу")
            region = key["Region"]
            count = int(row["values"][0])
            if count < 0 or region in counts:
                raise ValueError("Некорректное количество работников")
            counts[region] = count

        if counts.keys() != regions.keys():
            raise ValueError("Получены данные не для всех fylke")
    except (URLError, OSError):
        print("Ошибка: не удалось получить данные из API SSB.")
        return
    except (ValueError, KeyError, TypeError, IndexError):
        print("Ошибка: API SSB вернул некорректные или неполные данные.")
        return

    print(f"Период: {latest_period}")
    for code, name in regions.items():
        print(f"{name}: {counts[code]}")


if __name__ == "__main__":
    main()
