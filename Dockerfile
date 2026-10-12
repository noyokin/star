FROM python:3.10-slim
WORKDIR /app
# Копируем список библиотек и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Копируем все остальные файлы
COPY . .
# Запускаем бота
CMD ["python", "bot.py"]
