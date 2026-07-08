import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta

# =========================
# КОНФИГУРАЦИЯ
# =========================
CONFIG = {
    "periods": {"recent_days": 3, "history_days": 21, "min_data_days": 7},
    "thresholds": {"ctr_min": 0.005, "ctr_max": 0.15, "cpa_target": 2000.0, "conversion_drop_pct": 0.4},
    "messages": {"ok": [
        "Показатели соответствуют историческому тренду",
        "Система не обнаружила критических отклонений",
        "Кампания работает стабильно"
    ]}
}

HISTORY_FILE = "action_history.json"

# =========================
# ССЫЛКИ НА РЕКЛАМНЫЕ КАБИНЕТЫ
# =========================
def get_campaign_url(source, campaign_id):
    if source == "google":
        return f"https://ads.google.com/aw/campaigns?campaignId={campaign_id}"
    elif source == "yandex":
        return f"https://direct.yandex.ru/registered/main.pl?cmd=edit-campaign&id={campaign_id}"
    elif source == "meta":
        return f"https://www.facebook.com/adsmanager/manage/campaigns?campaign_id={campaign_id}"
    return "https://google.com"

# =========================
# ИСТОРИЯ ДЕЙСТВИЙ
# =========================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================
# ЯДРО АНАЛИЗА
# =========================
def analyze_campaigns(df: pd.DataFrame):
    results = []
    periods = CONFIG["periods"]
    thresholds = CONFIG["thresholds"]
    messages = CONFIG["messages"]

    for (project, campaign), camp_df in df.groupby(["project", "campaign"]):
        camp_df = camp_df.sort_values("date").reset_index(drop=True)
        total_days = len(camp_df)
        source = camp_df["source"].iloc[0]
        campaign_id = str(camp_df["campaign_id"].iloc[0])

        if total_days < periods["min_data_days"]:
            results.append({
                "label": f"{project} / {campaign}",
                "status": "data_accumulation",
                "problem": f"Доступно только {total_days} дней данных (нужно минимум {periods['min_data_days']})",
                "actions": ["Наблюдать", "Закрыть"],
                "source": source, 
                "campaign_id": campaign_id
            })
            continue

        # Читаем бюджет из таблицы
        try:
            budget_limit = camp_df["budget"].iloc[0]
        except:
            budget_limit = camp_df["cost"].sum() * 1.5

        total_spent = camp_df["cost"].sum()
        remaining = budget_limit - total_spent
        avg_daily = total_spent / max(total_days, 1)
        days_left = remaining / max(avg_daily, 1) if avg_daily > 0 else 999

        base = {
            "label": f"{project} / {campaign}", 
            "source": source, 
            "campaign_id": campaign_id
        }

        # ПРИОРИТЕТ 1: Бюджет
        if remaining <= 0 or days_left <= 0:
            results.append({
                **base, 
                "status": "stopped",
                "problem": "Бюджет исчерпан. Объявления не показываются.",
                "actions": ["Пополнить", "Закрыть"]
            })
        elif days_left <= 1:
            results.append({
                **base, 
                "status": "critical",
                "problem": f"Бюджет закончится завтра (~{int(days_left)} дн.)",
                "actions": ["Пополнить", "Наблюдать", "Игнорировать"]
            })
        elif days_left <= 3:
            results.append({
                **base, 
                "status": "warning",
                "problem": f"Бюджет закончится через ~{int(days_left)} дня",
                "actions": ["Пополнить", "Наблюдать", "Игнорировать"]
            })
        elif days_left <= 5:
            results.append({
                **base, 
                "status": "info",
                "problem": f"Бюджет закончится через ~{int(days_left)} дней",
                "actions": ["Пополнить", "Наблюдать", "Игнорировать"]
            })
        else:
            # ПРИОРИТЕТ 2: Метрики
            recent_df = camp_df.tail(periods["recent_days"])
            history_df = camp_df.iloc[:-periods["recent_days"]]
            if len(history_df) < 3:
                history_df = recent_df

            r_cost, r_conv = recent_df["cost"].sum(), recent_df["conversions"].sum()
            r_clicks, r_impr = recent_df["clicks"].sum(), recent_df["impressions"].sum()
            h_cost, h