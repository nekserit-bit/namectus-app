import csv
import os
from datetime import datetime

FILE_NAME = "data_storage.csv"

# Если файл ещё не существует — создаём его с заголовками
if not os.path.exists(FILE_NAME):
    with open(FILE_NAME, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["date", "project_id", "clicks", "cost"])

print("Файл готов или уже существует.")