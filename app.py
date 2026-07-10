import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv

# Импорты...
from dotenv import load_dotenv

st.write("🚨 DEBUG 000 - Файл загружается!")  # ← ДОБАВИТЬ ЗДЕСЬ!

# =========================
# БЕЗОПАСНАЯ ЗАГРУЗКА КЛЮЧЕЙ
# =========================
load_dotenv()
YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID")
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET")
YANDEX_REDIRECT_URI = os.getenv("YANDEX_REDIRECT_URI", "https://namectus-app.onrender.com/callback")

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
# УНИВЕРСАЛЬНОЕ ХРАНЕНИЕ ТОКЕНОВ
# =========================
TOKENS_FILE = "tokens.json"

def save_token(source, token):
    """Сохраняет токен для любого источника (yandex, google, meta)"""
    st.write(f"🔍 DEBUG save_token: Вызвана для {source}")  # ← ДОБАВИТЬ!
    tokens = load_all_tokens()
    tokens[source] = {
        "token": token,
        "saved_at": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)
    st.write(f"🔍 DEBUG save_token: Файл {TOKENS_FILE} сохранён!")  # ← ДОБАВИТЬ!

def load_token(source):
    """Загружает токен для конкретного источника"""
    tokens = load_all_tokens()
    return tokens.get(source, {}).get("token")

def load_all_tokens():
    """Загружает все токены из файла"""
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

# =========================
# ЯДРО АНАЛИЗА
# =========================
def analyze_campaigns(df: pd.DataFrame):
    results = []
    periods = CONFIG["periods"]
    thresholds = CONFIG["thresholds"]

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
                "campaign_id": campaign_id,
                "project": project
            })
            continue

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
            "campaign_id": campaign_id,
            "project": project
        }

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
            st.error(f" {res['problem']}")
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
        else:
            st.error(f"Ошибка: {response.status_code} - {response.text}")
    except Exception as e:
        st.error(f"Ошибка получения токена: {e}")
    return None

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

# =========================
# ФУНКЦИЯ ДЛЯ ГРУППИРОВКИ ПО ПРОЕКТАМ
# =========================
def render_grouped_by_projects(items, section_name):
    """Группирует кампании по проектам"""
    if not items:
        return
    
    projects = {}
    for item in items:
        project = item.get("project", "Без проекта")
        if project not in projects:
            projects[project] = []
        projects[project].append(item)
    
    for project, project_items in projects.items():
        st.markdown(f"####  {project}")
        for res in project_items:
            label = res["label"]
            history = st.session_state.history.get(label, {})
            is_pending = st.session_state.pending_top_ups.get(label, False)
            render_campaign_card(res, label, history, is_pending)

# =========================
# ТЕСТ API ЯНДЕКС.ДИРЕКТ
# =========================
def fetch_yandex_test_data(token):
    """Тестовая функция для получения данных из API Яндекс.Директ"""
    url = "https://api.direct.yandex.com/json/v5/reports"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept-Language": "ru",
        "processingMode": "auto"
    }
    
    body = {
        "params": {
            "SelectionCriteria": {},
            "FieldNames": ["CampaignName", "Impressions", "Clicks", "Cost", "Conversions"],
            "DateRangeType": "LAST_7_DAYS",
            "ReportName": "NamectusTestReport",
            "ReportType": "CAMPAIGN_PERFORMANCE_REPORT"
        }
    }
    
    try:
        response = requests.post(url, json=body, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                return f"Ошибка API: {data['error']}"
            if "data" in data:
                return data["data"]
            return "Запрос принят, но данных нет (или отчет еще генерируется)"
        else:
            return f"HTTP Ошибка: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Исключение: {e}"

# =========================
# ИНТЕРФЕЙС STREAMLIT
# =========================
st.set_page_config(page_title="Namectus", page_icon="📊", layout="wide")

# Инициализация session_state
if "history" not in st.session_state:
    st.session_state.history = load_history()
if "pending_top_ups" not in st.session_state:
    st.session_state.pending_top_ups = {}
if "show_section" not in st.session_state:
    st.session_state.show_section = {}

# 🔥 Автоматически загружаем токен, если он сохранён
if "yandex_token" not in st.session_state:
    saved_token = load_token("yandex")
    if saved_token:
        st.session_state["yandex_token"] = saved_token
        st.rerun()

# Проверяем, есть ли code в URL (после входа через Яндекс)
query_params = st.query_params
if "code" in query_params and "yandex_token" not in st.session_state:
    st.write("🔍 DEBUG: Код получен из URL!")  # ← ДОБАВИТЬ!
    code = query_params["code"]
    token = exchange_code_for_token(code)
    if token:
        st.write("🔍 DEBUG: Токен получен от Яндекса!")  # ← ДОБАВИТЬ!
        st.session_state["yandex_token"] = token
        save_token("yandex", token)
        st.write("🔍 DEBUG: Токен сохранён в файл!")  # ← ДОБАВИТЬ!
        st.success("✅ Успешно подключено к Яндекс.Директ! Токен сохранён.")
        st.query_params.clear()
        st.rerun()
    else:
        st.error("❌ ОШИБКА: Токен не получен!")  # ← ДОБАВИТЬ!

# Шапка
st.markdown(f"#  NAMECTUS | {datetime.now().strftime('%d.%m.%Y')}")
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
    st.write("🔍 DEBUG 111 - Код обновился!") 
    # Кнопку выхода убрали из шапки

# ТЕСТОВЫЙ БЛОК: ПОЛУЧЕНИЕ ДАННЫХ ИЗ API
if "yandex_token" in st.session_state:
    st.markdown("---")
    st.markdown("### 🧪 Тест API Яндекс.Директ")
    
    if st.button("🚀 Запросить данные из API"):
        with st.spinner("Яндекс думает..."):
            raw_data = fetch_yandex_test_data(st.session_state["yandex_token"])
            
        if isinstance(raw_data, str):
            st.error(raw_data)
        else:
            st.success("✅ Данные получены!")
            st.json(raw_data)
            
            if "Rows" in raw_data:
                rows = raw_data["Rows"]
                if rows:
                    df_test = pd.DataFrame([row["Cells"] for row in rows])
                    st.dataframe(df_test)

# Кнопки управления
col1, col2 = st.columns(2)
with col1:
    if st.button(" Пересканировать", use_container_width=True):
        for label, hist in st.session_state.history.items():
            if "session_closed" in hist:
                del hist["session_closed"]
            if "hide_until" in hist:
                del hist["hide_until"]
        save_history(st.session_state.history)
        st.session_state.show_section = {}
        st.rerun()

with col2:
    if st.button("🔽 Свернуть всё", use_container_width=True):
        st.session_state.show_section = {}
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
# ГРУППИРОВКА ПО СТАТУСАМ
# =========================
stopped = [r for r in results if r["status"] == "stopped"]
critical = [r for r in results if r["status"] == "critical"]
warning = [r for r in results if r["status"] == "warning"]
info = [r for r in results if r["status"] == "info"]
ok = [r for r in results if r["status"] == "ok"]
data_accumulation = [r for r in results if r["status"] == "data_accumulation"]

# =========================
# ОГРОМНЫЕ КАРТОЧКИ
# =========================
st.markdown("### 🔍 Состояние кампаний")

st.markdown("""
<style>
.big-card {
    background: white;
    border-radius: 20px;
    padding: 15px 10px;
    text-align: center;
    cursor: pointer;
    border: 3px solid #e0e0e0;
    transition: all 0.3s;
    height: 220px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    box-sizing: border-box;
    margin-bottom: 10px;
}
.big-card:hover {
    transform: scale(1.02);
    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
}
.big-number {
    font-size: 60px;
    font-weight: bold;
    margin: 0;
    line-height: 1;
}
.big-label {
    font-size: 18px;
    margin-top: 15px;
    color: #666;
    font-weight: 500;
}
</style>
""", unsafe_allow_html=True)

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.markdown(f"""
    <div class="big-card" style="border-color: #333;">
        <div class="big-number" style="color: #333;">⚫ {len(stopped)}</div>
        <div class="big-label">Остановлены</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Открыть остановленные", key="btn_stopped", use_container_width=True):
        st.session_state.show_section["stopped"] = not st.session_state.show_section.get("stopped", False)
        
with col2:
    st.markdown(f"""
    <div class="big-card" style="border-color: #dc3545;">
        <div class="big-number" style="color: #dc3545;">🔴 {len(critical)}</div>
        <div class="big-label">Критично</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Открыть критичные", key="btn_critical", use_container_width=True):
        st.session_state.show_section["critical"] = not st.session_state.show_section.get("critical", False)

with col3:
    st.markdown(f"""
    <div class="big-card" style="border-color: #fd7e14;">
        <div class="big-number" style="color: #fd7e14;"> {len(warning)}</div>
        <div class="big-label">Требует внимания</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Открыть требующие внимания", key="btn_warning", use_container_width=True):
        st.session_state.show_section["warning"] = not st.session_state.show_section.get("warning", False)

with col4:
    st.markdown(f"""
    <div class="big-card" style="border-color: #ffc107;">
        <div class="big-number" style="color: #ffc107;">🟡 {len(info)}</div>
        <div class="big-label">Плановое</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Открыть плановые", key="btn_info", use_container_width=True):
        st.session_state.show_section["info"] = not st.session_state.show_section.get("info", False)

with col5:
    st.markdown(f"""
    <div class="big-card" style="border-color: #28a745;">
        <div class="big-number" style="color: #28a745;">🟢 {len(ok)}</div>
        <div class="big-label">Всё в порядке</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Открыть работающие", key="btn_ok", use_container_width=True):
        st.session_state.show_section["ok"] = not st.session_state.show_section.get("ok", False)

with col6:
    st.markdown(f"""
    <div class="big-card" style="border-color: #6c757d;">
        <div class="big-number" style="color: #6c757d;"> {len(data_accumulation)}</div>
        <div class="big-label">Накопление данных</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Открыть накопление", key="btn_data_acc", use_container_width=True):
        st.session_state.show_section["data_accumulation"] = not st.session_state.show_section.get("data_accumulation", False)

st.markdown("---")

# =========================
# РАСКРЫВАЮЩИЕСЯ РАЗДЕЛЫ
# =========================

if stopped and st.session_state.show_section.get("stopped", False):
    st.markdown("###  ОСТАНОВЛЕНЫ (Бюджет исчерпан)")
    render_grouped_by_projects(stopped, "stopped")

if critical and st.session_state.show_section.get("critical", False):
    st.markdown("### 🔴 КРИТИЧЕСКИЕ (Срочно!)")
    render_grouped_by_projects(critical, "critical")

if warning and st.session_state.show_section.get("warning", False):
    st.markdown("### 🟠 ТРЕБУЕТ ВНИМАНИЯ")
    render_grouped_by_projects(warning, "warning")

if info and st.session_state.show_section.get("info", False):
    st.markdown("### 🟡 ПЛАНОВОЕ ЗАВЕРШЕНИЕ БЮДЖЕТА")
    render_grouped_by_projects(info, "info")

if ok and st.session_state.show_section.get("ok", False):
    st.markdown("### 🟢 ВСЁ В ПОРЯДКЕ")
    for res in ok:
        label = res["label"]
        st.markdown(f"- **{label}**: Работает стабильно")

if data_accumulation and st.session_state.show_section.get("data_accumulation", False):
    st.markdown("###  НАКОПЛЕНИЕ ДАННЫХ")
    render_grouped_by_projects(data_accumulation, "data_accumulation")

st.markdown("---")
st.caption("Namectus v0.8 | Dashboard с группировкой по проектам")

# Техническая кнопка сброса токена
if "yandex_token" in st.session_state:
    st.markdown("---")
    if st.button("🔧 Сбросить подключение к Яндексу", key="reset_token"):
        del st.session_state["yandex_token"]
        if os.path.exists(TOKENS_FILE):
            os.remove(TOKENS_FILE)
        st.rerun()