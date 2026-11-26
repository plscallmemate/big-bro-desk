# Тест: видит ли GitHub-сервер Яндекс Музыку. Ничего никуда не отправляет, только печатает в лог.
import re, requests
from playwright.sync_api import sync_playwright

ID = "25318156"  # W.Rabbit 99
print("=== 1. IP сервера ===")
try:
    print(requests.get("https://ipinfo.io/json", timeout=15).text)
except Exception as e:
    print("ipinfo error:", e)

print("\n=== 2. API (ожидаем 451, если закрыт по гео) ===")
try:
    r = requests.get(f"https://api.music.yandex.net/artists/{ID}/brief-info", timeout=20,
                     headers={"X-Yandex-Music-Client": "YandexMusicAndroid/24023231", "User-Agent": "Yandex-Music-API", "Accept-Language": "ru"})
    print("status", r.status_code, r.text[:300])
except Exception as e:
    print("api error:", e)

print("\n=== 3. Страница артиста в браузере ===")
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(locale="ru-RU", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    seen = []
    pg.on("response", lambda r: seen.append((r.status, r.url)) if "yandex" in r.url and ("handlers" in r.url or "api" in r.url or "artist" in r.url) else None)
    try:
        resp = pg.goto(f"https://music.yandex.ru/artist/{ID}", wait_until="networkidle", timeout=60000)
        print("status", resp.status if resp else None, "url", pg.url)
    except Exception as e:
        print("goto error:", e)
    pg.wait_for_timeout(5000)
    print("title:", pg.title())
    txt = pg.inner_text("body") if pg.query_selector("body") else ""
    print("captcha:", bool(re.search(r"captcha|робот|не робот", txt + pg.url, re.I)))
    print("text length:", len(txt))
    for line in txt.splitlines():
        if re.search(r"слушател|лайк|нрав|подписч", line, re.I):
            print("LINE:", line.strip()[:200])
    print("--- первые 1200 символов ---")
    print(txt[:1200])
    print("--- запросы страницы (yandex) ---")
    for s, u in seen[:40]:
        print(s, u[:160])
    pg.screenshot(path="shot.png")
    b.close()
