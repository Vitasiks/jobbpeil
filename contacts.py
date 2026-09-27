contacts = {}

while True:
    print()
    print("1. Добавить контакт")
    print("2. Найти контакт")
    print("3. Показать все контакты")
    print("4. Выйти")

    choice = input("Выбери действие: ")

    if choice == "1":
        name = input("Введи имя: ")
        phone_number = input("Введи номер телефона: ")
        contacts[name] = phone_number
        print("Контакт добавлен.")

    elif choice == "2":
        name = input("Введи имя для поиска: ")

        if name in contacts:
            print(f"Номер телефона: {contacts[name]}")
        else:
            print("Такого контакта нет.")

    elif choice == "3":
        for name, phone_number in contacts.items():
            print(f"{name}: {phone_number}")

    elif choice == "4":
        break
