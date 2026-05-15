"""Одноразовый скрипт: создаёт все таблицы на удалённой БД.

Использование:
    DATABASE_URL=postgresql://user:pass@host:port/db python setup_db.py

Или добавь DATABASE_URL в .env — скрипт подтянет его автоматически.
"""
import asyncio
import os
import sys

# Загружаем .env если есть python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not DATABASE_URL:
    print("❌ DATABASE_URL не задан. Укажи в .env или как переменную окружения:")
    print("   DATABASE_URL=postgresql://... python setup_db.py")
    sys.exit(1)

# asyncpg использует postgresql://, не postgresql+asyncpg://
DATABASE_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

SQL = open("create_tables.sql", encoding="utf-8").read()


async def main():
    print(f"Подключение к БД...")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        print(f"❌ Не удалось подключиться: {e}")
        sys.exit(1)

    print("✅ Подключено!")

    statements = [s.strip() for s in SQL.split(";") if s.strip()]
    errors = []

    for stmt in statements:
        try:
            await conn.execute(stmt)
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
        sys.exit(1)
    else:
        print("\n🎉 Все таблицы созданы успешно!")


if __name__ == "__main__":
    asyncio.run(main())
