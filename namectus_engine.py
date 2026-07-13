import json

class NamectusEngine:
    def __init__(self):
        with open('texts/ru_alerts.json', 'r', encoding='utf-8') as file:
            self.data = json.load(file)
    
    def check_campaign(self, campaign_info):
        alerts = []
        
        # ПРАВИЛО 1: Нет заявок
        if campaign_info['days'] >= 3 and campaign_info['spend'] > 0 and campaign_info['conversions'] == 0:
            vars = {'days': campaign_info['days'], 'spend': campaign_info['spend'], 
                    'currency': campaign_info['currency'], 'clicks': campaign_info['clicks']}
            
            alerts.append({
                'severity': 'critical',
                'title': self.data['rules']['no_conversions']['title'].format(**vars),
                'description': self.data['rules']['no_conversions']['description'].format(**vars),
                'action': self.data['rules']['no_conversions']['action']
            })
        
        # ПРАВИЛО 2: Бюджет заканчивается
        if campaign_info['budget_remaining'] > 0 and campaign_info['daily_spend'] > 0:
            days_left = campaign_info['budget_remaining'] / campaign_info['daily_spend']
            if days_left <= 5:
                vars = {'days': int(days_left), 'remaining': campaign_info['budget_remaining'], 
                        'daily': campaign_info['daily_spend'], 'currency': campaign_info['currency']}
                
                alerts.append({
                    'severity': 'warning',
                    'title': self.data['rules']['budget_running_out']['title'].format(**vars),
                    'description': self.data['rules']['budget_running_out']['description'].format(**vars),
                    'action': self.data['rules']['budget_running_out']['action']
                })
        
        return alerts