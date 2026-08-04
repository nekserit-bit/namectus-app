from namectus_engine import NamectusEngine

engine = NamectusEngine()

# Создаём "идеальную" проблемную кампанию для теста
test_campaign = {
    'days': 5,
    'spend': 12500,
    'currency': '₽',
    'conversions': 0,          # Сработает правило 1 (Нет заявок)
    'status': 'active',
    'budget_remaining': 2000,  # Сработает правило 3 (Бюджет на исходе)
    'daily_spend': 2500,
    'previous_cpa': 500,
    'current_cpa': 700,        # Сработает правило 5 (CPA вырос на 40%)
    'current_ctr': 0.003,      # Сработает правило 6 (CTR упал)
    'previous_ctr': 0.01,
    'broken_links_count': 2    # Сработает правило 7 (Битые ссылки)
}

problems = engine.check_campaign(test_campaign)

print("=== РЕЗУЛЬТАТ ПРОВЕРКИ NAMECTUS ===\n")
if problems:
    print(f"Найдено проблем: {len(problems)}\n")
    for p in problems:
        print(p['title'])
        print(p['description'])
        print(p['action'])
        print("-" * 50)
else:
    print(" Всё отлично! Проблем нет.")