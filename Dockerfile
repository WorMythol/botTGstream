FROM python:3.11-slim

# Системные зависимости (pg_dump для бэкапов — опционально)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Зависимости отдельно — кэшируется при сборке
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY . .

# Запуск бота
CMD ["python", "-m", "bot.main"]
