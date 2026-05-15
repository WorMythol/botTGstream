"""Одноразовый скрипт: создаёт все таблицы на удалённой БД."""
import asyncio
import asyncpg

DATABASE_URL = (
    "postgresql://bothost_db_30e3ee627b8f:"
    "k16XMMA50yqT1ocnoRCeevfe2ETdipNmY6Ox7B8-_lA"
    "@node1.pghost.ru:15686/bothost_db_30e3ee627b8f"
)

SQL = open("create_tables.sql", encoding="utf-8").read()


async def main():
    print("Подключение к БД...")
    conn = await asyncpg.connect(DATABASE_URL)
    print("✅ Подключено!")

    # Выполняем по блокам (asyncpg не поддерживает несколько statements в одном execute)
    statements = [s.strip() for s in SQL.split(";") if s.strip()]
    errors = []

    for stmt in statements:
        try:
            await conn.execute(stmt)
            # Печатаем первую строку каждого запроса для удобства
            first_line = stmt.splitlines()[0][:80]
            print(f"  ✓ {first_line}")
        except asyncpg.exceptions.DuplicateTableError:
            print(f"  ⚠ Таблица уже существует (пропускаем)")
        except asyncpg.exceptions.DuplicateObjectError:
            print(f"  ⚠ Объект уже существует (пропускаем)")
        except Exception as e:
            print(f"  ✗ Ошибка: {e}")
            errors.append(str(e))

    await conn.close()

    if errors:
        print(f"\n❌ Завершено с {len(errors)} ошибками:")
        for e in errors:
            print(f"  - {e}")
    else:
        print("\n🎉 Все таблицы созданы успешно!")


if __name__ == "__main__":
    asyncio.run(main())
