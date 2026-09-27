import json
from urllib.error import URLError
from urllib.request import urlopen


def main():
    try:
        with urlopen("https://jsonplaceholder.typicode.com/users", timeout=10) as response:
            users = json.load(response)
    except (URLError, OSError):
        print("Ошибка: не удалось получить данные из API.")
        return
    except ValueError:
        print("Ошибка: API вернул некорректный JSON.")
        return

    print(f"Получено пользователей: {len(users)}")
    for user in users:
        print(f"{user['name']} — {user['address']['city']}")

    cities = {user["address"]["city"] for user in users}
    print(f"Количество разных городов: {len(cities)}")

    with open("users_data.json", "w", encoding="utf-8") as file:
        json.dump(users, file, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    main()
