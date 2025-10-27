import requests
import json

# Тестируем API userbot
url = "http://localhost:8001/rooms/get_views"
data = {
    "contractor_id": "1",
    "channel_id": -1003252895737,
    "limit": 10
}

try:
    response = requests.post(url, json=data, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")
