import pandas as pd

# читаем файл
df = pd.read_csv('data_storage.csv')

print("Проверяем данные...\n")

# проверяем каждую строку
for index, row in df.iterrows():
    
    # правило 1: есть расход, но нет конверсий
    if row['cost'] > 0 and row['conversions'] == 0:
        print(f"⚠ ПРОБЛЕМА: проект {row['project_id']}")
        print("🔴 КРИТИЧНО: Есть расходы, но нет конверсий")

    # правило 2: пользователи уходят сразу (высокий bounce rate)
    if row['clicks'] > 50 and row['conversions'] == 0 and row['impressions'] > 0:
        print(f"⚠ ПРОБЛЕМА: проект {row['project_id']}")
        print("🟠 ВАЖНО: Пользователи кликают, но нет результата — возможна нерелевантная страница")

    # правило 3: риск по бюджету (условная модель)
    if row['cost'] > 4000 and row['conversions'] == 0:
       print(f"⚠ РИСК БЮДЖЕТА: проект {row['project_id']}")
       print("🔴 КРИТИЧНО: Большие расходы без результата — возможный слив бюджета")