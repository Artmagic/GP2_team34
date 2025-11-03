import requests
import pandas as pd
from tqdm import tqdm
import time
import json

url = "https://api.cian.ru/search-offers/v2/search-offers-desktop/"

# === 2. ТВОИ cookies (вставь из браузера!) ===
COOKIES = "frontend_session_id=abc123xyz; device_id=xyz098abc; session_region_id=1"

# === 3. Заголовки ===
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/118.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru,en;q=0.9",
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": "https://www.cian.ru",
    "Referer": "https://www.cian.ru/",
    "X-Requested-With": "XMLHttpRequest",
    "Cookie": COOKIES,
}

# === 4. Получение одной страницы ===
def get_page(page_num):
    payload = {
        "jsonQuery": {
            "_type": "commercialrent",
            "engine_version": {"type": "term", "value": 2},
            "office_type": {"type": "terms", "value": [4, 5]},
            "region": {"type": "terms", "value": [1]},
            "floor_types": {"type": "terms", "value": [1]},
            "page": {"type": "term", "value": page_num}
        }
    }

    r = requests.post(url, headers=headers, json=payload)
    if r.status_code == 403:
        raise Exception("403 Forbidden — проверь cookies")
    r.raise_for_status()
    return r.json()

# === 5. Извлечение данных из ответа ===
def parse_offers(data):
    offers = []
    for offer in data.get("data", {}).get("offersSerialized", []):
        info = {
            "id": offer.get("id"),
            "title": offer.get("title"),
            "address": offer.get("geo", {}).get("address"),
            "latitude": offer.get("geo", {}).get("coordinates", {}).get("lat"),
            "longitude": offer.get("geo", {}).get("coordinates", {}).get("lng"),
            "price": offer.get("bargainTerms", {}).get("priceRur"),
            "area": offer.get("totalArea"),
            "floor": offer.get("floorNumber"),
            "floors_total": offer.get("building", {}).get("floorsCount"),
            "description": offer.get("description"),
            "link": f'https://www.cian.ru/rent/commercial/{offer.get("id")}/',
        }
        offers.append(info)
    return offers

# === 6. Основной цикл ===
all_offers = []

for page in tqdm(range(1, 259)):  # 258 страниц
    try:
        data = get_page(page)
        offers = parse_offers(data)
        all_offers.extend(offers)

        # сохраняем каждые 20 страниц
        if page % 20 == 0:
            pd.DataFrame(all_offers).to_csv("cian_offices_temp.csv", index=False, encoding="utf-8-sig")
            print(f"💾 Сохранено промежуточно: {len(all_offers)} объявлений")

        time.sleep(1.5)
    except Exception as e:
        print(f"⚠️ Ошибка на странице {page}: {e}")
        time.sleep(3)

# === 7. Финальное сохранение ===
df = pd.DataFrame(all_offers)
df.to_csv("cian_offices.csv", index=False, encoding="utf-8-sig")
print(f"✅ Готово! Сохранено {len(df)} объявлений")
