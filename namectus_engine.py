import json


class NamectusEngine:
    """Движок правил NAMECTUS: тексты правил читает из texts/ru_alerts.json."""

    def __init__(self, path="texts/ru_alerts.json"):
        with open(path, "r", encoding="utf-8") as file:
            self.data = json.load(file)

    def _alert(self, key, severity, vars):
        rule = self.data.get("rules", {}).get(key)
        if not rule:
            return None
        return {
            "severity": severity,
            "title": rule["title"].format(**vars),
            "description": rule["description"].format(**vars),
            "action": rule["action"],
            "key": key,
        }

    def check_campaign(self, c):
        alerts = []
        cur = c.get("currency", "₽")

        # 1. Траты без заявок
        if c.get("days", 0) >= 3 and c.get("spend", 0) > 0 and c.get("conversions", 0) == 0:
            a = self._alert("no_conversions", "critical", {
                "days": c.get("days", 0), "spend": round(c.get("spend", 0), 2),
                "currency": cur, "clicks": c.get("clicks", 0)})
            if a: alerts.append(a)

        # 2. Кампания остановлена
        if c.get("status") in ("STOPPED", "OFF", "PAUSED", "SUSPENDED"):
            a = self._alert("campaign_stopped", "critical", {})
            if a: alerts.append(a)

        # 3. Бюджет заканчивается
        if c.get("budget_remaining", 0) > 0 and c.get("daily_spend", 0) > 0:
            days_left = c["budget_remaining"] / c["daily_spend"]
            if days_left <= 5:
                a = self._alert("budget_running_out", "warning", {
                    "days": int(days_left), "remaining": round(c["budget_remaining"], 2),
                    "daily": round(c["daily_spend"], 2), "currency": cur})
                if a: alerts.append(a)

        # 4. Бюджет исчерпан
        if c.get("budget_exhausted"):
            a = self._alert("budget_exhausted", "critical", {})
            if a: alerts.append(a)

        # 5. Рост стоимости заявки
        prev_cpa, cur_cpa = c.get("previous_cpa", 0), c.get("current_cpa", 0)
        if prev_cpa > 0 and cur_cpa > prev_cpa * 1.2:
            a = self._alert("cpa_increased", "warning", {
                "percent": int(round((cur_cpa - prev_cpa) / prev_cpa * 100)),
                "prev_cpa": round(prev_cpa, 2), "cur_cpa": round(cur_cpa, 2), "currency": cur})
            if a: alerts.append(a)

        # 6. Падение CTR
        prev_ctr, cur_ctr = c.get("previous_ctr", 0), c.get("current_ctr", 0)
        if prev_ctr > 0 and cur_ctr < prev_ctr * 0.8:
            a = self._alert("ctr_dropped", "warning", {
                "prev_ctr": round(prev_ctr * 100, 2), "cur_ctr": round(cur_ctr * 100, 2)})
            if a: alerts.append(a)

        # 7. Битые ссылки
        if c.get("broken_links_count", 0) > 0:
            a = self._alert("broken_links", "critical", {"count": c["broken_links_count"]})
            if a: alerts.append(a)

        # 8. Отказы
        if c.get("bounce_rate", 0) >= 40:
            a = self._alert("bounce_rate", "warning", {"rate": int(c["bounce_rate"])})
            if a: alerts.append(a)

        # 9-14. Флаги из кабинета (вторая волна, когда скан научится читать настройки)
        for flag, key, severity in [
            ("flag_age_under_18", "age_under_18", "warning"),
            ("flag_no_extensions", "no_extensions", "warning"),
            ("flag_no_analytics", "no_analytics", "critical"),
            ("flag_autotargeting", "uncontrolled_autotargeting", "warning"),
            ("flag_no_monitoring", "no_site_monitoring", "critical"),
            ("flag_no_minus_words", "empty_minus_words", "warning"),
        ]:
            if c.get(flag):
                a = self._alert(key, severity, {})
                if a: alerts.append(a)

        return alerts