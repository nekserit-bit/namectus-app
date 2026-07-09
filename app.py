import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import requests

# =========================
# ЯНДЕКС OAUTH НАСТРОЙКИ
# =========================
YANDEX_CLIENT_ID = "aba6d279d3544aaab91a4e04990c5b47"
YANDEX_CLIENT_SECRET = "926ae5fe918444138b2428181245f842"
YANDEX_REDIRECT_URI = "https://namectus-app.onrender.com/callback"

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
            h_cost, h_conv = history_df["cost"].mean(), history_df["conversions"].mean()

            r_cpa = r_cost / max(r_conv, 1)
            h_cpa = h_cost / max(h_conv, 1) if h_conv > 0 else 0
            r_ctr = r_clicks / max(r_impr, 1)

            signals = []
            
            if r_cost > 0 and r_conv == 0:
                signals.append("critical")
            elif h_conv > 0 and r_cpa > h_cpa * 1.8:
                signals.append("critical")
            elif h_conv > 0 and r_conv < h_conv * (1 - thresholds["conversion_drop_pct"]):
                signals.append("warning")
            elif r_ctr < thresholds["ctr_min"]:
                signals.append("warning")
            elif r_ctr > thresholds["ctr_max"]:
                signals.append("warning")

            if "critical" in signals:
                results.append({
                    **base, 
                    "status": "critical",
                    "problem": "Резкий рост CPA или нет конверсий", 
                    "actions": ["Исправить", "Наблюдать", "Игнорировать"]
                })
            elif "warning" in signals:
                results.append({
                    **base, 
                    "status": "warning",
                    "problem": "Низкий CTR или падение конверсий", 
                    "actions": ["Исправить", "Наблюдать", "Игнорировать"]
                })
            else:
                results.append({
                    **base, 
                    "status": "ok",
                    "problem": "", 
                    "actions": []
                })
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
# КАРТОЧКА КАМПАНИИ
# =========================
def render_campaign_card(res, label, history, is_pending):
    st.markdown("---")
    st.markdown(f"**{label}** [{res['source'].upper()}]")
    
    if history.get("action"):
        st.caption(f"✅ {history['action']} ({history.get('date', '')})")

    if res.get("problem"):
        if res["status"] == "stopped":
            st.error(f"⚫ {res['problem']}")
        elif res["status"] == "critical":
            st.error(f"🔴 {res['problem']}")
        elif res["status"] == "warning":
            st.warning(f"🟠 {res['problem']}")
        elif res["status"] == "info":
            st.info(f"🟡 {res['problem']}")

    if is_pending:
        url = get_campaign_url(res["source"], res["campaign_id"])
        st.markdown(f"[🔗 Открыть рекламный кабинет]({url})")
        
        action_text = "Пополнить" if "бюджет" in res.get("problem", "").lower() else "Исправить"
        st.markdown(f"**После действия нажмите:**")
        
        if st.button("✅ Отметить выполненным", key=f"{label}_confirm"):
            st.session_state.history[label] = {
                "action": f"{action_text} выполнено",
                "date": datetime.now().strftime("%d.%m.%Y %H:%M")
            }
            st.session_state.pending_top_ups[label] = False
            save_history(st.session_state.history)
            st.rerun()
    else:
        if res.get("actions"):
            cols = st.columns(len(res["actions"]))
            for i, act in enumerate(res["actions"]):
                with cols[i]:
                    if st.button(act, key=f"{label}_{act}"):
                        if act in ["Пополнить", "Исправить"]:
                            st.session_state.pending_top_ups[label] = True
                            st.session_state.history[label] = {
                                "action": f"Ожидает: {act}",
                                "date": datetime.now().strftime("%d.%m.%Y %H:%M")
                            }
                        elif act == "Игнорировать":
                            hide_until = datetime.now() + timedelta(hours=24)
                            st.session_state.history[label] = {
                                "action": act,
                                "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                                "hide_until": hide_until.strftime("%d.%m.%Y %H:%M")
                            }
                        elif act == "Закрыть":
                            st.session_state.history[label] = {
                                "action": act,
                                "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                                "session_closed": True
                            }
                        else:
                            st.session_state.history[label] = {
                                "action": act,
                                "date": datetime.now().strftime("%d.%m.%Y %H:%M")
                            }
                        save_history(st.session_state.history)
                        st.rerun()
# =========================
# ОБРАБОТКА ВХОДА ЧЕРЕЗ ЯНДЕКС
# =========================
def exchange_code_for_token(code):
    """Обменивает временный code на постоянный токен"""
    token_url = "https://oauth.yandex.ru/token"
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": YANDEX_CLIENT_ID,
        "client_secret": YANDEX_CLIENT_SECRET
    }
    try:
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            token_data = response.json()
            return token_data.get("access_token")
    except Exception as e:
        st.error(f"Ошибка получения токена: {e}")
    return None

# Проверяем, есть ли code в URL (после входа через Яндекс)
query_params = st.experimental_get_query_params()
if "code" in query_params and "yandex_token" not in st.session_state:
    code = query_params["code"][0]
    token = exchange_code_for_token(code)
    if token:
        st.session_state["yandex_token"] = token
        st.success("✅ Успешно подключено к Яндекс.Директ!")
        # Убираем code из URL
        st.experimental_set_query_params()
        st.rerun()

# =========================
# ИНТЕРФЕЙС STREAMLIT
# =========================

# =========================
# ЯНДЕКС OAUTH ЛОГИКА
# =========================
def get_yandex_auth_url():
    """Возвращает ссылку для входа через Яндекс"""
    return (
        f"https://oauth.yandex.ru/authorize?"
        f"response_type=code&"
        f"client_id={YANDEX_CLIENT_ID}&"
        f"redirect_uri={YANDEX_REDIRECT_URI}"
    )
st.set_page_config(page_title="Namectus", page_icon="📊", layout="wide")

# Инициализация session_state
if "history" not in st.session_state:
    st.session_state.history = load_history()
if "pending_top_ups" not in st.session_state:
    st.session_state.pending_top_ups = {}

# Шапка
st.markdown(f"# 📅 NAMECTUS | {datetime.now().strftime('%d.%m.%Y')}")
st.markdown("---")

# Кнопка входа через Яндекс
if "yandex_token" not in st.session_state:
    auth_url = get_yandex_auth_url()
    st.markdown(f"### 🔐 Подключите рекламный кабинет")
    st.markdown(f"[Войти через Яндекс]({auth_url})")
    st.caption("После входа Namectus сможет автоматически получать данные из Яндекс.Директ")
    st.markdown("---")
else:
    st.success("✅ Вы подключены к Яндекс.Директ")
    if st.button("Выйти из аккаунта"):
        del st.session_state["yandex_token"]
        st.rerun()

# Кнопка пересканирования
if st.button("🔄 Пересканировать"):
    for label, hist in st.session_state.history.items():
        if "session_closed" in hist:
            del hist["session_closed"]
        if "hide_until" in hist:
            del hist["hide_until"]
    save_history(st.session_state.history)
    st.rerun()

# Загрузка данных
try:
    SHEET_ID = "10cf-dT0Sd5K2c-39x_7zOxbyUdB8Lsr264VdTMhNP7E"
    url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
    df = pd.read_csv(url)
    results = analyze_campaigns(df)
    results = filter_hidden(results, st.session_state.history, st.session_state.pending_top_ups)
except Exception as e:
    st.error(f"Ошибка загрузки данных: {e}")
    st.stop()

if not results:
    st.success("✅ Все кампании скрыты или в норме. Отличная работа!")
    st.stop()

# =========================
# ГРУППИРОВКА
# =========================
stopped = [r for r in results if r["status"] == "stopped"]
critical = [r for r in results if r["status"] == "critical"]
warning = [r for r in results if r["status"] == "warning"]
info = [r for r in results if r["status"] == "info"]
ok = [r for r in results if r["status"] == "ok"]
data_accumulation = [r for r in results if r["status"] == "data_accumulation"]

# =========================
# ВИЗУАЛЬНАЯ ПАНЕЛЬ С КРУЖКАМИ
# =========================
st.markdown("### 🔍 Состояние кампаний")

# Создаём 5 колонок для кружков
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    if st.button(f"⚫ {len(stopped)}", key="btn_stopped", use_container_width=True):
        st.session_state["show_stopped"] = not st.session_state.get("show_stopped", False)
    st.caption("Остановлены")

with col2:
    if st.button(f"🔴 {len(critical)}", key="btn_critical", use_container_width=True):
        st.session_state["show_critical"] = not st.session_state.get("show_critical", False)
    st.caption("Критично")

with col3:
    if st.button(f"🟠 {len(warning)}", key="btn_warning", use_container_width=True):
        st.session_state["show_warning"] = not st.session_state.get("show_warning", False)
    st.caption("Требует внимания")

with col4:
    if st.button(f"🟡 {len(info)}", key="btn_info", use_container_width=True):
        st.session_state["show_info"] = not st.session_state.get("show_info", False)
    st.caption("Плановое")

with col5:
    if st.button(f"🟢 {len(ok)}", key="btn_ok", use_container_width=True):
        st.session_state["show_ok"] = not st.session_state.get("show_ok", False)
    st.caption("Всё в порядке")

st.markdown("---")

# =========================
# РАСКРЫВАЮЩИЕСЯ РАЗДЕЛЫ
# =========================

# ⚫ ОСТАНОВЛЕНЫ
if stopped and st.session_state.get("show_stopped", False):
    st.markdown("### ⚫ ОСТАНОВЛЕНЫ (Бюджет исчерпан)")
    for res in stopped:
        label = res["label"]
        history = st.session_state.history.get(label, {})
        is_pending = st.session_state.pending_top_ups.get(label, False)
        render_campaign_card(res, label, history, is_pending)

# 🔴 КРИТИЧЕСКИЕ
if critical and st.session_state.get("show_critical", False):
    st.markdown("### 🔴 КРИТИЧЕСКИЕ (Срочно!)")
    for res in critical:
        label = res["label"]
        history = st.session_state.history.get(label, {})
        is_pending = st.session_state.pending_top_ups.get(label, False)
        render_campaign_card(res, label, history, is_pending)

# 🟠 ПРЕДУПРЕЖДЕНИЯ
if warning and st.session_state.get("show_warning", False):
    st.markdown("### 🟠 ТРЕБУЕТ ВНИМАНИЯ")
    for res in warning:
        label = res["label"]
        history = st.session_state.history.get(label, {})
        is_pending = st.session_state.pending_top_ups.get(label, False)
        render_campaign_card(res, label, history, is_pending)

# 🟡 ИНФОРМАЦИЯ
if info and st.session_state.get("show_info", False):
    st.markdown("### 🟡 ПЛАНОВОЕ ЗАВЕРШЕНИЕ БЮДЖЕТА")
    for res in info:
        label = res["label"]
        history = st.session_state.history.get(label, {})
        is_pending = st.session_state.pending_top_ups.get(label, False)
        render_campaign_card(res, label, history, is_pending)

# 🟢 ВСЁ В ПОРЯДКЕ
if ok and st.session_state.get("show_ok", False):
    st.markdown("### 🟢 ВСЁ В ПОРЯДКЕ")
    for res in ok:
        label = res["label"]
        st.markdown(f"- **{label}**: Работает стабильно")

# ⚪ НАКОПЛЕНИЕ ДАННЫХ
if data_accumulation:
    st.markdown("### ⚪ НАКОПЛЕНИЕ ДАННЫХ")
    for res in data_accumulation:
        st.markdown(f"- **{res['label']}**: {res['problem']}")

st.markdown("---")
st.caption("Namectus v0.4 | Dashboard")