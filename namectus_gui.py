import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
import json
import os
import webbrowser
from datetime import datetime

# 1. КОНФИГУРАЦИЯ
CONFIG = {
    "periods": {"recent_days": 3, "history_days": 21, "min_data_days": 7},
    "thresholds": {"ctr_min": 0.005, "ctr_max": 0.15, "cpa_target": 2000.0, "conversion_drop_pct": 0.4},
    "messages": {"ok": [
        "Показатели соответствуют историческому тренду",
        "Система не обнаружила критических отклонений",
        "Кампания работает стабильно"
    ]}
}

# Тестовые бюджеты
CAMPAIGN_BUDGETS = {"R1": 295000, "S1": 290000, "M1": 500000}
HISTORY_FILE = "action_history.json"

# 2. ФУНКЦИЯ ОТКРЫТИЯ РЕКЛАМНОГО КАБИНЕТА
def open_campaign_browser(source, campaign_id):
    """Открывает браузер с прямой ссылкой на кампанию в рекламном кабинете"""
    if source == "google":
        url = f"https://ads.google.com/aw/campaigns?campaignId={campaign_id}&ocid={campaign_id}"
    elif source == "yandex":
        url = f"https://direct.yandex.ru/registered/main.pl?cmd=edit-campaign&id={campaign_id}"
    elif source == "meta":
        url = f"https://www.facebook.com/adsmanager/manage/campaigns?act=0&campaign_id={campaign_id}"
    else:
        url = "https://google.com"
    
    webbrowser.open(url)

# 3. ЯДРО АНАЛИЗА
def analyze_campaigns(df: pd.DataFrame):
    results = []
    periods, thresholds, messages = CONFIG["periods"], CONFIG["thresholds"], CONFIG["messages"]

    for (project, campaign), camp_df in df.groupby(["project", "campaign"]):
        camp_df = camp_df.sort_values("date").reset_index(drop=True)
        total_days = len(camp_df)
        source = camp_df["source"].iloc[0]
        campaign_id = camp_df["campaign_id"].iloc[0]

        if total_days < periods["min_data_days"]:
            results.append({
                "label": f"{project}/{campaign}",
                "icon": "⚪",
                "title": "Накопление данных",
                "problem": "",
                "actions": ["👁 Наблюдать", "🔕 Закрыть"],
                "source": source,
                "campaign_id": campaign_id
            })
            continue

        total_spent = camp_df["cost"].sum()
        budget_limit = CAMPAIGN_BUDGETS.get(campaign, total_spent * 1.5)
        remaining = budget_limit - total_spent
        avg_daily = total_spent / max(total_days, 1)
        days_left = remaining / max(avg_daily, 1)

        if remaining <= 0 or days_left <= 0:
            results.append({
                "label": f"{project}/{campaign}",
                "icon": "",
                "title": "Реклама остановлена",
                "problem": "Бюджет исчерпан. Объявления не показываются.",
                "actions": ["💳 Пополнить", "🔕 Закрыть"],
                "source": source,
                "campaign_id": campaign_id
            })
        elif days_left <= 1:
            results.append({
                "label": f"{project}/{campaign}",
                "icon": "🔴",
                "title": "Бюджет на исходе",
                "problem": "Бюджет закончится завтра (~1 дн.)",
                "actions": ["💳 Пополнить", "👁 Наблюдать", "🔕 Игнорировать"],
                "source": source,
                "campaign_id": campaign_id
            })
        elif days_left <= 3:
            results.append({
                "label": f"{project}/{campaign}",
                "icon": "🟠",
                "title": "Бюджет скоро закончится",
                "problem": f"Бюджет закончится через ~{int(days_left)} дня. Время согласовать оплату.",
                "actions": ["💳 Пополнить", "👁 Наблюдать", "🔕 Игнорировать"],
                "source": source,
                "campaign_id": campaign_id
            })
        elif days_left <= 5:
            results.append({
                "label": f"{project}/{campaign}",
                "icon": "",
                "title": "Плановое завершение бюджета",
                "problem": f"Бюджет закончится через ~{int(days_left)} дней.",
                "actions": ["💳 Пополнить", "👁 Наблюдать", "🔕 Игнорировать"],
                "source": source,
                "campaign_id": campaign_id
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
            h_cpa = h_cost / max(h_conv, 1)
            r_ctr = r_clicks / max(r_impr, 1)

            signals, problem = [], ""
            if r_cost > 0 and r_conv == 0:
                signals.append("critical")
                problem = "Расход без конверсий"
            elif h_conv > 0 and r_cpa > h_cpa * 1.8:
                signals.append("critical")
                problem = "Резкий рост CPA"
            elif h_conv > 0 and r_conv < h_conv * (1 - thresholds["conversion_drop_pct"]):
                signals.append("warning")
                problem = "Падение конверсий"
            elif r_ctr < thresholds["ctr_min"]:
                signals.append("warning")
                problem = "Низкий CTR"
            elif r_ctr > thresholds["ctr_max"]:
                signals.append("warning")
                problem = "Аномальный CTR"

            if "critical" in signals:
                icon, title, acts = "🔴", "Критическое отклонение", ["🔧 Исправить", "👁 Наблюдать", "🔕 Игнорировать"]
            elif "warning" in signals:
                icon, title, acts = "🟠", "Требует внимания", ["🔧 Исправить", "👁 Наблюдать", "🔕 Игнорировать"]
            else:
                icon, title, acts, problem = "", f"{messages['ok'][hash(campaign) % len(messages['ok'])]}", [], ""

            results.append({
                "label": f"{project}/{campaign}",
                "icon": icon,
                "title": title,
                "problem": problem,
                "actions": acts,
                "source": source,
                "campaign_id": campaign_id
            })
    return results

# 4. ИСТОРИЯ ДЕЙСТВИЙ
def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_history(data):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 5. ИНТЕРФЕЙС
class NamectusApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Namectus | Утренний отчёт")
        self.root.geometry("900x700")
        self.root.configure(bg="#f5f7fa")
        self.status_labels = {}
        self.campaign_data = {}
        self.history = load_history()
        self.build_ui()
        self.refresh()

    def build_ui(self):
        tk.Label(
            self.root,
            text=f"📅 NAMECTUS | {datetime.now().strftime('%d.%m.%Y')}",
            font=("Segoe UI", 16, "bold"),
            bg="#f5f7fa"
        ).pack(pady=10)

        self.canvas = tk.Canvas(self.root, bg="#f5f7fa", highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = tk.Frame(self.canvas, bg="#f5f7fa")
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        tk.Button(
            self.root,
            text="🔄 Пересканировать",
            command=self.refresh,
            font=("Segoe UI", 10)
        ).pack(pady=8)

    def refresh(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        try:
            df = pd.read_csv("data_storage.csv")
            results = analyze_campaigns(df)
            for res in results:
                self.draw_card(res)
        except Exception as e:
            tk.Label(
                self.scroll_frame,
                text=f"❌ Ошибка загрузки: {e}",
                fg="red",
                bg="#f5f7fa"
            ).pack(pady=30)

    def draw_card(self, res):
        frame = tk.Frame(self.scroll_frame, bg="white", bd=1, relief="solid")
        frame.pack(fill="x", padx=15, pady=6)

        # Заголовок карточки
        tk.Label(
            frame,
            text=f"{res['label']}  {res['icon']}  [{res['source'].upper()}]",
            font=("Segoe UI", 12, "bold"),
            bg="white"
        ).pack(anchor="w", padx=10, pady=(10, 0))

        # Проблема
        if res.get('problem'):
            tk.Label(
                frame,
                text=f"⚠️ {res['problem']}",
                fg="#c0392b",
                bg="white",
                wraplength=750
            ).pack(anchor="w", padx=10)

        # Статус действия
        self.status_labels[res['label']] = tk.Label(
            frame,
            text="",
            fg="#27ae60",
            bg="white",
            font=("Segoe UI", 10, "italic")
        )
        self.status_labels[res['label']].pack(anchor="w", padx=10, pady=(0, 5))

        # Сохраняем данные кампании
        self.campaign_data[res['label']] = {
            "source": res.get("source", ""),
            "campaign_id": res.get("campaign_id", "")
        }

        # Кнопки действий
        btn_frame = tk.Frame(frame, bg="white")
        btn_frame.pack(anchor="w", padx=10, pady=(0, 10))

        for act in res.get('actions', []):
            btn = tk.Button(
                btn_frame,
                text=act,
                font=("Segoe UI", 9),
                bg="#ecf0f1",
                activebackground="#d5dbdb",
                command=lambda a=act, l=res['label']: self.take_action(l, a)
            )
            btn.pack(side="left", padx=3)

        # Кнопка "Отметить пополненным" (всегда видна для кампаний с бюджетными проблемами)
        if "Пополнить" in res.get('actions', []):
            confirm_btn = tk.Button(
                btn_frame,
                text="✅ Отметить пополненным",
                font=("Segoe UI", 9),
                bg="#d5f4e6",
                activebackground="#a8e6cf",
                command=lambda l=res['label']: self.confirm_top_up(l)
            )
            confirm_btn.pack(side="left", padx=3)

        # Показываем сохранённое действие из истории
        if res['label'] in self.history:
            hist = self.history[res['label']]
            self.status_labels[res['label']].config(
                text=f"✅ {hist['action']} ({hist['date']})"
            )

    def take_action(self, label, action):
        """Обработка нажатия на кнопку действия"""
        data = self.campaign_data.get(label, {})
        source = data.get("source", "")
        campaign_id = data.get("campaign_id", "")
        
        # Если действие связано с переходом в кабинет
        if "Пополнить" in action or "Исправить" in action:
            # Открываем рекламный кабинет
            open_campaign_browser(source, campaign_id)
            
            # Записываем в историю
            self.history[label] = {
                "action": action,
                "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "status": "pending"
            }
            save_history(self.history)
            self.status_labels[label].config(text=f"🌐 Открыт кабинет. Ожидание подтверждения...")
            
            msg = f"Открыт рекламный кабинет {source.upper()}.\n\n"
            if "Пополнить" in action:
                msg += "После пополнения бюджета нажмите '✅ Отметить пополненным'."
            else:
                msg += "Внесите изменения в настройках кампании."
            
            messagebox.showinfo("Namectus", msg)
        else:
            # Обычное действие (Наблюдать, Игнорировать, Закрыть)
            self.history[label] = {
                "action": action,
                "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                "status": "done"
            }
            save_history(self.history)
            self.status_labels[label].config(text=f"✅ {action} ({self.history[label]['date']})")
            messagebox.showinfo("Namectus", f"Действие '{action}' для {label} сохранено.")

    def confirm_top_up(self, label):
        """Подтверждение пополнения бюджета"""
        if label in self.history and self.history[label].get("action") == "💳 Пополнить":
            self.history[label]["status"] = "done"
            self.history[label]["confirmed_date"] = datetime.now().strftime("%d.%m.%Y %H:%M")
            save_history(self.history)
            self.status_labels[label].config(
                text=f"✅ Бюджет пополнен ({self.history[label]['confirmed_date']})"
            )
            messagebox.showinfo(
                "Namectus",
                f"Бюджет для {label} отмечен как пополненный.\n\n"
                f"В реальной версии Namectus автоматически проверит остаток через API."
            )
        else:
            messagebox.showwarning(
                "Namectus",
                f"Сначала нажмите '💳 Пополнить', чтобы открыть рекламный кабинет."
            )

if __name__ == "__main__":
    root = tk.Tk()
    app = NamectusApp(root)
    root.mainloop()