import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv
import streamlit.components.v1 as components
import math

# =========================
# ПАМЯТЬ: SUPABASE
# =========================
from supabase import create_client

def _secret(key, default=""):
    """Читает секрет из Streamlit-секретов или переменных среды. Не падает."""
    try:
        v = st.secrets.get(key)
        if v is not None:
            return v
    except Exception:
        pass
    return os.getenv(key, default)

SUPABASE_URL = _secret("SUPABASE_URL", "")
SUPABASE_KEY = _secret("SUPABASE_KEY", "")
sb = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

def _safe_parse(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None

def db_load_all(email):
    """Загружает всё хозяйство пользователя из базы."""
    if not sb: return
    try:
        u = sb.table("users").select("*").eq("email", email).execute()
        if u.data:
            r = u.data[0]
            st.session_state.user_tariff = r.get("tariff") or "trial"
            st.session_state.sub_end = _safe_parse(r.get("sub_end"))
            st.session_state.trial_end = _safe_parse(r.get("trial_end"))
            st.session_state.extra_accounts = r.get("extra_accounts") or 0
            st.session_state.user_currency = r.get("currency") or "€"
        p = sb.table("projects").select("*").eq("email", email).execute()
        st.session_state.projects = [{"name": x["name"], "created": datetime.now()} for x in p.data]
        a = sb.table("accounts").select("*").eq("email", email).execute()
        st.session_state.connected_accounts = [{"platform": x["platform"], "name": x["name"], "project": x.get("project", ""), "login": x.get("login", ""), "date": datetime.now()} for x in a.data]
        i = sb.table("invoices").select("*").eq("email", email).execute()
        st.session_state.invoices = [{"num": x["num"], "date": x["date"], "sum": x["sum"], "status": x.get("status", "pending"), "action": x.get("action"), "action_data": x.get("action_data") or {}, "html": x["html"]} for x in i.data]
    except Exception as e:
        print(f"Ошибка загрузки из базы: {e}")

def db_sync_all():
    """Сохраняет всё хозяйство пользователя в базу."""
    if not sb or not st.session_state.get("auth_passed") or not st.session_state.get("user_email"):
        return
    try:
        email = st.session_state.user_email
        sb.table("users").upsert({
            "email": email,
            "password": st.session_state.get("user_password", ""),
            "tariff": st.session_state.get("user_tariff") or "trial",
            "sub_end": st.session_state.get("sub_end").isoformat() if st.session_state.get("sub_end") else None,
            "trial_end": st.session_state.get("trial_end").isoformat() if st.session_state.get("trial_end") else None,
            "extra_accounts": st.session_state.get("extra_accounts") or 0,
            "currency": st.session_state.get("user_currency") or "€",
        }).execute()
        sb.table("projects").delete().eq("email", email).execute()
        if st.session_state.projects:
            sb.table("projects").insert([{"email": email, "name": x["name"]} for x in st.session_state.projects]).execute()
        sb.table("accounts").delete().eq("email", email).execute()
        if st.session_state.connected_accounts:
            sb.table("accounts").insert([{"email": email, "platform": x["platform"], "name": x["name"], "project": x.get("project", ""), "login": x.get("login", "")} for x in st.session_state.connected_accounts]).execute()
        sb.table("invoices").delete().eq("email", email).execute()
        if st.session_state.invoices:
            sb.table("invoices").insert([{"email": email, "num": x["num"], "date": x["date"], "sum": x["sum"], "status": x.get("status", "pending"), "action": x.get("action"), "action_data": x.get("action_data", {}), "html": x["html"]} for x in st.session_state.invoices]).execute()
    except Exception as e:
        print(f"Ошибка сохранения в базу: {e}")

def db_log(email, action, details=""):
    """Пишет событие в журнал действий."""
    if not sb: return
    try:
        sb.table("logs").insert({"email": email, "action": action, "details": details}).execute()
    except Exception:
        pass

# =========================
# БЕЗОПАСНАЯ ЗАГРУЗКА КЛЮЧЕЙ
# =========================
load_dotenv()
YANDEX_CLIENT_ID = _secret("YANDEX_CLIENT_ID")
YANDEX_CLIENT_SECRET = _secret("YANDEX_CLIENT_SECRET")
YANDEX_REDIRECT_URI = _secret("YANDEX_REDIRECT_URI", "https://namectus-app-bcjbphr6biswigvrnz7a2g.streamlit.app/")

# =========================
# ФАЙЛЫ ХРАНЕНИЯ
# =========================
HISTORY_FILE = "action_history.json"
PROJECTS_FILE = "projects.json"
TOKENS_FILE = "tokens.json"

# =========================
# СТРУКТУРА ТАРИФОВ (строго по документу)
# =========================
TARIFFS = {
    "business": {"name": "Бизнес-клиент", "limit": 1, "price": 2000, "extra_price": 1000, "max_extra": None},
    "agency_start": {"name": "Agency Start", "limit": 5, "price": 5000, "extra_price": 500, "max_extra": 18},
    "agency": {"name": "Agency", "limit": 20, "price": 15000, "extra_price": 500, "max_extra": 45},
    "agency_pro": {"name": "Agency Pro", "limit": 50, "price": 30000, "extra_price": 500, "max_extra": 90},
    "enterprise": {"name": "Enterprise", "limit": 100, "price": 50000, "extra_price": 500, "max_extra": None}
}

# =========================
# ИНИЦИАЛИЗАЦИЯ SESSION_STATE
# =========================
if "user_currency" not in st.session_state: st.session_state.user_currency = "RUB"
if "user_language" not in st.session_state: st.session_state.user_language = "ru"
if "user_email" not in st.session_state: st.session_state.user_email = None
if "user_tariff" not in st.session_state: st.session_state.user_tariff = None
if "trial_end" not in st.session_state: st.session_state.trial_end = None
if "sub_end" not in st.session_state: st.session_state.sub_end = None
if "connected_accounts" not in st.session_state: st.session_state.connected_accounts = []
if "extra_accounts" not in st.session_state: st.session_state.extra_accounts = 0
if "auth_passed" not in st.session_state: st.session_state.auth_passed = False

# Вспомогательные функции для тарифов
def get_total_limit():
    if st.session_state.user_tariff == "trial": return 1
    if not st.session_state.user_tariff: return 0
    return TARIFFS[st.session_state.user_tariff]["limit"] + st.session_state.extra_accounts

def get_days_left():
    """Сколько дней осталось по тарифу. Безопасна при любом формате даты."""
    from datetime import timezone
    tariff = st.session_state.get("user_tariff", "trial")
    end_date = st.session_state.get("trial_end") if tariff == "trial" else st.session_state.get("sub_end")
    if not end_date:
        return 0
    try:
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        return max(0, (end_date - datetime.now(timezone.utc)).days)
    except Exception:
        return 0
    
    # Приводим к aware datetime (UTC) для корректного сравнения
    from datetime import timezone
    now = datetime.now(timezone.utc)
    
    if hasattr(end_date, 'tzinfo') and end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    elif not hasattr(end_date, 'tzinfo'):
        # Если это строка — парсим
        try:
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except Exception:
            return 0
    
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    
    delta = end_date - now
    return max(0, delta.days)

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
# ФУНКЦИИ ДЛЯ ПОДКЛЮЧЕНИЯ ЯНДЕКС ДИРЕКТ
# =========================
def exchange_code_for_token(code):
    try:
        response = requests.post("https://oauth.yandex.ru/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": YANDEX_CLIENT_ID,
            "client_secret": YANDEX_CLIENT_SECRET
        })
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception as e:
        st.error(f"Ошибка: {e}")
    return None

def get_yandex_auth_url():
    from urllib.parse import quote
    state = quote(st.session_state.get("user_email") or "")
    return (f"https://oauth.yandex.ru/authorize?response_type=code"
            f"&client_id={YANDEX_CLIENT_ID}"
            f"&redirect_uri={YANDEX_REDIRECT_URI}"
            f"&state={state}")

def get_yandex_accounts():
    """Список доступных рекламных кабинетов Яндекса (для агентства — все клиенты)."""
    token = st.session_state.get("yandex_token")
    if not token:
        st.session_state.ya_error = "Токена доступа нет."
        return []
    try:
        r = requests.post(
            "https://api.direct.yandex.ru/json/v5/clients",
            headers={"Authorization": f"Bearer {token}", "Accept-Language": "ru"},
            json={"method": "get", "params": {"FieldNames": ["Login", "ManagedLogins", "ClientInfo"]}}
        )
        data = r.json()
        if "error" in data:
            st.session_state.ya_error = f"Яндекс говорит: {data.get('error')} / {data.get('error_description', '')}"
            return []
        result = data.get("result", {})
        clients = result.get("clients", []) if isinstance(result, dict) else result
        if not clients:
            st.session_state.ya_error = f"Яндекс вернул пустой список. Сырой ответ: {str(data)[:500]}"
            return []
        st.session_state.ya_error = ""
        accounts = []
        for c in clients:
            info = c.get("ClientInfo") or {}
            own_name = info.get("Name") or c.get("Login", "")
            sub = c.get("ManagedLogins") or []
            if sub:
                for s in sub:
                    login = s.get("Login") if isinstance(s, dict) else s
                    accounts.append({"login": login, "name": login})
            else:
                accounts.append({"login": c.get("Login", ""), "name": own_name})
        return accounts
    except Exception as e:
        st.session_state.ya_error = f"Запрос не удался: {e}"
        return []

# =========================
# АНАЛИЗ КАМПАНИЙ
# =========================
def analyze_campaigns(df: pd.DataFrame):
    from namectus_engine import NamectusEngine
    engine = NamectusEngine()
    results = []
    
    for (project, campaign), camp_df in df.groupby(["project", "campaign"]):
        camp_df = camp_df.sort_values("date").reset_index(drop=True)
        total_days = len(camp_df)
        source = camp_df["source"].iloc[0]
        campaign_id = str(camp_df["campaign_id"].iloc[0])
        
        if total_days < 7:
            results.append({"label": f"{project} / {campaign}", "status": "data_accumulation", "problem": f"Доступно только {total_days} дней", "actions": ["Наблюдать"], "source": source, "campaign_id": campaign_id, "project": project, "campaign": campaign})
            continue
        
        total_spent = camp_df["cost"].sum()
        total_conv = int(camp_df["conversions"].sum())
        total_clicks = int(camp_df["clicks"].sum())
        total_impressions = int(camp_df["impressions"].sum())
        
        campaign_info = {
            'days': total_days, 'spend': total_spent, 'currency': '₽',
            'conversions': total_conv, 'clicks': total_clicks, 'status': 'active',
            'budget_remaining': 0, 'daily_spend': total_spent / max(total_days, 1),
            'previous_cpa': 0, 'current_cpa': total_spent / max(total_conv, 1),
            'previous_ctr': 0.01, 'current_ctr': total_clicks / max(total_impressions, 1),
            'broken_links_count': 0
        }
        
        alerts = engine.check_campaign(campaign_info)
        base = {"label": f"{project} / {campaign}", "source": source, "campaign_id": campaign_id, "project": project, "campaign": campaign}
        
        if not alerts:
            results.append({**base, "status": "ok", "problem": "", "actions": []})
        else:
            main_alert = alerts[0]
            if main_alert['severity'] == 'critical':
                status, actions = "critical", ["Исправить", "Наблюдать", "Игнорировать"]
            else:
                status, actions = "warning", ["Исправить", "Наблюдать", "Игнорировать"]
            results.append({**base, "status": status, "problem": main_alert['description'], "actions": actions})
    return results

# =========================
# ФИЛЬТР СКРЫТЫХ (ТОЛЬКО ОДНА ФУНКЦИЯ, БЕЗ ДУБЛЕЙ)
# =========================
def filter_hidden(results, history):
    now = datetime.now()
    filtered = []
    for res in results:
        label = res["label"]
        if label in history:
            h = history[label]
            if h.get("action") == "Закрыть" and h.get("session_closed"): continue
            if "hide_until" in h:
                try:
                    if now < datetime.strptime(h["hide_until"], "%d.%m.%Y %H:%M"): continue
                except: pass
        filtered.append(res)
    return filtered

# =========================
# НАСТРОЙКА СТРАНИЦЫ
# =========================
st.set_page_config(page_title="Namectus", page_icon="", layout="wide")

# =========================
# СЛОВАРЬ ПЕРЕВОДОВ
# =========================
LANG = {
    "ru": {
        "login": "Вход",
        "register": "Регистрация",
        "email_phone": "Почта или телефон",
        "password": "Пароль",
        "login_btn": "Войти",
        "get_code": "Получить код",
        "code_from_message": "Код из сообщения",
        "create_password": "Придумай пароль",
        "register_btn": "Зарегистрироваться",
        "fill_all_fields": "Заполните все поля",
        "check_code": "Проверь код (введи 1234) и заполни все поля",
        "code_sent": "Код отправлен на {email} (Тестовый код: 1234)",
        "choose_language": "Выберите язык",
        "welcome": "Добро пожаловать в Namectus",
        "start_free": "Начать бесплатно",
        "choose_tariff": "Подключить тариф",
        "trial_period": "У вас пробный период",
        "days_left": "Осталось: {days} дней",
        "your_tariff": "Ваш тариф: {tariff}",
        "connect_ad_account": "Подключите рекламный кабинет",
        "yandex": "Яндекс",
        "google": "Google",
        "meta": "Meta",
        "scan": "Сканировать",
        "connected": "Подключено",
        "not_connected": "Не подключено",
    },
    "kz": {
        "login": "Кіру",
        "register": "Тіркелу",
        "email_phone": "Пошта немесе телефон",
        "password": "Құпия сөз",
        "login_btn": "Кіру",
        "get_code": "Код алу",
        "code_from_message": "Хабарламадағы код",
        "create_password": "Құпия сөз ойлап тап",
        "register_btn": "Тіркелу",
        "fill_all_fields": "Барлық өрістерді толтырыңыз",
        "check_code": "Кодты тексеріңіз (1234 енгізіңіз) және барлық өрістерді толтырыңыз",
        "code_sent": "Код {email} мекенжайына жіберілді (Сынақ коды: 1234)",
        "choose_language": "Тілді таңдаңыз",
        "welcome": "Namectus-қа қош келдіңіз",
        "start_free": "Тегін бастау",
        "choose_tariff": "Тарифті қосу",
        "trial_period": "Сізде сынақ мерзімі бар",
        "days_left": "Қалды: {days} күн",
        "your_tariff": "Сіздің тарифіңіз: {tariff}",
        "connect_ad_account": "Жарнама кабинетін қосыңыз",
        "yandex": "Яндекс",
        "google": "Google",
        "meta": "Meta",
        "scan": "Сканерлеу",
        "connected": "Қосылды",
        "not_connected": "Қосылмады",
    },
    "en": {
        "login": "Login",
        "register": "Register",
        "email_phone": "Email or phone",
        "password": "Password",
        "login_btn": "Log in",
        "get_code": "Get code",
        "code_from_message": "Code from message",
        "create_password": "Create password",
        "register_btn": "Register",
        "fill_all_fields": "Fill all fields",
        "check_code": "Check code (enter 1234) and fill all fields",
        "code_sent": "Code sent to {email} (Test code: 1234)",
        "choose_language": "Choose language",
        "welcome": "Welcome to Namectus",
        "start_free": "Start for free",
        "choose_tariff": "Choose tariff",
        "trial_period": "You have a trial period",
        "days_left": "Days left: {days}",
        "your_tariff": "Your tariff: {tariff}",
        "connect_ad_account": "Connect ad account",
        "yandex": "Yandex",
        "google": "Google",
        "meta": "Meta",
        "scan": "Scan",
        "connected": "Connected",
        "not_connected": "Not connected",
    }
}

def t(key):
    """Получить перевод для текущего языка"""
    lang = st.session_state.get("user_language", "ru")
    return LANG.get(lang, LANG["ru"]).get(key, key)

# =========================
# НОВЫЙ ВХОДНОЙ ТАМБУР (SaaS-архитектура)
# =========================

# 1. Структура тарифов (из твоего документа)
TARIFFS = {
    "business": {"name": "Бизнес-клиент", "limit": 1, "price": 2000, "extra_price": 1000, "max_extra": None},
    "agency_start": {"name": "Agency Start", "limit": 5, "price": 5000, "extra_price": 500, "max_extra": 18},
    "agency": {"name": "Agency", "limit": 20, "price": 15000, "extra_price": 500, "max_extra": 45},
    "agency_pro": {"name": "Agency Pro", "limit": 50, "price": 30000, "extra_price": 500, "max_extra": 90},
    "enterprise": {"name": "Enterprise", "limit": 100, "price": 50000, "extra_price": 500, "max_extra": None}
}

# БАЗОВЫЕ ЦЕНЫ В ЕВРО (продуктовая константа, доступна всем экранам)
PRICES_EUR = {
    "trial":        {"price": 0,   "extra": 0,  "unit": "источник"},
    "business":     {"price": 20,  "extra": 10, "unit": "источник"},
    "agency_start": {"price": 50,  "extra": 5,  "unit": "проект"},
    "agency":       {"price": 150, "extra": 5,  "unit": "проект"},
    "agency_pro":   {"price": 300, "extra": 5,  "unit": "проект"},
    "enterprise":   {"price": 500, "extra": 5,  "unit": "проект"},
}
RATES = {"€": 1, "$": 1.1, "₽": 100, "₸": 550}

def make_invoice(tariff_key, amount_eur=None, note="", action=None, action_data=None):
    """Создаёт счёт и кладёт в архив. action: renew/switch/extra — что куплено."""
    p = PRICES_EUR.get(tariff_key, {"price": 0, "extra": 0, "unit": "проект"})
    amount = amount_eur if amount_eur is not None else p["price"]
    num = f"INV-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    cur = st.session_state.get("user_currency", "€")
    rate = RATES.get(cur, 1)
    amount_cur = int(round(amount * rate, -1)) if cur in ("₽", "₸") else round(amount * rate)
    t_name = TARIFFS[tariff_key]["name"] if tariff_key in TARIFFS else tariff_key
    html = f"""<html><head><meta charset="utf-8"><title>Счёт {num}</title>
<style>body{{font-family:Arial;padding:40px;color:#222}}h1{{font-size:20px}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #999;padding:8px;text-align:left}}</style>
</head><body>
<h1>NAMECTUS — счёт на оплату</h1>
<p>№ {num} от {datetime.now().strftime('%d.%m.%Y')}</p>
<p>Клиент: {st.session_state.user_email}</p>
<table><tr><th>Позиция</th><th>Цена</th></tr>
<tr><td>{note or ('Тариф «' + t_name + '», подписка 30 дней')}</td><td>{amount} € ({amount_cur} {cur})</td></tr>
</table>
<p><b>Итого: {amount} € ({amount_cur} {cur})</b></p>
<p>Продавец: NAMECTUS. Реквизиты для оплаты будут указаны после регистрации юрлица (ТОО Казахстан / самозанятость РФ).</p>
<p>Оплата счёта означает согласие с условиями оферты (счёт-договор).</p>
</body></html>"""
    inv = {"num": num, "date": datetime.now().strftime("%d.%m.%Y"), "sum": f"{amount} €",
           "html": html, "status": "pending", "action": action, "action_data": action_data or {}}
    st.session_state.invoices.append(inv)
    db_log(st.session_state.user_email, "Счёт сформирован", f"{num} на {amount} €")
    return inv

def apply_invoice(inv):
    """Применяет покупку из счёта ТОЛЬКО после оплаты."""
    a = inv.get("action")
    d = inv.get("action_data", {})
    if a == "renew":
        st.session_state.sub_end = datetime.now() + timedelta(days=30)
    elif a == "switch":
        st.session_state.user_tariff = d.get("tariff", st.session_state.user_tariff)
        st.session_state.sub_end = datetime.now() + timedelta(days=30)
        st.session_state.extra_accounts = 0
    elif a == "extra":
        st.session_state.extra_accounts += 1
    inv["status"] = "paid"

# 2. Инициализация переменных (Скелет мультивалютности и сессии)
if "user_currency" not in st.session_state: st.session_state.user_currency = "RUB"
if "user_language" not in st.session_state: st.session_state.user_language = "ru"
if "user_email" not in st.session_state: st.session_state.user_email = None
if "user_tariff" not in st.session_state: st.session_state.user_tariff = None
if "trial_end" not in st.session_state: st.session_state.trial_end = None
if "sub_end" not in st.session_state: st.session_state.sub_end = None
if "connected_accounts" not in st.session_state: st.session_state.connected_accounts = []
if "extra_accounts" not in st.session_state: st.session_state.extra_accounts = 0
if "auth_passed" not in st.session_state: st.session_state.auth_passed = False
if "invoices" not in st.session_state: st.session_state.invoices = []
if "scan_archive" not in st.session_state: st.session_state.scan_archive = []
if "projects" not in st.session_state: st.session_state.projects = []

# Вспомогательные функции
def get_total_limit():
    if st.session_state.user_tariff == "trial": return 1
    if not st.session_state.user_tariff: return 0
    return TARIFFS[st.session_state.user_tariff]["limit"] + st.session_state.extra_accounts

# =========================
# ОБРАБОТКА ВОЗВРАТА С ЯНДЕКСА (до экрана входа!)
# =========================
query_params = st.query_params
if "code" in query_params and "yandex_token" not in st.session_state:
    token = exchange_code_for_token(query_params["code"])
    if token:
        st.session_state["yandex_token"] = token
        st.session_state.oauth_ok = True
        returned_email = query_params.get("state", "")
        if returned_email:
            st.session_state.user_email = returned_email
            st.session_state.auth_passed = True
        st.query_params.clear()
        st.rerun()

# =========================
# ОБРАБОТКА ВОЗВРАТА С ЯНДЕКСА (до экрана входа!)
# =========================
query_params = st.query_params
if "code" in query_params and "yandex_token" not in st.session_state:
    token = exchange_code_for_token(query_params["code"])
    if token:
        st.session_state["yandex_token"] = token
        st.session_state.oauth_ok = True
        returned_email = query_params.get("state", "")
        if returned_email:
            st.session_state.user_email = returned_email
            st.session_state.auth_passed = True
        st.query_params.clear()
        st.rerun()

# Авто-загрузка хозяйства вернувшегося пользователя из базы
if sb and st.session_state.get("user_email") and not st.session_state.get("db_loaded"):
    db_load_all(st.session_state.user_email)
    st.session_state.db_loaded = True

# =========================
# ЭКРАН 1: ВХОД И РЕГИСТРАЦИЯ (КОМПАКТНАЯ ШАПКА + НОВАЯ РЕГИСТРАЦИЯ + ПРОВЕРКА ПАРОЛЯ)
# =========================
if not st.session_state.auth_passed:

    # Агрессивно убираем отступы сверху
    st.markdown(
        """
        <style>
        .block-container { 
            padding-top: 0rem !important; 
            padding-bottom: 0rem !important;
            margin-top: -3rem; 
        }
        header[data-testid="stHeader"] { display: none; }
        .password-hint { font-size: 12px; margin-top: 5px; }
        .check { color: #28a745; }
        .cross { color: #dc3545; }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Шапка в одну строку: Логотип, Название, Язык
    col_logo, col_title, col_lang = st.columns([0.5, 3, 2])

    with col_logo:
        st.image("logo.png", width=60)

    with col_title:
        st.markdown("<h3 style='margin-top: 12px;'>NAMECTUS v1.0</h3>", unsafe_allow_html=True)

    with col_lang:
        current_idx = 0 if st.session_state.user_language == "ru" else (1 if st.session_state.user_language == "kz" else 2)
        lang = st.selectbox(
            "Язык",
            ["🇷🇺 Русский", "🇰🇿 Қазақша", "🇬🇧 English"],
            index=current_idx,
            label_visibility="collapsed"
        )
        
        if "Русский" in lang:
            st.session_state.user_language = "ru"
        elif "Қазақша" in lang:
            st.session_state.user_language = "kz"
        else:
            st.session_state.user_language = "en"

    # Тонкая линия разделитель
    st.markdown("<div style='height: 5px;'></div>", unsafe_allow_html=True)
    st.divider()

    # ЦЕНТРИРОВАНИЕ ФОРМЫ
    col_empty1, col_form, col_empty2 = st.columns([1, 2, 1])

    with col_form:
        tab_login, tab_reg = st.tabs([t("login"), t("register")])

        with tab_login:
            email = st.text_input(t("email_phone"), key="login_email_tz1")
            password = st.text_input(t("password"), type="password", key="login_pass_tz1")

            if st.button(t("login_btn"), type="primary", use_container_width=True):
                if email and password:
                    st.session_state.user_email = email
                    st.session_state.auth_passed = True
                    st.rerun()
                else:
                    st.warning(t("fill_all_fields"))

        with tab_reg:
            # Поля ввода
            reg_email = st.text_input(t("email_phone"), key="reg_email_new")
            reg_pass = st.text_input(t("password"), type="password", key="reg_pass_new")
            reg_pass_confirm = st.text_input("Подтвердите пароль", type="password", key="reg_pass_confirm_new")
            
            # 1. Динамическая проверка пароля
            has_latin = any('a' <= c <= 'z' or 'A' <= c <= 'Z' for c in reg_pass)
            has_cyrillic = any('а' <= c.lower() <= 'я' or c.lower() == 'ё' for c in reg_pass)
            
            checks = {
                "length": len(reg_pass) >= 8,
                "upper": any('A' <= c <= 'Z' for c in reg_pass),
                "lower": any('a' <= c <= 'z' for c in reg_pass),
                "digit": any(c.isdigit() for c in reg_pass),
                "special": any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in reg_pass)
            }
            
            # Пароль надежный, если выполнены правила И нет кириллицы
            is_strong = checks["length"] and checks["upper"] and checks["digit"] and has_latin and not has_cyrillic
            
            # Рисуем подсказки
            hint_html = "<div class='password-hint'>"
            hint_html += "<span class='check'>✓</span> Минимум 8 символов<br>" if checks["length"] else "<span class='cross'>✗</span> Минимум 8 символов<br>"
            hint_html += "<span class='check'>✓</span> Латинская заглавная (A-Z)<br>" if checks["upper"] else "<span class='cross'>✗</span> Латинская заглавная (A-Z)<br>"
            hint_html += "<span class='check'>✓</span> Латинская строчная (a-z)<br>" if checks["lower"] else "<span class='cross'>✗</span> Латинская строчная (a-z)<br>"
            hint_html += "<span class='check'>✓</span> Цифра<br>" if checks["digit"] else "<span class='cross'>✗</span> Цифра<br>"
            hint_html += "<span class='check'>✓</span> Спецсимвол (!@#$%^&*)<br>" if checks["special"] else "<span class='cross'>✗</span> Спецсимвол (!@#$%^&*)<br>"
            hint_html += "</div>"
            
            st.markdown(hint_html, unsafe_allow_html=True)
            
            # Явная ругань на русские буквы
            if has_cyrillic:
                st.warning("⚠️ В пароле русские буквы! Переключи раскладку на английскую — пароль пишется только латиницей.")

            # 2. Кнопка "Получить код"
            if st.button(t("get_code"), use_container_width=True, key="btn_get_code_new"):
                if not reg_email or not reg_pass or not reg_pass_confirm:
                    st.warning(t("fill_all_fields"))
                elif reg_pass != reg_pass_confirm:
                    st.error("Пароли не совпадают! Проверьте поле 'Подтвердите пароль'.")
                elif not is_strong:
                    st.error("Пароль слишком слабый! Выполните все требования выше.")
                else:
                    st.success(t("code_sent").format(email=reg_email))

            # 3. Поле для кода
            reg_code = st.text_input(t("code_from_message"), key="reg_code_new")
            
            # 4. Кнопка "Зарегистрироваться"
            if st.button(t("register_btn"), type="primary", use_container_width=True, key="btn_reg_new"):
                if not reg_code or not reg_email or not reg_pass or not reg_pass_confirm:
                    st.warning(t("fill_all_fields"))
                elif reg_code != "1234":
                    st.error("Неверный код! Попробуйте 1234.")
                elif reg_pass != reg_pass_confirm:
                    st.error("Пароли не совпадают!")
                elif not is_strong:
                    st.error("Пароль слишком слабый!")
                else:
                    st.session_state.user_email = reg_email
                    st.session_state.auth_passed = True
                    st.rerun()

    st.stop()

# =========================
# ЭКРАН 2: ОНБОРДИНГ (ВЫБОР ТАРИФА)
# =========================
if st.session_state.user_tariff is None:
    import streamlit.components.v1 as components

    # БАЗОВАЯ ВАЛЮТА ПРОДУКТА — ЕВРО
    PRICES_EUR = {
        "business":     {"price": 20,  "extra": 10, "unit": "источник трафика"},
        "agency_start": {"price": 50,  "extra": 5,  "unit": "проект"},
        "agency":       {"price": 150, "extra": 5,  "unit": "проект"},
        "agency_pro":   {"price": 300, "extra": 5,  "unit": "проект"},
        "enterprise":   {"price": 500, "extra": 5,  "unit": "проект"},
    }
    RATES = {"€": 1, "$": 1.1, "₽": 100, "₸": 550}
    SYMBOLS = ["€", "$", "₽", "₸"]

    # Шапка
    h1, h2, h3 = st.columns([0.5, 4, 2])
    with h1:
        st.image("logo.png", width=50)
    with h2:
        st.markdown("<h3 style='margin-top: 8px;'>NAMECTUS v1.0</h3>", unsafe_allow_html=True)
    with h3:
        components.html("""
        <div id='nc_clock' style='color:#9aa0a6; font-size:13px; text-align:right; padding-top:12px;'></div>
        <script>
        function nc_tick(){
            var n = new Date();
            document.getElementById('nc_clock').innerText =
                n.toLocaleDateString('ru-RU') + ' ' + n.toLocaleTimeString('ru-RU');
        }
        nc_tick();
        setInterval(nc_tick, 1000);
        </script>
        """, height=45)
    st.divider()

    # CSS для зелёной кнопки
    st.markdown("""
    <style>
    div[data-testid="stButton"] button[kind="primary"] {
        background-color: #2e7d32 !important;
        color: white !important;
    }
    div[data-testid="stButton"] button[kind="primary"]:hover {
        background-color: #1b5e20 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"### 👋 Добро пожаловать, {st.session_state.user_email}!")
    st.markdown("NAMECTUS следит за вашей рекламой и находит проблемы до того, как они сольют бюджет.")

    # ТРИ КОЛОНКИ: триал | пустая | платные
    col_trial, col_gap, col_paid = st.columns([2, 0.5, 1.2])

    with col_trial:
        st.markdown("###  Попробовать бесплатно")
        st.caption("10 дней • 1 кабинет")
        # Делим колонку пополам: кнопка займёт половину ширины col_trial
        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            if st.button("Начать бесплатный период", type="primary", use_container_width=True, key="btn_trial_green"):
                st.session_state.user_tariff = "trial"
                st.session_state.trial_end = datetime.now() + timedelta(days=10)
                st.rerun()

    with col_paid:
        st.markdown("### 💎 Платные тарифы")
        
        cur = st.selectbox("Валюта", SYMBOLS,
                           index=SYMBOLS.index(st.session_state.user_currency) if st.session_state.user_currency in SYMBOLS else 0,
                           key="cur_select_onboard")
        st.session_state.user_currency = cur

        def price(eur):
            v = eur * RATES[cur]
            v = int(round(v, -1)) if cur in ("₽", "₸") else int(round(v))
            return f"{v:,} {cur}".replace(",", " ")

        options_keys = ["business", "agency_start", "agency", "agency_pro", "enterprise"]
        options_text = [
            f"Бизнес-клиент — {price(20)}/мес — 1 источник",
            f"Agency Start — {price(50)}/мес — до 5 проектов",
            f"Agency — {price(150)}/мес — до 20 проектов",
            f"Agency Pro — {price(300)}/мес — до 50 проектов",
            f"Enterprise — {price(500)}/мес — от 100 проектов",
        ]
        chosen = st.selectbox("Тариф", options_text, key="tariff_select_onboard")
        chosen_key = options_keys[options_text.index(chosen)]

        if st.button("Подключить тариф", use_container_width=True, key="btn_pick_tariff"):
            st.session_state.terms_tariff = chosen_key

    # --- Всплывающее окно с условиями тарифа ---
    @st.dialog("📄 Условия тарифа")
    def show_terms_dialog():
        k = st.session_state.terms_tariff
        info = TARIFFS[k]
        p = PRICES_EUR[k]
        st.markdown(f"### «{info['name']}»")
        st.markdown(f"""
- Базовая цена: **{price(p['price'])}/мес** (фиксировано в евро: {p['price']} €)
- Включено: **{info['limit']}** {p['unit']}
- Дополнительная единица: **+{price(p['extra'])}/мес** за {p['unit']}{' (максимум ' + str(info['max_extra']) + ')' if info['max_extra'] else ' (без лимита)'}
- Оплата: картой или по счёту для юрлиц. Подписка — 30 дней.
""")
        agree = st.checkbox("Я ознакомился(ась) с условиями и согласен(на)", key="agree_terms_dlg")
        if agree:
            if st.button("💳 Получить счёт и активировать", type="primary", use_container_width=True, key="btn_activate_dlg"):
                make_invoice(k)
                st.session_state.user_tariff = k
                st.session_state.sub_end = datetime.now() + timedelta(days=30)
                st.session_state.terms_tariff = None
                st.session_state.invoice_ready = True
                st.rerun()

    # Показываем окошко, если выбран тариф
    if st.session_state.get("terms_tariff"):
        show_terms_dialog()

    # Сообщение после активации
    if st.session_state.get("invoice_ready"):
        st.success("✅ Тариф активирован! Счёт сохранён в архив (кнопка скачивания появится следующим шагом).")

    st.stop()

# =========================
# ЭКРАН 3: ШАПКА РАБОЧЕГО ПРОСТРАНСТВА
# =========================
import math
# Авто-загрузка хозяйства из базы (один раз за сессию)
if sb and st.session_state.get("user_email") and not st.session_state.get("db_loaded"):
    if not st.session_state.invoices and not st.session_state.projects:
        db_load_all(st.session_state.user_email)
    st.session_state.db_loaded = True

# БОКОВАЯ ПАНЕЛЬ
with st.sidebar:
    st.image("logo.png", width=60)

    # --- Тариф: продлить или сменить ---
    with st.expander("💎 Продлить или сменить тариф"):
        k = st.session_state.user_tariff
        t_name = "Пробный период" if k == "trial" else TARIFFS[k]["name"]
        st.caption(f"Текущий: {t_name}")
        p = PRICES_EUR.get(k, {"price": 0, "extra": 0, "unit": "проект"})
        if k != "trial":
            if st.button(f"🔄 Продлить (+{p['price']} €)", use_container_width=True, key="sb_renew"):
                make_invoice(k, note=f"Продление тарифа «{t_name}», подписка 30 дней", action="renew")
                st.session_state.invoice_ready = True
                st.rerun()
        keys = ["business", "agency_start", "agency", "agency_pro", "enterprise"]
        texts = []
        for x in keys:
            if x == "business":
                texts.append(f"{TARIFFS[x]['name']} — {PRICES_EUR[x]['price']} €/мес — 1 источник")
            elif x == "enterprise":
                texts.append(f"{TARIFFS[x]['name']} — {PRICES_EUR[x]['price']} €/мес — от 100 проектов")
            else:
                texts.append(f"{TARIFFS[x]['name']} — {PRICES_EUR[x]['price']} €/мес — до {TARIFFS[x]['limit']} проектов")
        choice = st.selectbox("Выбрать тариф", texts, key="sb_tariff_choice")
        if st.button("💳 Сформировать счёт", use_container_width=True, key="sb_switch"):
            new_tariff = keys[texts.index(choice)]
            make_invoice(new_tariff, note=f"Переход на тариф «{TARIFFS[new_tariff]['name']}», подписка 30 дней", action="switch", action_data={"tariff": new_tariff})
            st.session_state.invoice_ready = True
            st.rerun()

    # --- Подключённые проекты (справочно, добавление — только с главного экрана) ---
    with st.expander(f"📂 Подключённые проекты — {len(st.session_state.projects)}"):
        if st.session_state.projects:
            for p in sorted(st.session_state.projects, key=lambda x: x["name"]):
                sources = [a for a in st.session_state.connected_accounts if a.get("project") == p["name"]]
                with st.expander(f"{p['name']} • источников: {len(sources)}"):
                    if sources:
                        labels = {"yandex": "🔴 Яндекс.Директ", "google": "🔵 Google Ads", "meta": "🔷 Meta Ads"}
                        for a in sources:
                            st.caption(labels.get(a["platform"], a["platform"]))
                    else:
                        st.caption("Источники не подключены.")
        else:
            st.caption("Пока нет проектов.")

    with st.expander("🧾 Мои счета"):
        pending = [i for i in st.session_state.invoices if i.get("status", "pending") == "pending"]
        paid = [i for i in st.session_state.invoices if i.get("status") == "paid"]

        st.markdown("**Активные:**")
        if pending:
            for inv in reversed(pending):
                if st.button(f"⏳ {inv['num']} • {inv['date']} • {inv['sum']}", use_container_width=True, key=f"inv_row_{inv['num']}"):
                    st.session_state.view_invoice = inv["num"]
        else:
            st.caption("Нет активных счетов.")

        if paid:
            st.divider()
            st.markdown("**Оплаченные:**")
            for inv in reversed(paid):
                st.caption(f"✅ {inv['num']} • {inv['date']} • {inv['sum']}")

        if st.session_state.get("view_invoice"):
            inv = next((i for i in st.session_state.invoices if i["num"] == st.session_state.view_invoice), None)
            if inv:
                st.divider()
                st.caption(f"Клиент: {st.session_state.user_email}")
                st.caption(f"Итого: {inv['sum']}")
                st.caption("Статус: Сформирован")
                st.caption("Продавец: NAMECTUS (счёт-договор)")
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.download_button("⬇ Скачать", data=inv["html"], file_name=inv["num"] + ".html", mime="text/html", key="sb_dl_view")
                with col2:
                    if st.button("✓ Оплачен", key="mark_paid_view"):
                        apply_invoice(inv)
                        st.session_state.view_invoice = None
                        st.rerun()
                if st.button("Закрыть просмотр", key="sb_close_view"):
                    st.session_state.view_invoice = None
                    st.rerun()

    # --- Архив сканирований: год → месяц → дата ---
    with st.expander("📊 Архив сканирований"):
        archive = st.session_state.scan_archive
        if archive:
            years = sorted(set(r["date"].year for r in archive), reverse=True)
            for year in years:
                with st.expander(f"📅 {year}"):
                    months_in_year = sorted(set(r["date"].month for r in archive if r["date"].year == year), reverse=True)
                    for month in months_in_year:
                        month_name = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"][month-1]
                        with st.expander(f"{month_name} {year}"):
                            reports = [r for r in archive if r["date"].year == year and r["date"].month == month]
                            for r in sorted(reports, key=lambda x: x["date"], reverse=True):
                                if st.button(f"📄 {r['date'].strftime('%d.%m.%Y')}", use_container_width=True, key=f"scan_row_{r['date'].strftime('%Y%m%d')}"):
                                    st.session_state.view_scan = r["date"].strftime("%Y%m%d")
        else:
            st.caption("Здесь будут сохранённые отчёты.")
            st.info("Появится после подключения реальных данных.")

def get_days_left():
    """Сколько дней осталось по тарифу. Безопасна при любом формате даты."""
    from datetime import timezone
    tariff = st.session_state.get("user_tariff", "trial")
    end_date = st.session_state.get("trial_end") if tariff == "trial" else st.session_state.get("sub_end")
    if not end_date:
        return 0
    try:
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        return max(0, (end_date - datetime.now(timezone.utc)).days)
    except Exception:
        return 0

# Компактные отступы + зелёная кнопка сканирования
st.markdown("""
<style>
h3, h4 { margin-top: 0.3rem !important; margin-bottom: 0.3rem !important; }
hr { margin: 0.5rem 0 !important; }
div[data-testid="stButton"] button[kind="primary"] {
    background-color: #2e7d32 !important;
    color: white !important;
}
</style>
""", unsafe_allow_html=True)

# Шапка: логотип, название и локальное время
h1, h2, h3 = st.columns([0.5, 4, 2])
with h1:
    st.image("logo.png", width=50)
with h2:
    st.markdown("<h3 style='margin-top: 8px;'>NAMECTUS v1.0</h3>", unsafe_allow_html=True)
with h3:
    components.html("""
    <div id='nc_clock' style='color:#9aa0a6; font-size:13px; text-align:right; padding-top:12px;'></div>
    <script>
    function nc_tick(){
        var n = new Date();
        document.getElementById('nc_clock').innerText =
            n.toLocaleDateString('ru-RU') + ' ' + n.toLocaleTimeString('ru-RU');
    }
    nc_tick();
    setInterval(nc_tick, 1000);
    </script>
    """, height=45)
st.divider()

# Инфо-панель: email, тариф, дни
col_info1, col_info2, col_info3 = st.columns([3, 1, 2])
with col_info1:
    st.markdown(f"**{st.session_state.user_email}**")
with col_info2:
    tariff_name = "Пробный период" if st.session_state.user_tariff == "trial" else TARIFFS[st.session_state.user_tariff]["name"]
    st.markdown(f"💎 {tariff_name}")
with col_info3:
    days = get_days_left()
    st.markdown(f"⏳ Осталось: {days} дней")

# Инициализация навигации
if "nav_screen" not in st.session_state:
    st.session_state.nav_screen = "scan"
if "view_mode" not in st.session_state:
    st.session_state.view_mode = None
if "selected_project" not in st.session_state:
    st.session_state.selected_project = None
if "selected_category" not in st.session_state:
    st.session_state.selected_category = None
if "selected_campaign" not in st.session_state:
    st.session_state.selected_campaign = None
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "history" not in st.session_state:
    st.session_state.history = load_history()

st.divider()

if st.session_state.user_tariff in ["trial", "business"]:
    current_cabs = len(st.session_state.connected_accounts)
else:
    current_cabs = len(st.session_state.projects)
total_limit = get_total_limit()
if st.session_state.user_tariff in ["trial", "business"]:
    unit_name = "источник"
else:
    unit_name = "проект"

# 1. СНАЧАЛА: сканирование (компактная зелёная кнопка) или напоминалка
if current_cabs > 0:
    if st.button("🔍 Сканировать", type="primary", key="btn_scan_main"):
        with st.spinner("🔄 Анализируем данные..."):
            try:
                SHEET_ID = "10cf-dT0Sd5K2c-39x_7zOxbyUdB8Lsr264VdTMhNP7E"
                df = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv")
                results = analyze_campaigns(df)
                results = filter_hidden(results, st.session_state.history)
                if not results:
                    st.warning("Нет данных")
                else:
                    st.session_state.scan_results = results
                    db_log(st.session_state.user_email, "Сканирование", f"найдено результатов: {len(results)}")
                    st.session_state.nav_screen = "choose_mode"
                    st.rerun()
            except Exception as e:
                st.error(f"Ошибка: {e}")
else:
    col_msg, col_empty = st.columns([3, 1])
    with col_msg:
        st.info("Подключите хотя бы один рекламный кабинет, чтобы начать сканирование.")

st.divider()

# 2. ПОТОМ: подключение кабинетов (названия — обычным текстом)
st.markdown("#### Подключите рекламный кабинет")
col_y, col_g, col_m = st.columns(3)
paid_active = st.session_state.user_tariff == "trial" or any(i.get("status") == "paid" for i in st.session_state.invoices)

with col_y:
    st.markdown("**🔴 Яндекс.Директ**")
    if st.button("Подключить Яндекс", use_container_width=True, key="btn_yandex"):
        if not paid_active:
            st.error("💳 Оплатите счёт, после чего подключайте кабинеты и проекты.")
        elif current_cabs >= total_limit:
            st.session_state.show_limit_dialog = True
        elif not st.session_state.get("yandex_token"):
            st.session_state.ask_yandex_login = True
        else:
            st.session_state.show_yandex_dialog = True
    if st.session_state.get("ask_yandex_login"):
        st.markdown(f'<a href="{get_yandex_auth_url()}" style="color:#90caf9;font-weight:bold;">🔐 Войти в Яндекс.Директ и разрешить доступ (только чтение)</a>', unsafe_allow_html=True)
    if st.session_state.get("oauth_ok"):
        st.session_state.oauth_ok = False
        st.session_state.show_yandex_dialog = True
with col_g:
    st.markdown("**🔵 Google Ads**")
    st.button("Скоро", use_container_width=True, disabled=True, key="btn_soon_g")
with col_m:
    st.markdown("**🔷 Meta Ads**")
    st.button("Скоро", use_container_width=True, disabled=True, key="btn_soon_m")

# --- ОКНО ВЫБОРА ПРОЕКТА (универсальное для всех платформ) ---
@st.dialog("📁 Подключение источника")
def show_project_dialog():
    platform = st.session_state.show_project_dialog
    labels = {"yandex": "Яндекс.Директ", "google": "Google Ads", "meta": "Meta Ads"}
    label = labels.get(platform, platform)
    st.markdown(f"Подключаем **{label}**")
    st.caption("Назовите проект, к которому будет привязан этот источник.")

    if st.session_state.projects:
        st.markdown("**Существующие проекты:**")
        for p in st.session_state.projects:
            if st.button(f"📂 {p['name']}", use_container_width=True, key=f"proj_pick_{p['name']}"):
                st.session_state.connected_accounts.append({
                    "platform": platform,
                    "name": f"{label} • {p['name']}",
                    "project": p["name"],
                    "date": datetime.now()
                })
                st.session_state.show_project_dialog = False
                st.session_state.source_ready = f"{label} подключён к проекту «{p['name']}»!"
                st.rerun()
        st.divider()

    st.markdown("**Или создать новый проект:**")
    new_name = st.text_input("Название проекта", placeholder="Например: Магазин цветов", key="new_project_name")
    if st.button("➕ Создать и подключить", type="primary", use_container_width=True, key="btn_create_project"):
        if not new_name.strip():
            st.error("Введите название проекта.")
        else:
            existing = next((p for p in st.session_state.projects if p["name"].lower() == new_name.strip().lower()), None)
            project_name = existing["name"] if existing else new_name.strip()
            if existing is None:
                st.session_state.projects.append({"name": project_name, "created": datetime.now()})
            st.session_state.connected_accounts.append({
                "platform": platform,
                "name": f"{label} • {project_name}",
                "project": project_name,
                "date": datetime.now()
            })
            st.session_state.show_project_dialog = False
            st.session_state.source_ready = f"{label} подключён к проекту «{project_name}»!"
            db_log(st.session_state.user_email, "Подключён кабинет", f"{label} → {project_name}")
            st.rerun()

if st.session_state.get("show_project_dialog"):
    show_project_dialog()

# --- ОКНО ВЫБОРА КАБИНЕТОВ ЯНДЕКСА (реальные данные из API) ---
@st.dialog("🔴 Подключение Яндекс.Директ")
def show_yandex_dialog():
    st.caption("Шаг 1. Отметьте кабинеты, которые подключаем.")
    if "ya_accounts" not in st.session_state or not st.session_state.ya_accounts:
        with st.spinner("Получаем список кабинетов из Яндекса..."):
            st.session_state.ya_accounts = get_yandex_accounts()
    accounts = st.session_state.ya_accounts
    if not accounts:
        err = st.session_state.get("ya_error", "")
        st.warning(f"Яндекс не отдал список кабинетов. {err or 'Проверьте, что в приложении на oauth.yandex.ru включено право «Яндекс.Директ API».'}")
        return
    options = {}
    for a in accounts:
        options[f"{a['login']} — {a['name']}"] = a
    picked = st.multiselect("Кабинеты", list(options.keys()))
    st.caption("Шаг 2. В какой проект положить выбранные кабинеты?")
    if st.session_state.projects:
        mode = st.radio("Проект", ["Создать новый", "Выбрать существующий"], horizontal=True)
        if mode == "Выбрать существующий":
            project_name = st.selectbox("Существующий проект", [p["name"] for p in st.session_state.projects])
        else:
            project_name = st.text_input("Название нового проекта", placeholder="Например: Магазин цветов")
    else:
        project_name = st.text_input("Название проекта", placeholder="Например: Магазин цветов")
    if st.button("✅ Подключить выбранные", type="primary", use_container_width=True):
        if not picked:
            st.error("Выберите хотя бы один кабинет.")
            return
        if not project_name or not project_name.strip():
            st.error("Введите название проекта.")
            return
        room = total_limit - current_cabs
        if len(picked) > room:
            st.error(f"Тариф позволяет добавить ещё {room}, а выбрано {len(picked)}. Снимите лишние или расширьте тариф.")
            return
        pname = project_name.strip()
        if not any(p["name"] == pname for p in st.session_state.projects):
            st.session_state.projects.append({"name": pname, "created": datetime.now()})
        for key in picked:
            a = options[key]
            st.session_state.connected_accounts.append({
                "platform": "yandex",
                "name": f"Яндекс.Директ • {a['login']}",
                "project": pname,
                "login": a["login"],
                "date": datetime.now()
            })
        st.session_state.show_yandex_dialog = False
        st.session_state.source_ready = f"Подключено кабинетов: {len(picked)} → проект «{pname}»!"
        db_log(st.session_state.user_email, "Подключены кабинеты", f"{len(picked)} → {pname}")
        st.rerun()

if st.session_state.get("show_yandex_dialog"):
    show_yandex_dialog()

if st.session_state.get("source_ready"):
    msg = st.session_state.source_ready
    st.session_state.source_ready = None
    components.html(f"""
    <div id='okmsg' style='background:#14532d;color:#86efac;padding:10px 16px;border-radius:8px;font-size:14px;'>✅ {msg}</div>
    <script>setTimeout(function(){{document.getElementById('okmsg').style.display='none';}},180000);</script>
    """, height=60)

# --- ОКНО ЛИМИТА (самодостаточное) ---
@st.dialog("🛒 Расширение возможностей")
def show_limit_dialog():
    PR = {
        "trial":        {"price": 0,   "extra": 0,  "unit": "источник"},
        "business":     {"price": 20,  "extra": 10, "unit": "источник"},
        "agency_start": {"price": 50,  "extra": 5,  "unit": "проект"},
        "agency":       {"price": 150, "extra": 5,  "unit": "проект"},
        "agency_pro":   {"price": 300, "extra": 5,  "unit": "проект"},
        "enterprise":   {"price": 500, "extra": 5,  "unit": "проект"},
    }
    k = st.session_state.user_tariff
    t_name = "Пробный период" if k == "trial" else TARIFFS[k]["name"]
    p = PR.get(k, PR["business"])
    extra = st.session_state.extra_accounts
    max_extra = TARIFFS[k]["max_extra"] if k in TARIFFS else None
    unit_plural = "источники" if p["unit"] == "источник" else "проекты"
    can_buy = (k != "trial") and ((max_extra is None) or (extra < max_extra))

    st.markdown(f"Тариф «{t_name}»: доступные {unit_plural} закончились.")

    if can_buy:
        if st.button(f"➕ Купить ещё 1 {p['unit']} (+{p['extra']} €/мес)", use_container_width=True, key="dlg_buy_extra"):
            make_invoice(k, amount_eur=p["extra"], note=f"Дополнительный {p['unit']}, +1 мес", action="extra")
            st.session_state.show_limit_dialog = False
            st.session_state.invoice_ready = True
            st.rerun()
        if max_extra is not None:
            st.caption(f"Ваш тариф позволяет докупить не более {max_extra} {unit_plural}. Уже докуплено: {extra}.")
    else:
        st.caption("Докупка мест на этом тарифе недоступна — выберите тариф выше.")

    st.markdown("**Или перейти на другой тариф:**")
    keys = ["business", "agency_start", "agency", "agency_pro", "enterprise"]
    texts = []
    for x in keys:
        if x == "business":
            texts.append(f"{TARIFFS[x]['name']} — {PR[x]['price']} €/мес — 1 источник")
        elif x == "enterprise":
            texts.append(f"{TARIFFS[x]['name']} — {PR[x]['price']} €/мес — от 100 проектов")
        else:
            texts.append(f"{TARIFFS[x]['name']} — {PR[x]['price']} €/мес — до {TARIFFS[x]['limit']} проектов")
    choice = st.selectbox("Выбрать тариф", texts, key="dlg_new_tariff")
    if st.button("💳 Сформировать счёт", type="primary", use_container_width=True, key="dlg_switch"):
        new_tariff = keys[texts.index(choice)]
        make_invoice(new_tariff, note=f"Переход на тариф «{TARIFFS[new_tariff]['name']}», подписка 30 дней", action="switch", action_data={"tariff": new_tariff})
        st.session_state.show_limit_dialog = False
        st.session_state.invoice_ready = True
        st.rerun()
        st.session_state.user_tariff = keys[texts.index(choice)]
        st.session_state.sub_end = datetime.now() + timedelta(days=30)
        st.session_state.extra_accounts = 0
        st.session_state.show_limit_dialog = False
        st.session_state.invoice_ready = True
        st.rerun()

if st.session_state.get("show_limit_dialog"):
    show_limit_dialog()

if st.session_state.get("invoice_ready") and st.session_state.invoices:
    inv = st.session_state.invoices[-1]
    st.success(f"✅ Счёт {inv['num']} на {inv['sum']} сформирован. Услуга активируется после оплаты (кнопка «✓ Оплачен» в боковушке, раздел «Мои счета»).")
    st.download_button("⬇ Скачать счёт", data=inv["html"], file_name=inv["num"] + ".html", mime="text/html", key="dl_last_invoice")
    st.session_state.invoice_ready = False

st.divider()

# 3. В КОНЦЕ: справочная информация
st.markdown(f"Подключено {unit_name}ов: {current_cabs} из {total_limit}")
st.progress(min(current_cabs / total_limit, 1.0) if total_limit > 0 else 0)
# Сохраняем всё в базу при каждом действии
db_sync_all()

# =========================
# ЭКРАН 2: ВЫБОР РЕЖИМА
# =========================
if st.session_state.nav_screen == "choose_mode":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    st.markdown("### Как посмотреть результаты?")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("📁 По проектам", use_container_width=True, type="primary"):
            st.session_state.view_mode = "projects"
            st.session_state.nav_screen = "projects_list"
            st.rerun()
    
    with col2:
        if st.button("⚠ По критичности", use_container_width=True, type="primary"):
            st.session_state.view_mode = "problems"
            st.session_state.nav_screen = "categories_list"
            st.rerun()

# =========================
# ЭКРАН 3: СПИСОК ПРОЕКТОВ
# =========================
elif st.session_state.nav_screen == "projects_list":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    st.markdown("### 📁 Выберите проект")
    
    results = st.session_state.scan_results
    projects = list(set(r["project"] for r in results if r["status"] != "ok"))
    
    if not projects:
        st.success("✅ Все проблемы отработаны!")
        if st.button("🔄 Новое сканирование"):
            st.session_state.scan_results = None
            st.session_state.nav_screen = "scan"
            st.rerun()
        st.stop()
    
    for proj in projects:
        proj_problems = [r for r in results if r["project"] == proj and r["status"] != "ok"]
        critical_count = len([r for r in proj_problems if r["status"] == "critical"])
        warning_count = len([r for r in proj_problems if r["status"] == "warning"])
        
        st.markdown("---")
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"#### 📁 {proj}")
            if critical_count > 0: st.caption(f"🔴 Критично: {critical_count}")
            if warning_count > 0: st.caption(f"🟡 Требует внимания: {warning_count}")
        with col2:
            if st.button("👉 Открыть", key=f"proj_{proj}"):
                st.session_state.selected_project = proj
                st.session_state.nav_screen = "categories_in_project"
                st.rerun()
    
    if st.button("️ Назад к выбору режима"):
        st.session_state.nav_screen = "choose_mode"
        st.rerun()

# =========================
# ЭКРАН 4: КАТЕГОРИИ В ПРОЕКТЕ
# =========================
elif st.session_state.nav_screen == "categories_in_project":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    proj = st.session_state.selected_project
    st.markdown(f"###  {proj}")
    st.markdown("Выберите категорию проблем:")
    
    results = st.session_state.scan_results
    proj_results = [r for r in results if r["project"] == proj and r["status"] != "ok"]
    
    if not proj_results:
        st.success("✅ В этом проекте все проблемы отработаны!")
        if st.button("⬅️ Назад к проектам"):
            st.session_state.nav_screen = "projects_list"
            st.rerun()
        st.stop()
    
    critical = [r for r in proj_results if r["status"] == "critical"]
    warning = [r for r in proj_results if r["status"] == "warning"]
    
    if critical:
        st.markdown("---")
        if st.button(f"🔴 Критично ({len(critical)})", use_container_width=True):
            st.session_state.selected_category = "critical"
            st.session_state.nav_screen = "campaigns_list"
            st.rerun()
    
    if warning:
        st.markdown("---")
        if st.button(f"🟡 Требует внимания ({len(warning)})", use_container_width=True):
            st.session_state.selected_category = "warning"
            st.session_state.nav_screen = "campaigns_list"
            st.rerun()
    
    if st.button("⬅️ Назад к проектам"):
        st.session_state.nav_screen = "projects_list"
        st.rerun()

# =========================
# ЭКРАН: КАТЕГОРИИ (ПО КРИТИЧНОСТИ)
# =========================
elif st.session_state.nav_screen == "categories_list":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    st.markdown("### ⚠ Выберите категорию проблем")
    
    results = st.session_state.scan_results
    critical = [r for r in results if r["status"] == "critical"]
    warning = [r for r in results if r["status"] == "warning"]
    
    if not critical and not warning:
        st.success("✅ Все проблемы отработаны!")
        if st.button("🔄 Новое сканирование"):
            st.session_state.scan_results = None
            st.session_state.nav_screen = "scan"
            st.rerun()
        st.stop()
    
    if critical:
        st.markdown("---")
        if st.button(f"🔴 Критично ({len(critical)})", use_container_width=True):
            st.session_state.selected_category = "critical"
            st.session_state.nav_screen = "projects_by_category"
            st.rerun()
    
    if warning:
        st.markdown("---")
        if st.button(f" Требует внимания ({len(warning)})", use_container_width=True):
            st.session_state.selected_category = "warning"
            st.session_state.nav_screen = "projects_by_category"
            st.rerun()
    
    if st.button("⬅️ Назад к выбору режима"):
        st.session_state.nav_screen = "choose_mode"
        st.rerun()

# =========================
# ЭКРАН: ПРОЕКТЫ В КАТЕГОРИИ
# =========================
elif st.session_state.nav_screen == "projects_by_category":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    category = st.session_state.selected_category
    cat_name = "🔴 Критично" if category == "critical" else "🟡 Требует внимания"
    st.markdown(f"### {cat_name}")
    st.markdown("Выберите проект:")
    
    results = st.session_state.scan_results
    filtered = [r for r in results if r["status"] == category]
    projects = list(set(r["project"] for r in filtered))
    
    if not projects:
        st.success("✅ В этой категории все проблемы отработаны!")
        if st.button("⬅️ Назад к категориям"):
            st.session_state.nav_screen = "categories_list"
            st.rerun()
        st.stop()
    
    for proj in projects:
        count = len([r for r in filtered if r["project"] == proj])
        st.markdown("---")
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"#### 📁 {proj}")
            st.caption(f"{count} кампаний с проблемами")
        with col2:
            if st.button("👉 Открыть", key=f"cat_proj_{proj}"):
                st.session_state.selected_project = proj
                st.session_state.nav_screen = "campaigns_list"
                st.rerun()
    
    if st.button("⬅️ Назад к категориям"):
        st.session_state.nav_screen = "categories_list"
        st.rerun()

# =========================
# ЭКРАН 5: КАМПАНИИ
# =========================
elif st.session_state.nav_screen == "campaigns_list":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    proj = st.session_state.selected_project
    cat = st.session_state.selected_category
    
    st.markdown(f"### 📁 {proj}")
    cat_name = "🔴 Критично" if cat == "critical" else "🟡 Требует внимания"
    st.markdown(f"**{cat_name}**")
    st.markdown("Выберите кампанию:")
    
    results = st.session_state.scan_results
    filtered = [r for r in results if r["project"] == proj and r["status"] == cat]
    
    if not filtered:
        st.success("✅ В этой категории все проблемы отработаны!")
        back_screen = "categories_in_project" if st.session_state.view_mode == "projects" else "projects_by_category"
        if st.button(f"⬅️ Назад"):
            st.session_state.nav_screen = back_screen
            st.rerun()
        st.stop()
    
    for res in filtered:
        st.markdown("---")
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(f"**{res['campaign']}**")
            st.caption(f"[{res['source'].upper()}]")
        with col2:
            if st.button(" Открыть", key=f"camp_{res['label']}"):
                st.session_state.selected_campaign = res
                st.session_state.nav_screen = "problem_detail"
                st.rerun()
    
    back_screen = "categories_in_project" if st.session_state.view_mode == "projects" else "projects_by_category"
    if st.button("⬅️ Назад"):
        st.session_state.nav_screen = back_screen
        st.rerun()

# =========================
# ЭКРАН 6: ДЕТАЛИ ПРОБЛЕМЫ
# =========================
elif st.session_state.nav_screen == "problem_detail":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    res = st.session_state.selected_campaign
    
    st.markdown(f"### {res['campaign']}")
    st.caption(f"[{res['source'].upper()}] • {res['project']}")
    st.markdown("---")
    
    st.markdown("#### 🔴 Проблема")
    st.error(res['problem'])
    
    st.markdown("#### 💡 Что проверить")
    st.markdown("""
    • Формы заявки на сайте
    • Посадочную страницу
    • Поисковые запросы
    • Объявления и креативы
    """)
    
    st.markdown("---")
    st.markdown("#### Действия")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🔗 Перейти в кабинет", use_container_width=True):
            url = get_campaign_url(res["source"], res["campaign_id"])
            st.markdown(f'<a href="{url}" target="_blank">Открыть в новой вкладке</a>', unsafe_allow_html=True)
            st.session_state.history[res["label"]] = {"action": "Перешёл в кабинет", "date": datetime.now().strftime("%d.%m.%Y %H:%M")}
            save_history(st.session_state.history)
            st.session_state.nav_screen = "campaigns_list"
            st.rerun()
    
    with col2:
        if st.button("✅ Наблюдать", use_container_width=True):
            st.session_state.history[res["label"]] = {"action": "Наблюдать", "date": datetime.now().strftime("%d.%m.%Y %H:%M")}
            save_history(st.session_state.history)
            st.session_state.nav_screen = "campaigns_list"
            st.rerun()
    
    with col3:
        if st.button("⏸ Игнорировать", use_container_width=True):
            hide_until = datetime.now() + timedelta(hours=24)
            st.session_state.history[res["label"]] = {"action": "Игнорировать", "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "hide_until": hide_until.strftime("%d.%m.%Y %H:%M")}
            save_history(st.session_state.history)
            st.session_state.nav_screen = "campaigns_list"
            st.rerun()
    
    if st.button("⬅️ Назад к списку кампаний"):
        st.session_state.nav_screen = "campaigns_list"
        st.rerun()