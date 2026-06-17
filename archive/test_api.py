import requests

response = requests.get("https://api.github.com")

print("Статус ответа:", response.status_code)
print("Ответ сервера:")
print(response.text[:200])