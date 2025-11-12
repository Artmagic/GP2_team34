import time
import json
import csv
import os
import logging
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import InvalidSessionIdException

try:
    from webdriver_manager.chrome import ChromeDriverManager
    WD_MANAGER_AVAILABLE = True
except Exception:
    WD_MANAGER_AVAILABLE = False


COOKIES_JSON = "cookies.json"
OUTPUT_CSV = "cian_cat_metro.csv"
HEADLESS = False
WAIT_TIMEOUT = 15
MAX_SCROLLS = 3
SCROLL_PAUSE = 1.0
MAX_METRO_ID = 500
MAX_PAGES = 100
ATTACH_DEBUGGER = False
DEBUGGER_ADDRESS = "127.0.0.1:9222"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

BASE_URL = "https://www.cian.ru/cat.php"
BASE_PARAMS = (
    "deal_type=rent"
    "&engine_version=2"
    "&foot_min=25"
    "&offer_type=offices"
    "&office_type[0]=5"
    "&only_foot=2"
    "&region=1"
)

CARD_XPATHS = [
    "//article[contains(@class,'serp-item')]",
    "//div[contains(@data-name,'Card') or contains(@data-mark,'SerpCard')]"
]


def create_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if HEADLESS:
        opts.add_argument("--headless=new")
    if ATTACH_DEBUGGER:
        opts.add_experimental_option("debuggerAddress", DEBUGGER_ADDRESS)
    service = Service(ChromeDriverManager().install()) if WD_MANAGER_AVAILABLE else Service()
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_window_size(1280, 900)
    return driver


def load_cookies(driver: webdriver.Chrome):
    if not os.path.exists(COOKIES_JSON):
        return
    with open(COOKIES_JSON, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    for c in cookies:
        try:
            driver.add_cookie({
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".cian.ru")
            })
        except Exception:
            continue


def restart_driver(driver: Optional[webdriver.Chrome]) -> webdriver.Chrome:
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    driver = create_driver()
    driver.get("https://www.cian.ru/")
    time.sleep(1)
    load_cookies(driver)
    return driver


def safe_get_text(el, xpaths):
    for xp in xpaths:
        try:
            t = el.find_element(By.XPATH, xp).text.strip()
            if t:
                return t
        except Exception:
            continue
    return ""


def extract_card_data(card, metro_id) -> Dict:
    title = safe_get_text(card, [
        ".//a[contains(@class,'Link_link_name') or contains(@class,'title')]",
        ".//h3"
    ])
    price = safe_get_text(card, [
        ".//span[contains(@class,'price-text')]",
        ".//div[contains(@class,'price')]",
        ".//*[contains(text(),'₽')]"
    ])
    address = safe_get_text(card, [
        ".//div[contains(@data-name,'Geo')]",
        ".//div[contains(@class,'address')]",
    ])
    link = ""
    latitude = ""
    longitude = ""

    try:
        a = card.find_element(By.XPATH, ".//a[@href and contains(@href,'cian.ru')]")
        link = a.get_attribute("href")
    except Exception:
        pass

    try:
        coords_el = card.find_element(By.XPATH, ".//*[@data-coords]")
        coords_str = coords_el.get_attribute("data-coords")
        if coords_str and "," in coords_str:
            latitude, longitude = coords_str.split(",")
    except Exception:
        pass

    if not latitude or not longitude:
        try:
            map_a = card.find_element(By.XPATH, ".//a[contains(@href,'maps.cian.ru')]")
            href = map_a.get_attribute("href")
            if "ll=" in href:
                ll_part = href.split("ll=")[1].split("&")[0]
                lon, lat = ll_part.split("%2C")
                latitude, longitude = lat, lon
        except Exception:
            pass

    return {
        "metro_id": metro_id,
        "title": title,
        "price": price,
        "address": address,
        "latitude": latitude.strip(),
        "longitude": longitude.strip(),
        "link": link
    }


def get_cards(driver):
    for _ in range(MAX_SCROLLS):
        driver.execute_script("window.scrollBy(0, document.body.scrollHeight * 0.8);")
        time.sleep(SCROLL_PAUSE)
    for xp in CARD_XPATHS:
        cards = driver.find_elements(By.XPATH, xp)
        if cards:
            return cards
    return []


def append_to_csv(data: List[Dict], filename: str):
    if not data:
        return
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        if not file_exists:
            writer.writeheader()
        writer.writerows(data)


def parse_metro(driver, metro_id: int):
    seen_links = set()
    empty_pages_in_row = 0
    repeated_pages_in_row = 0

    for page in range(1, MAX_PAGES + 1):
        url = f"{BASE_URL}?{BASE_PARAMS}&metro[0]={metro_id}&p={page}"
        logging.info(f"🚇 metro={metro_id} | страница {page}")

        try:
            driver.get(url)
        except InvalidSessionIdException:
            logging.warning("Потеряна сессия — перезапуск Chrome...")
            driver = restart_driver(driver)
            driver.get(url)

        try:
            WebDriverWait(driver, WAIT_TIMEOUT).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
        except Exception:
            logging.warning("body not loaded")

        cards = get_cards(driver)
        count_cards = len(cards)
        logging.info(f"🔎 Найдено {count_cards} карточек")

        if count_cards == 0:
            logging.info(f"metro={metro_id}: страница {page} пуста — стоп.")
            break

        page_data = []
        for card in cards:
            try:
                d = extract_card_data(card, metro_id)
                if d["link"] and d["link"] not in seen_links:
                    seen_links.add(d["link"])
                    page_data.append(d)
            except Exception:
                continue

        if len(page_data) == 0:
            repeated_pages_in_row += 1
            logging.info(f"metro={metro_id}: нет новых объявлений на странице ({repeated_pages_in_row} раз подряд)")
            if repeated_pages_in_row >= 1:
                logging.info(f"metro={metro_id}: новые объявления закончились — переход к следующему метро.")
                break
        else:
            repeated_pages_in_row = 0

        append_to_csv(page_data, OUTPUT_CSV)
        logging.info(f"metro={metro_id}: добавлено {len(page_data)} объявлений (всего {len(seen_links)})")

        if count_cards < 10:
            logging.info(f"metro={metro_id}: мало карточек ({count_cards}) — стоп.")
            break

        time.sleep(1.5)

    return driver


driver = restart_driver(None)
for metro_id in range(1, 400):
    logging.info(f"Станция metro_id={metro_id}")
    try:
        driver = parse_metro(driver, metro_id)
    except Exception as e:
        logging.error(f"Ошибка на metro_id={metro_id}: {e}")
        driver = restart_driver(driver)

logging.info("Парсинг завершён.")