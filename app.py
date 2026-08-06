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
    end_date = st.session_state.trial_end if st.session_state.user_tariff == "trial" else st.session_state.sub_end
    if not end_date: return 0
    return max(0, (end_date - datetime.now()).days)

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
    return f"https://oauth.yandex.ru/authorize?response_type=code&client_id={YANDEX_CLIENT_ID}&redirect_uri={YANDEX_REDIRECT_URI}"

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

# Вспомогательные функции
def get_total_limit():
    if st.session_state.user_tariff == "trial": return 1
    if not st.session_state.user_tariff: return 0
    return TARIFFS[st.session_state.user_tariff]["limit"] + st.session_state.extra_accounts

def get_days_left():
    end_date = st.session_state.trial_end if st.session_state.user_tariff == "trial" else st.session_state.sub_end
    if not end_date: return 0
    return max(0, (end_date - datetime.now()).days)

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

    # Условия, галочка и счёт
    if st.session_state.get("terms_tariff"):
        st.divider()
        k = st.session_state.terms_tariff
        info = TARIFFS[k]
        p = PRICES_EUR[k]
        st.markdown(f"####  Условия тарифа «{info['name']}»")
        st.markdown(f"""
- Базовая цена: **{price(p['price'])}/мес** (фиксировано в евро: {p['price']} €)
- Включено: **{info['limit']}** {p['unit']}
- Дополнительная единица: **+{price(p['extra'])}/мес** за {p['unit']}{' (максимум ' + str(info['max_extra']) + ')' if info['max_extra'] else ' (без лимита)'}
- Оплата: картой или по счёту для юрлиц. Подписка — 30 дней.
""")
        agree = st.checkbox("Я ознакомился(ась) с условиями и согласен(на)", key="agree_terms")
        if agree:
            if st.button("💳 Получить счёт и активировать", type="primary", use_container_width=True, key="btn_activate_tariff"):
                st.session_state.user_tariff = k
                st.session_state.sub_end = datetime.now() + timedelta(days=30)
                st.session_state.terms_tariff = None
                st.success("Счёт сформирован (заглушка).")
                st.rerun()

    st.stop()

# =========================
# ЭКРАН 3: ШАПКА РАБОЧЕГО ПРОСТРАНСТВА
# =========================
now = datetime.now()
st.markdown(f"# Namectus v1.0 | {now.strftime('%d.%m.%Y %H:%M:%S')}")

# Инфо-панель справа
col_info1, col_info2, col_info3 = st.columns([3, 1, 2])
with col_info1: st.markdown(f"**{st.session_state.user_email}**")
with col_info2: 
    tariff_name = "Пробный период" if st.session_state.user_tariff == "trial" else TARIFFS[st.session_state.user_tariff]["name"]
    st.markdown(f"💎 {tariff_name}")
with col_info3: 
    days = get_days_left()
    st.markdown(f"⏳ Осталось: {days} дней")

st.markdown("---")

# Статус кабинетов
current_cabs = len(st.session_state.connected_accounts)
total_limit = get_total_limit()
st.markdown(f"### Подключено кабинетов: {current_cabs} из {total_limit}")
st.progress(min(current_cabs / total_limit, 1.0) if total_limit > 0 else 0)

st.markdown("---")
st.markdown("### Подключите рекламный кабинет")

# Кнопки подключения (Яндекс активен, остальные заглушки)
col_y, col_g, col_m = st.columns(3)
with col_y:
    st.markdown("#### 🔴 Яндекс.Директ")
    if st.button("Подключить Яндекс", use_container_width=True, key="btn_yandex"):
        if current_cabs < total_limit:
            st.session_state.connected_accounts.append({"platform": "yandex", "name": f"Яндекс #{current_cabs+1}", "date": datetime.now()})
            st.success("Яндекс подключён!")
            st.rerun()
        else:
            st.error("⚠️ Лимит превышен! Нужно докупить кабинет.")
            # Здесь потом будет модалка докупки
with col_g:
    st.markdown("#### 🔵 Google Ads")
    st.button("Скоро", use_container_width=True, disabled=True, key="btn_soon_g")
with col_m:
    st.markdown("#### 🔷 Meta Ads")
    st.button("Скоро", use_container_width=True, disabled=True, key="btn_soon_m")

st.markdown("---")

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

# Загрузка токена
if "yandex_token" not in st.session_state and os.path.exists(TOKENS_FILE):
    try:
        with open(TOKENS_FILE, 'r', encoding='utf-8') as f:
            token = json.load(f).get("yandex", {}).get("token")
            if token: st.session_state["yandex_token"] = token
    except: pass

# Обработка OAuth
query_params = st.query_params
if "code" in query_params and "yandex_token" not in st.session_state:
    token = exchange_code_for_token(query_params["code"])
    if token:
        st.session_state["yandex_token"] = token
        with open(TOKENS_FILE, 'w', encoding='utf-8') as f:
            json.dump({"yandex": {"token": token}}, f)
        st.query_params.clear()
        st.rerun()

# =========================
# ЭКРАН: ВХОД
# =========================
if "yandex_token" not in st.session_state:
    st.markdown("### 👋 Добро пожаловать в Namectus")
    st.markdown("Выберите рекламную платформу для подключения:")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        <div style="border: 2px solid #e0e0e0; border-radius: 12px; padding: 20px; text-align: center;">
            <h3>🔴 Яндекс.Директ</h3>
        </div>
        """, unsafe_allow_html=True)
        auth_url = get_yandex_auth_url()
        st.markdown(f'[🔐 Войти через Яндекс]({auth_url})')

    with col2:
        st.markdown("""
        <div style="border: 2px dashed #e0e0e0; border-radius: 12px; padding: 20px; text-align: center; opacity: 0.6;">
            <h3>🔵 Google Ads</h3>
            <p>Скоро будет доступно</p>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div style="border: 2px dashed #e0e0e0; border-radius: 12px; padding: 20px; text-align: center; opacity: 0.6;">
            <h3>🔷 Meta Ads</h3>
            <p>Скоро будет доступно</p>
        </div>
        """, unsafe_allow_html=True)

    st.stop()

# =========================
# ЭКРАН 1: СКАНИРОВАНИЕ
# =========================
if st.session_state.nav_screen == "scan":
    now = datetime.now()
    st.markdown(f"# NAMECTUS v1.1 | {now.strftime('%d.%m.%Y %H:%M:%S')}")
    st.markdown("---")
    
    st.success("☑ Вы подключены к Яндекс.Директ")
    st.markdown("Нажмите кнопку ниже, чтобы проверить состояние кампаний.")
    
    if st.button("🔍 Сканировать"):
        with st.spinner("🔄 Анализируем данные..."):
            try:
                SHEET_ID = "10cf-dT0Sd5K2c-39x_7zOxbyUdB8Lsr264VdTMhNP7E"
                df = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv")
                results = analyze_campaigns(df)
                results = filter_hidden(results, st.session_state.history)
                
                if not results:
                    st.warning("Нет данных")
                    st.stop()
                
                st.session_state.scan_results = results
                st.session_state.nav_screen = "choose_mode"
                st.rerun()
            except Exception as e:
                st.error(f"Ошибка: {e}")
                if st.button("🧪 Тестовые данные"):
                    test_data = {'project': ['Bio-wc-service', 'solodent'], 'campaign': ['Баннер', 'Поиск'], 'source': ['yandex', 'yandex'], 'campaign_id': [1, 2], 'date': pd.date_range('2026-07-01', periods=2), 'cost': [368, 120], 'conversions': [0, 0], 'clicks': [45, 30], 'impressions': [9000, 5000], 'budget': [1000, 1000]}
                    df_test = pd.DataFrame(test_data)
                    st.session_state.scan_results = filter_hidden(analyze_campaigns(df_test), st.session_state.history)
                    st.session_state.nav_screen = "choose_mode"
                    st.rerun()
                st.stop()

# =========================
# ЭКРАН 2: ВЫБОР РЕЖИМА
# =========================
elif st.session_state.nav_screen == "choose_mode":
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