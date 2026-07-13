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
    tokens = load_all_tokens()
    tokens[source] = {
        "token": token,
        "saved_at": datetime.now().strftime("%d.%m.%Y %H:%M")
    }
    with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)

def load_token(source):
    tokens = load_all_tokens()
    return tokens.get(source, {}).get("token")

def load_all_tokens():
    if os.path.exists(TOKENS_FILE):
        try:
            with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

# =========================
# ЯДРО АНАЛИЗА (с namectus_engine)
# =========================
def analyze_campaigns(df: pd.DataFrame):
    """Новый мозг: использует NamectusEngine, но возвращает данные в старом формате для UI"""
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
        total_conv = int(camp_df["conversions"].sum())
        total_clicks = int(camp_df["clicks"].sum())
        total_impressions = int(camp_df["impressions"].sum())
        
        campaign_info = {
            'days': total_days,
            'spend': total_spent,
            'currency': '₽',
            'conversions': total_conv,
            'clicks': total_clicks,
            'status': 'active',
            'budget_remaining': remaining,
            'daily_spend': avg_daily,
            'previous_cpa': 0,
            'current_cpa': total_spent / max(total_conv, 1),
            'previous_ctr': 0.01,
            'current_ctr': total_clicks / max(total_impressions, 1),
            'broken_links_count': 0
        }
        
        alerts = engine.check_campaign(campaign_info)
        
        base = {
            "label": f"{project} / {campaign}", 
            "source": source, 
            "campaign_id": campaign_id,
            "project": project
        }
        
        if not alerts:
            results.append({
                **base,
                "status": "ok",
                "problem": "",
                "actions": []
            })
        else:
            main_alert = alerts[0]
            
            if 'бюджет' in main_alert['title'].lower() and main_alert['severity'] == 'critical':
                status = "stopped"
                actions = ["Пополнить", "Наблюдать", "Игнорировать"]
            elif 'бюджет' in main_alert['title'].lower() and main_alert['severity'] == 'warning':
                status = "info"
                actions = ["Пополнить", "Наблюдать", "Игнорировать"]
            elif main_alert['severity'] == 'critical':
                status = "critical"
                actions = ["Исправить", "Наблюдать", "Игнорировать"]
            else:
                status = "warning"
                actions = ["Исправить", "Наблюдать", "Игнорировать"]
            
            results.append({
                **base,
                "status": status,
                "problem": main_alert['description'],
                "actions": actions
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
# ГРУППИРОВКА ПО ПРОЕКТАМ
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
# КАРТОЧКА КАМПАНИИ
# =========================
def render_campaign_card(res, label, history, is_pending):
    st.markdown("---")
    st.markdown(f"**{label}** [{res['source'].upper()}]")
    
    if history.get("action"):
        st.caption(f"✅ {history['action']} ({history.get('date', '')})")

    if res.get("problem"):
        if res["status"] == "stopped":
            st.error(f" {res['problem']}")
        elif res["status"] == "critical":
            st.error(f" {res['problem']}")
        elif res["status"] == "warning":
            st.warning(f" {res['problem']}")
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

def get_yandex_auth_url():
    return (
        f"https://oauth.yandex.ru/authorize?"
        f"response_type=code&"
        f"client_id={YANDEX_CLIENT_ID}&"
        f"redirect_uri={YANDEX_REDIRECT_URI}"
    )

# =========================
# СТИЛИ ДЛЯ КНОПКИ
# =========================
st.markdown("""
<style>
    .scan-button button {
        background-color: #4A90E2 !important;
        color: white !important;
        border: none !important;
        border-radius: 8px !important;
        font-size: 16px !important;
        font-weight: normal !important;
        width: 200px !important;
        padding: 10px 20px !important;
    }
    .scan-button button:hover {
        background-color: #357ABD !important;
    }
    .stSpinner > div {
        border-color: #4A90E2 !important;
    }
</style>
""", unsafe_allow_html=True)

# =========================
# ЛОГИКА ЭКРАНА
# =========================
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None

# 1. Если токена нет — показываем вход
if "yandex_token" not in st.session_state:
    st.markdown("### 👋 Добро пожаловать в Namectus")
    st.markdown("Для начала работы подключите ваш рекламный кабинет.")
    
    auth_url = get_yandex_auth_url()
    st.markdown(f'[🔐 Войти через Яндекс]({auth_url})')
    st.caption("После входа Namectus сможет получать данные из вашего кабинета")
    st.stop()

# 2. Если токен есть, но сканирование еще не запускали
if st.session_state.scan_results is None:
    st.markdown("☑ Вы подключены к Яндекс.Директ")
    st.markdown("---")
    st.markdown("Нажмите кнопку ниже, чтобы проверить состояние ваших рекламных кампаний.")
    
    st.markdown('<div class="scan-button">', unsafe_allow_html=True)
    if st.button("🔍 Сканировать"):
        with st.spinner("🔄 Анализируем данные... Это может занять до 30 секунд"):
            try:
                SHEET_ID = "10cf-dT0Sd5K2c-39x_7zOxbyUdB8Lsr264VdTMhNP7E"
                url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
                
                st.info(" Загружаем данные из таблицы...")
                df = pd.read_csv(url)
                
                st.info("🧠 Анализируем кампании...")
                results = analyze_campaigns(df)
                results = filter_hidden(results, st.session_state.history, st.session_state.pending_top_ups)
                
                if len(results) == 0:
                    st.warning("⚠️ Данные получены, но кампании не найдены. Проверьте таблицу.")
                    st.stop()
                
                st.session_state.scan_results = results
                st.session_state.show_problems = False
                st.session_state.group_by = None
                
                st.success(f"✅ Проанализировано кампаний: {len(results)}")
                st.balloons()
                st.rerun()
                
            except Exception as e:
                import traceback
                error_detail = traceback.format_exc()
                print(f"!!! ПОЛНАЯ ОШИБКА: {error_detail}")
                
                st.error(f"❌ Ошибка при загрузке данных:")
                st.code(str(e))
                
                st.warning("💡 Хотите протестировать интерфейс?")
                if st.button("🧪 Загрузить тестовые данные"):
                    try:
                        test_data = {
                            'project': ['Bio-wc-service', 'Bio-wc-service', 'solodent'],
                            'campaign': ['Баннер на поиске Мойка кабин', 'РСЯ Товары', 'Поиск Бренд'],
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
                        
                        results = analyze_campaigns(df_test)
                        results = filter_hidden(results, st.session_state.history, st.session_state.pending_top_ups)
                        
                        st.session_state.scan_results = results
                        st.session_state.show_problems = False
                        st.session_state.group_by = None
                        
                        st.success("✅ Тестовые данные загружены!")
                        st.rerun()
                    except Exception as test_e:
                        st.error(f"Ошибка с тестовыми данными: {test_e}")
                st.stop()
    st.markdown('</div>', unsafe_allow_html=True)
    st.stop()

# =========================
# ЭКРАН ПОСЛЕ СКАНИРОВАНИЯ
# =========================
if st.session_state.scan_results is not None:
    results = st.session_state.scan_results
    
    stopped = [r for r in results if r["status"] == "stopped"]
    critical = [r for r in results if r["status"] == "critical"]
    warning = [r for r in results if r["status"] == "warning"]
    info = [r for r in results if r["status"] == "info"]
    ok = [r for r in results if r["status"] == "ok"]
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
                st.session_state.group_by = None
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
                if critical:
                    st.markdown("#### 🔴 Критично")
                    render_grouped_by_projects(critical, "critical")
                if warning or info:
                    st.markdown("#### 🟡 Требует внимания")
                    render_grouped_by_projects(warning + info, "warning")
                if stopped:
                    st.markdown("#### ⚫ Остановлены")
                    render_grouped_by_projects(stopped, "stopped")
                    
            elif st.session_state.get("group_by") == "priority":
                st.markdown("### ⚠ Список по важности")
                if critical:
                    st.markdown("#### 🔴 Критично")
                    render_grouped_by_projects(critical, "critical")
                if warning or info:
                    st.markdown("#### 🟡 Требует внимания")
                    render_grouped_by_projects(warning + info, "warning")
                if stopped:
                    st.markdown("#### ⚫ Остановлены")
                    render_grouped_by_projects(stopped, "stopped")
            
            st.markdown("---")
            if st.button("✅ Все проблемы решены. Скрыть и начать заново", use_container_width=True):
                st.session_state.scan_results = None
                st.session_state.show_problems = False
                st.session_state.group_by = None
                st.rerun()

# =========================
# ТЕХНИЧЕСКАЯ КНОПКА
# =========================
st.markdown("---")
if "yandex_token" in st.session_state:
    if st.button("🔧 Сбросить подключение к Яндексу", key="reset_token"):
        del st.session_state["yandex_token"]
        if os.path.exists(TOKENS_FILE):
            os.remove(TOKENS_FILE)
        st.session_state.scan_results = None
        st.rerun()