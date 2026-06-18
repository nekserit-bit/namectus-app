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

CAMPAIGN_BUDGETS = {"R1": 295000, "S1": 290000, "M1": 500000}
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
                "icon": "⚪", "title": "Накопление данных",
                "problem": "", "actions": ["Наблюдать", "Закрыть"],
                "source": source, "campaign_id": campaign_id
            })
            continue

        total_spent = camp_df["cost"].sum()
        budget_limit = CAMPAIGN_BUDGETS.get(campaign, total_spent * 1.5)
        remaining = budget_limit - total_spent
        avg_daily = total_spent / max(total_days, 1)
        days_left = remaining / max(avg_daily, 1)

        base = {"label": f"{project} / {campaign}", "source": source, "campaign_id": campaign_id}

        if remaining <= 0 or days_left <= 0:
            results.append({**base, "icon": "", "title": "Реклама остановлена",
                "problem": "Бюджет исчерпан. Объявления не показываются.",
                "actions": ["Пополнить", "Закрыть"]})
        elif days_left <= 1:
            results.append({**base, "icon": "", "title": "Бюджет на исходе",
                "problem": "Бюджет закончится завтра (~1 дн.)",
                "actions": ["Пополнить", "Наблюдать", "Игнорировать"]})
        elif days_left <= 3:
            results.append({**base, "icon": "🟠", "title": "Бюджет скоро закончится",
                "problem": f"Бюджет закончится через ~{int(days_left)} дня. Время согласовать оплату.",
                "actions": ["Пополнить", "Наблюдать", "Игнорировать"]})
        elif days_left <= 5:
            results.append({**base, "icon": "", "title": "Плановое завершение бюджета",
                "problem": f"Бюджет закончится через ~{int(days_left)} дней.",
                "actions": ["Пополнить", "Наблюдать", "Игнорировать"]})
        else:
            recent_df = camp_df.tail(periods["recent_days"])
            history_df = camp_df.iloc[:-periods["recent_days"]]
            if len(history_df) < 3:
                history_df = recent_df

            r_cost, r_conv = recent_df["cost"].sum(), recent_df["conversions"].sum()
            r_clicks, r_impr = recent_df["clicks"].sum(), recent_df["impressions"].sum()
            h_cost, h_conv = history_df["cost"].mean(), history_df["conversions"].mean()

            r_cpa = r_cost / max(r_conv, 1)
            h_cpa = h_cost / max(h_conv, 1)
            r_ctr = r_clicks / max(r_impr, 1)

            signals, problem = [], ""
            if r_cost > 0 and r_conv == 0:
                signals.append("critical"); problem = "Расход без конверсий"
            elif h_conv > 0 and r_cpa > h_cpa * 1.8:
                signals.append("critical"); problem = "Резкий рост CPA"
            elif h_conv > 0 and r_conv < h_conv * (1 - thresholds["conversion_drop_pct"]):
                signals.append("warning"); problem = "Падение конверсий"
            elif r_ctr < thresholds["ctr_min"]:
                signals.append("warning"); problem = "Низкий CTR"
            elif r_ctr > thresholds["ctr_max"]:
                signals.append("warning"); problem = "Аномальный CTR"

            if "critical" in signals:
                results.append({**base, "icon": "🔴", "title": "Критическое отклонение",
                    "problem": problem, "actions": ["Исправить", "Наблюдать", "Игнорировать"]})
            elif "warning" in signals:
                results.append({**base, "icon": "🟠", "title": "Требует внимания",
                    "problem": problem, "actions": ["Исправить", "Наблюдать", "Игнорировать"]})
            else:
                results.append({**base, "icon": "🟢",
                    "title": messages["ok"][hash(campaign) % len(messages["ok"])],
                    "problem": "", "actions": []})
    return results

# =========================
# ФИЛЬТР СКРЫТЫХ КАМПАНИЙ
# =========================
def filter_hidden(results, history, pending_top_ups):
    now = datetime.now()
    filtered = []
    for res in results:
        label = res["label"]
        if label in history:
            h = history[label]
            if "hide_until" in h:
                try:
                    hide_until = datetime.strptime(h["hide_until"], "%d.%m.%Y %H:%M")
                    if now < hide_until:
                        continue
                except:
                    pass
            if h.get("action") == "Закрыть" and h.get("session_closed"):
                continue
        filtered.append(res)
    return filtered

# =========================
# ИНТЕРФЕЙС STREAMLIT
# =========================
st.set_page_config(page_title="Namectus", page_icon="📊", layout="wide")

# Инициализация session_state
if "history" not in st.session_state:
    st.session_state.history = load_history()
if "pending_top_ups" not in st.session_state:
    st.session_state.pending_top_ups = {}

# Шапка
st.markdown(f"# 📅 NAMECTUS | {datetime.now().strftime('%d.%m.%Y')}")
st.markdown("---")

# Кнопка пересканирования
col_title, col_btn = st.columns([4, 1])
with col_btn:
    if st.button("🔄 Пересканировать", use_container_width=True):
        # Сбрасываем ВСЕ статусы скрытия (и "Закрыть", и "Игнорировать")
        for label, hist in st.session_state.history.items():
            if "session_closed" in hist:
                del hist["session_closed"]
            if "hide_until" in hist:
                del hist["hide_until"]
        save_history(st.session_state.history)
        st.rerun()

# Загрузка данных
try:
    df = pd.read_csv("data_storage.csv")
    results = analyze_campaigns(df)
    results = filter_hidden(results, st.session_state.history, st.session_state.pending_top_ups)
except Exception as e:
    st.error(f"Ошибка загрузки данных: {e}")
    st.stop()

if not results:
    st.success("✅ Все кампании скрыты или в норме. Отличная работа!")
    st.stop()

# Карточки кампаний
for res in results:
    label = res["label"]
    history = st.session_state.history.get(label, {})
    is_pending = st.session_state.pending_top_ups.get(label, False)

    with st.container():
        st.markdown("---")
        
        # Заголовок карточки
        title_col, status_col = st.columns([4, 1])
        with title_col:
            st.markdown(f"### {res['icon']} {label}  [{res['source'].upper()}]")
        with status_col:
            if history.get("action"):
                st.caption(f"✅ {history['action']}")
                st.caption(f"{history.get('date', '')}")

        # Проблема
        if res.get("problem"):
            st.warning(f"⚠️ {res['problem']}")

        # Если ожидает подтверждения пополнения
        if is_pending:
            url = get_campaign_url(res["source"], res["campaign_id"])
            st.info(f" [Открыть рекламный кабинет {res['source'].upper()}]({url})")
            st.markdown("**После пополнения бюджета нажмите кнопку ниже:**")
            if st.button("✅ Отметить пополненным", key=f"{label}_confirm"):
                st.session_state.history[label] = {
                    "action": "Бюджет пополнен",
                    "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                    "confirmed_date": datetime.now().strftime("%d.%m.%Y %H:%M")
                }
                st.session_state.pending_top_ups[label] = False
                save_history(st.session_state.history)
                st.rerun()
        else:
            # Кнопки действий
            if res.get("actions"):
                cols = st.columns(len(res["actions"]))
                
                for i, act in enumerate(res["actions"]):
                    with cols[i]:
                        if st.button(act, key=f"{label}_{act}"):
                            if act == "Пополнить" or act == "Исправить":
                                # Отмечаем как ожидающее подтверждения
                                st.session_state.pending_top_ups[label] = True
                                st.session_state.history[label] = {
                                    "action": f"Ожидает: {act}",
                                    "date": datetime.now().strftime("%d.%m.%Y %H:%M")
                                }
                                save_history(st.session_state.history)
                            elif act == "Игнорировать":
                                hide_until = datetime.now() + timedelta(hours=24)
                                st.session_state.history[label] = {
                                    "action": act,
                                    "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                                    "hide_until": hide_until.strftime("%d.%m.%Y %H:%M")
                                }
                                save_history(st.session_state.history)
                            elif act == "Закрыть":
                                st.session_state.history[label] = {
                                    "action": act,
                                    "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                                    "session_closed": True
                                }
                                save_history(st.session_state.history)
                            else:
                                st.session_state.history[label] = {
                                    "action": act,
                                    "date": datetime.now().strftime("%d.%m.%Y %H:%M")
                                }
                                save_history(st.session_state.history)
                            st.rerun()

st.markdown("---")
st.caption("Namectus v0.2 | Streamlit")