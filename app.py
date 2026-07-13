import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv

# =========================
# БЕЗОПАСНАЯ ЗАГРУЗКА КЛЮЧЕЙ
# =========================
load_dotenv()
YANDEX_CLIENT_ID = os.getenv("YANDEX_CLIENT_ID")
YANDEX_CLIENT_SECRET = os.getenv("YANDEX_CLIENT_SECRET")
YANDEX_REDIRECT_URI = os.getenv("YANDEX_REDIRECT_URI", "https://namectus-app.onrender.com/callback")

# =========================
# ФАЙЛЫ ХРАНЕНИЯ
# =========================
HISTORY_FILE = "action_history.json"
PROJECTS_FILE = "projects.json"
TOKENS_FILE = "tokens.json"

# =========================
# КОНФИГУРАЦИЯ
# =========================
CONFIG = {
    "periods": {"recent_days": 3, "history_days": 21, "min_data_days": 7},
    "thresholds": {"ctr_min": 0.005, "ctr_max": 0.15, "cpa_target": 2000.0, "conversion_drop_pct": 0.4}
}

# =========================
# УПРАВЛЕНИЕ ПРОЕКТАМИ (КАТАЛОГ)
# =========================
def load_projects():
    if os.path.exists(PROJECTS_FILE):
        try:
            with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_projects(projects):
    with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)

def add_project(name):
    projects = load_projects()
    if name not in projects:
        projects.append(name)
        save_projects(projects)

def remove_project(name):
    projects = load_projects()
    if name in projects:
        projects.remove(name)
        save_projects(projects)

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
# ОБРАБОТКА ВХОДА ЧЕРЕЗ ЯНДЕКС
# =========================
def exchange_code_for_token(code):
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
            return response.json().get("access_token")
        else:
            st.error(f"Ошибка Яндекса: {response.status_code}")
    except Exception as e:
        st.error(f"Ошибка получения токена: {e}")
    return None

def get_yandex_auth_url():
    return (
        f"https://oauth.yandex.ru/authorize?"
        f"response_type=code&"
        f"client_id={YANDEX_CLIENT_ID}&"
        f"redirect_uri={YANDEX_REDIRECT_URI}"
    )

# =========================
# ЯДРО АНАЛИЗА
# =========================
def analyze_campaigns(df: pd.DataFrame):
    from namectus_engine import NamectusEngine
    engine = NamectusEngine()
    
    results = []
    periods = CONFIG["periods"]
    
    for (project, campaign), camp_df in df.groupby(["project", "campaign"]):
        camp_df = camp_df.sort_values("date").reset_index(drop=True)
        total_days = len(camp_df)
        source = camp_df["source"].iloc[0]
        campaign_id = str(camp_df["campaign_id"].iloc[0])
        
        if total_days < periods["min_data_days"]:
            results.append({
                "label": f"{project} / {campaign}", 
                "status": "data_accumulation",
                "problem": f"Доступно только {total_days} дней данных",
                "actions": ["Наблюдать", "Закрыть"],
                "source": source, "campaign_id": campaign_id, "project": project
            })
            continue
        
        try:
            budget_limit = camp_df["budget"].iloc[0]
        except:
            budget_limit = camp_df["cost"].sum() * 1.5
        
        total_spent = camp_df["cost"].sum()
        remaining = budget_limit - total_spent
        avg_daily = total_spent / max(total_days, 1)
        total_conv = int(camp_df["conversions"].sum())
        total_clicks = int(camp_df["clicks"].sum())
        total_impressions = int(camp_df["impressions"].sum())
        
        campaign_info = {
            'days': total_days, 'spend': total_spent, 'currency': '₽',
            'conversions': total_conv, 'clicks': total_clicks, 'status': 'active',
            'budget_remaining': remaining, 'daily_spend': avg_daily,
            'previous_cpa': 0, 'current_cpa': total_spent / max(total_conv, 1),
            'previous_ctr': 0.01, 'current_ctr': total_clicks / max(total_impressions, 1),
            'broken_links_count': 0
        }
        
        alerts = engine.check_campaign(campaign_info)
        base = {"label": f"{project} / {campaign}", "source": source, "campaign_id": campaign_id, "project": project}
        
        if not alerts:
            results.append({**base, "status": "ok", "problem": "", "actions": []})
        else:
            main_alert = alerts[0]
            if 'бюджет' in main_alert['title'].lower() and main_alert['severity'] == 'critical':
                status, actions = "stopped", ["Пополнить", "Наблюдать", "Игнорировать"]
            elif 'бюджет' in main_alert['title'].lower() and main_alert['severity'] == 'warning':
                status, actions = "info", ["Пополнить", "Наблюдать", "Игнорировать"]
            elif main_alert['severity'] == 'critical':
                status, actions = "critical", ["Исправить", "Наблюдать", "Игнорировать"]
            else:
                status, actions = "warning", ["Исправить", "Наблюдать", "Игнорировать"]
            
            results.append({**base, "status": status, "problem": main_alert['description'], "actions": actions})
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
                    if now < datetime.strptime(h["hide_until"], "%d.%m.%Y %H:%M"): continue
                except: pass
            if h.get("action") == "Закрыть" and h.get("session_closed"): continue
        filtered.append(res)
    return filtered

# =========================
# ОТРИСОВКА КАРТОЧЕК
# =========================
def render_grouped_by_projects(items):
    if not items: return
    projects = {}
    for item in items:
        project = item.get("project", "Без проекта")
        if project not in projects: projects[project] = []
        projects[project].append(item)
    
    for project, project_items in projects.items():
        st.markdown(f"#### 📁 {project}")
        for res in project_items:
            label = res["label"]
            history = st.session_state.history.get(label, {})
            st.markdown("---")
            st.markdown(f"**{label}** [{res['source'].upper()}]")
            if history.get("action"): st.caption(f"✅ {history['action']} ({history.get('date', '')})")
            
            if res.get("problem"):
                if res["status"] in ["stopped", "critical"]: st.error(f"🔴 {res['problem']}")
                elif res["status"] == "warning": st.warning(f"🟠 {res['problem']}")
                elif res["status"] == "info": st.info(f"🟡 {res['problem']}")

            if res.get("actions"):
                cols = st.columns(len(res["actions"]))
                for i, act in enumerate(res["actions"]):
                    with cols[i]:
                        if st.button(act, key=f"{label}_{act}"):
                            if act in ["Пополнить", "Исправить"]:
                                st.session_state.pending_top_ups[label] = True
                                st.session_state.history[label] = {"action": f"Ожидает: {act}", "date": datetime.now().strftime("%d.%m.%Y %H:%M")}
                            elif act == "Игнорировать":
                                hide_until = datetime.now() + timedelta(hours=24)
                                st.session_state.history[label] = {"action": act, "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "hide_until": hide_until.strftime("%d.%m.%Y %H:%M")}
                            elif act == "Закрыть":
                                st.session_state.history[label] = {"action": act, "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "session_closed": True}
                            else:
                                st.session_state.history[label] = {"action": act, "date": datetime.now().strftime("%d.%m.%Y %H:%M")}
                            save_history(st.session_state.history)
                            st.rerun()

# =========================
# НАСТРОЙКА СТРАНИЦЫ И СТИЛИ
# =========================
st.set_page_config(page_title="Namectus", page_icon="📊", layout="wide")
st.markdown("""
<style>
    .scan-button button { background-color: #4A90E2 !important; color: white !important; border: none !important; border-radius: 8px !important; font-size: 16px !important; width: 200px !important; padding: 10px 20px !important; }
    .scan-button button:hover { background-color: #357ABD !important; }
    .stSpinner > div { border-color: #4A90E2 !important; }
</style>
""", unsafe_allow_html=True)

# =========================
# ИНИЦИАЛИЗАЦИЯ (ПРИОРИТЕТНАЯ ЗАГРУЗКА ТОКЕНА)
# =========================
if "history" not in st.session_state: st.session_state.history = load_history()
if "pending_top_ups" not in st.session_state: st.session_state.pending_top_ups = {}
if "scan_results" not in st.session_state: st.session_state.scan_results = None
if "last_scan_time" not in st.session_state: st.session_state.last_scan_time = None

# 🔥 ГЛАВНОЕ ИСПРАВЛЕНИЕ: Загружаем токен ПЕРВЫМ ДЕЛОМ
if "yandex_token" not in st.session_state:
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
                token_data = json.load(f)
                token = token_data.get("yandex", {}).get("token")
                if token:
                    st.session_state["yandex_token"] = token
        except Exception as e:
            print(f"Ошибка загрузки токена: {e}")

# Обработка кода от Яндекса (после OAuth)
query_params = st.query_params
if "code" in query_params and "yandex_token" not in st.session_state:
    token = exchange_code_for_token(query_params["code"])
    if token:
        st.session_state["yandex_token"] = token
        with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"yandex": {"token": token, "saved_at": datetime.now().strftime("%d.%m.%Y %H:%M")}}, f, ensure_ascii=False, indent=2)
        st.query_params.clear()
        st.rerun()

# =========================
# БОКОВАЯ ПАНЕЛЬ (САЙДБАР)
# =========================
with st.sidebar:
    st.markdown("### 📁 Каталог проектов")
    st.caption("Здесь хранится список ваших проектов. Это справочник.")
    
    # Добавление проекта
    new_proj = st.text_input("Название нового проекта:", placeholder="Например: Магазин цветов")
    if st.button(" Добавить проект"):
        if new_proj:
            add_project(new_proj)
            st.success(f"Проект '{new_proj}' добавлен!")
            st.rerun()
    
    # Список проектов с кнопками удаления
    projects = load_projects()
    if projects:
        st.markdown("---")
        for proj in projects:
            col1, col2 = st.columns([3, 1])
            with col1: st.markdown(f" {proj}")
            with col2: 
                if st.button("🗑", key=f"del_{proj}"):
                    remove_project(proj)
                    st.rerun()
    else:
        st.caption("Список пуст. Добавьте первый проект.")

    st.markdown("---")
    st.markdown("###  Настройки (SaaS)")
    # Эти переключатели уже заложены в архитектуру для будущей i18n и мультивалютности!
    st.selectbox("Язык интерфейса", ["Русский 🇷🇺", "English 🇬🇧"], index=0)
    st.selectbox("Валюта отчетов", ["RUB (₽)", "USD ($)", "EUR (€)"], index=0)

    st.markdown("---")
    if "yandex_token" in st.session_state:
        if st.button("🔄 Пересканировать"):
            st.session_state.scan_results = None
            st.rerun()
        if st.button("🔧 Выйти из Яндекса"):
            del st.session_state["yandex_token"]
            if os.path.exists(TOKENS_FILE): os.remove(TOKENS_FILE)
            st.session_state.scan_results = None
            st.rerun()

# =========================
# ШАПКА
# =========================
now = datetime.now()
st.markdown(f"# NAMECTUS v1.0 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
st.markdown("---")

# =========================
# ГЛАВНЫЙ ЭКРАН
# =========================

# 1. Если токена нет — показываем вход
if "yandex_token" not in st.session_state:
    st.markdown("### 👋 Добро пожаловать в Namectus")
    st.markdown("Для начала работы подключите рекламный кабинет.")
    st.markdown(f'[🔐 Войти через Яндекс]({get_yandex_auth_url()})')
    st.caption("После входа Namectus сможет получать данные из вашего кабинета")
    st.stop()

# 2. Если токен есть, но сканирование еще не запускали
if st.session_state.scan_results is None:
    st.success("☑ Вы подключены к Яндекс.Директ")
    st.markdown("Нажмите кнопку ниже, чтобы проверить состояние кампаний.")
    
    st.markdown('<div class="scan-button">', unsafe_allow_html=True)
    if st.button("🔍 Сканировать"):
        with st.spinner("🔄 Анализируем данные... Это может занять до 30 секунд"):
            try:
                # Временно читаем из Google Sheets (пока нет реального API)
                SHEET_ID = "10cf-dT0Sd5K2c-39x_7zOxbyUdB8Lsr264VdTMhNP7E"
                df = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv")
                
                st.info("📥 Загружаем данные...")
                results = analyze_campaigns(df)
                results = filter_hidden(results, st.session_state.history, st.session_state.pending_top_ups)
                
                st.info("🧠 Анализируем...")
                st.session_state.scan_results = results
                st.session_state.show_problems = False
                st.session_state.group_by = None
                st.session_state.last_scan_time = datetime.now()
                
                st.success(f"✅ Проанализировано кампаний: {len(results)}")
                st.balloons()
                st.rerun()
                
            except Exception as e:
                import traceback
                st.error(f"❌ Ошибка загрузки данных: {e}")
                st.warning("💡 Хотите протестировать интерфейс?")
                if st.button("🧪 Загрузить тестовые данные"):
                    test_data = {
                        'project': ['Тестовый проект', 'Тестовый проект', 'Тестовый проект'], 
                        'campaign': ['Баннер на поиске', 'РСЯ Товары', 'Поиск Бренд'], 
                        'source': ['yandex', 'yandex', 'yandex'], 
                        'campaign_id': [12345, 12346, 12347], 
                        'date': pd.date_range('2026-07-01', periods=3), 
                        'cost': [368.51, 12500, 5000], 
                        'conversions': [0, 0, 10], 
                        'clicks': [45, 340, 200], 
                        'impressions': [9000, 50000, 15000], 
                        'budget': [1000, 15000, 10000]
                    }
                    df_test = pd.DataFrame(test_data)
                    st.session_state.scan_results = analyze_campaigns(df_test)
                    st.session_state.show_problems = False
                    st.session_state.last_scan_time = datetime.now()
                    st.success("✅ Тестовые данные загружены!")
                    st.rerun()
                st.stop()
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# 3. Результаты сканирования
if st.session_state.scan_results is not None:
    results = st.session_state.scan_results
    
    stopped = [r for r in results if r["status"] == "stopped"]
    critical = [r for r in results if r["status"] == "critical"]
    warning = [r for r in results if r["status"] == "warning"]
    info = [r for r in results if r["status"] == "info"]
    data_accumulation = [r for r in results if r["status"] == "data_accumulation"]
    
    real_problems = stopped + critical + warning + info
    has_problems = len(real_problems) > 0
    only_accumulation = len(data_accumulation) > 0 and not has_problems

    if not has_problems and not only_accumulation:
        st.success("✅ Всё отлично! Проблем не обнаружено.")
        if st.button("🔄 Сканировать заново", use_container_width=True): 
            st.session_state.scan_results = None
            st.rerun()
            
    elif only_accumulation:
        st.info("⚪ Идёт накопление данных. Пока рано делать выводы.")
        if st.button("🔄 Сканировать заново", use_container_width=True): 
            st.session_state.scan_results = None
            st.rerun()
            
    else:
        st.warning(f"⚠ Есть проблема (найдено: {len(real_problems)})")
        
        if not st.session_state.get("show_problems", False):
            if st.button("👉 Открыть подробности", key="btn_show_problems"): 
                st.session_state.show_problems = True
                st.rerun()
        else:
            st.markdown("---")
            st.markdown("### Как посмотреть?")
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("📁 По проектам", key="btn_group_projects", use_container_width=True): 
                    st.session_state.group_by = "projects"
                    st.rerun()
            
            with col2:
                if st.button("⚠ По важности", key="btn_group_priority", use_container_width=True): 
                    st.session_state.group_by = "priority"
                    st.rerun()
            
            st.markdown("---")
            
            if st.session_state.get("group_by") == "projects":
                st.markdown("### 📁 Список по проектам")
                render_grouped_by_projects(real_problems)
                    
            elif st.session_state.get("group_by") == "priority":
                st.markdown("### ⚠ Список по важности")
                if critical: 
                    st.markdown("#### 🔴 Критично")
                    render_grouped_by_projects(critical)
                if warning or info: 
                    st.markdown("#### 🟡 Требует внимания")
                    render_grouped_by_projects(warning + info)
                if stopped: 
                    st.markdown("####  Остановлены")
                    render_grouped_by_projects(stopped)
            
            st.markdown("---")
            if st.button("✅ Все проблемы решены. Скрыть и начать заново", use_container_width=True):
                st.session_state.scan_results = None
                st.session_state.show_problems = False
                st.session_state.group_by = None
                st.rerun()