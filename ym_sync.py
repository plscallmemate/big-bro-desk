#!/usr/bin/env python3
"""
Big Bro Desk: синхронизация с Яндекс Музыкой.

Запускай с ВКЛЮЧЁННЫМ российским VPN (иначе Яндекс отвечает 451):
    python3 ym_sync.py

Что делает:
  1. спрашивает у твоего веб-приложения (Apps Script), каких артистов нужно обновить;
  2. по каждому берёт слушателей за месяц, дельту, лайки и (если нет) фото из Яндекс Музыки;
  3. отправляет цифры обратно в веб-приложение, оно раскладывает их по вкладкам таблицы.

Рядом лежит config.json:
    {"webapp_url": "https://script.google.com/macros/s/.../exec", "secret": "тот же пароль, что в меню Big Bro → 1"}

Ничего устанавливать не нужно: только Python 3 из коробки.
"""
import base64
import json
import socket
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Часто VPN плохо ходит по IPv6, и соединение «висит» до таймаута. Идём только по IPv4 (если очень надо: --ipv6)
if "--ipv6" not in sys.argv:
    _orig_gai = socket.getaddrinfo
    socket.getaddrinfo = lambda host, port, family=0, type=0, proto=0, flags=0: _orig_gai(host, port, socket.AF_INET, type, proto, flags)

HERE = os.path.dirname(os.path.abspath(__file__))
YM_API = "https://api.music.yandex.net/artists/{id}/brief-info"
YM_ALBUM = "https://api.music.yandex.net/albums/{id}"
YM_HEADERS = {
    "X-Yandex-Music-Client": "YandexMusicAndroid/24023231",
    "User-Agent": "Yandex-Music-API",
    "Accept-Language": "ru",
}
PAUSE = 0.35          # пауза между запросами, чтобы не злить Яндекс
PHOTO_LIMIT = 45000   # лимит ячейки Google Таблиц ~50 000 символов


def load_config():
    path = os.path.join(HERE, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        sys.exit("Нет файла config.json рядом со скриптом. Создай его (пример в начале ym_sync.py).")
    if not cfg.get("webapp_url") or not cfg.get("secret"):
        sys.exit("В config.json должны быть webapp_url и secret.")
    return cfg


def parse_brief(data):
    """Достаёт нужные поля из ответа brief-info. Возвращает dict или None."""
    res = (data or {}).get("result") or {}
    artist = res.get("artist") or {}
    stats = res.get("stats") or {}
    cover = (artist.get("cover") or {}).get("uri") or ""
    return {
        "release": pick_release(res),
        "listeners": stats.get("lastMonthListeners"),
        "delta": stats.get("lastMonthListenersDelta"),
        "likes": artist.get("likesCount"),
        "cover": cover,
    }


def pick_release(res):
    """Последний релиз: самый свежий по releaseDate среди lastReleases и albums."""
    cands = list(res.get("lastReleases") or []) + list(res.get("albums") or [])
    cands = [a for a in cands if isinstance(a, dict) and a.get("id") is not None]
    if not cands:
        return None
    def when(a):
        return str(a.get("releaseDate") or a.get("year") or "")
    a = max(cands, key=when)
    d = str(a.get("releaseDate") or "")[:10]  # 2026-11-07
    date = ".".join(reversed(d.split("-"))) if len(d) == 10 else str(a.get("year") or "")
    return {"id": a["id"], "title": a.get("title") or "", "date": date, "likes": a.get("likesCount")}


def ym_get(url, binary=False):
    req = urllib.request.Request(url, headers=YM_HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read()
    return body if binary else json.loads(body.decode("utf-8"))


def fetch_brief(artist_id):
    for attempt in range(3):
        try:
            return parse_brief(ym_get(YM_API.format(id=artist_id)))
        except urllib.error.HTTPError as e:
            if e.code == 451:
                sys.exit("\nЯндекс ответил 451: включи российский VPN и запусти скрипт снова.")
            if e.code in (404, 400):
                return None
            time.sleep(1.5 * (attempt + 1))
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return None


def fetch_photo(cover, size="100x100"):
    if not cover:
        return ""
    try:
        raw = ym_get("https://" + cover.replace("%%", size), binary=True)
    except Exception:
        return ""
    data = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    return data if len(data) < PHOTO_LIMIT else ""


def webapp(cfg, params=None, body=None):
    url = cfg["webapp_url"]
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(3):   # Apps Script иногда просыпается долго, пробуем до трёх раз
        t0 = time.time()
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as r:  # Apps Script отвечает редиректом, urllib идёт по нему сам
                out = json.loads(r.read().decode("utf-8"))
            break
        except (socket.timeout, TimeoutError):
            last = "нет ответа за %d сек" % (time.time() - t0)
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
        except urllib.error.URLError as e:
            last = "сеть: %s" % e.reason
        except ValueError:
            last = "ответ не похож на json (возможно, старая версия скрипта или не тот адрес)"
        print("  попытка %d не вышла (%s)" % (attempt + 1, last))
        time.sleep(3)
    else:
        sys.exit("\nВеб-приложение Apps Script не отвечает: " + str(last) +
                 "\nПроверь: 1) VPN включён и Google открывается; 2) адрес в config.json тот же, что в Deploy → Manage deployments;"
                 "\n3) в Apps Script слева «Executions» (Выполнения): видно ли там запуск doGet и сколько он шёл.")
    if out.get("error"):
        sys.exit("Веб-приложение вернуло ошибку: " + str(out["error"]))
    return out


def check(cfg):
    """python3 ym_sync.py --check: показывает, до какого сайта не достучаться (Google, редирект Google или Яндекс)."""
    tests = [
        ("Google Apps Script (script.google.com)", "script.google.com", 443),
        ("Google, куда Apps Script перекидывает ответ (script.googleusercontent.com)", "script.googleusercontent.com", 443),
        ("Яндекс Музыка API (api.music.yandex.net)", "api.music.yandex.net", 443),
    ]
    for name, host, port in tests:
        t0 = time.time()
        try:
            ip = socket.getaddrinfo(host, port)[0][4][0]
            s = socket.create_connection((host, port), timeout=15)
            s.close()
            print("OK    %-75s %s, %.1f сек" % (name, ip, time.time() - t0))
        except Exception as e:
            print("FAIL  %-75s %s" % (name, e))
    try:
        req = urllib.request.Request(YM_API.format(id="25318156"), headers=YM_HEADERS)
        urllib.request.urlopen(req, timeout=20)
        print("OK    Яндекс отдаёт данные (российский IP, VPN работает)")
    except urllib.error.HTTPError as e:
        print("Яндекс ответил HTTP %s%s" % (e.code, " (451: нужен российский VPN)" if e.code == 451 else ""))
    except Exception as e:
        print("FAIL  запрос к Яндексу: %s" % e)
    try:
        t0 = time.time()
        webapp(cfg, params={"action": "targets", "secret": cfg["secret"]})
        print("OK    таблица ответила за %.1f сек" % (time.time() - t0))
    except SystemExit as e:
        print("FAIL  таблица не ответила")


def main():
    cfg = load_config()
    if "--check" in sys.argv:
        check(cfg)
        return
    print("Спрашиваю у таблицы, кого обновлять…")
    t = webapp(cfg, params={"action": "targets", "secret": cfg["secret"]})
    ids, need_photo, big_photo = t.get("ids", []), set(t.get("needPhoto", [])), set(t.get("bigPhoto", []))
    if not ids:
        sys.exit("В таблице нет ни одной ссылки вида music.yandex.ru/artist/число.")
    print("Артистов: %d, фото нужно: %d" % (len(ids), len(need_photo)))

    briefs, bad, no_release = {}, [], []
    for i, aid in enumerate(ids, 1):
        b = fetch_brief(aid)
        if not b or b["listeners"] is None and b["likes"] is None:
            bad.append(aid)
        else:
            cover = b.pop("cover")
            rel = b.get("release")
            if rel and rel.get("likes") is None:   # в brief-info лайков альбома может не быть, спрашиваем отдельно
                try:
                    alb = ym_get(YM_ALBUM.format(id=rel["id"]))
                    rel["likes"] = ((alb or {}).get("result") or [{}])[0].get("likesCount")
                except Exception:
                    pass
            if rel is None:
                no_release.append(aid)
            if aid in need_photo:
                p = fetch_photo(cover, "200x200" if aid in big_photo else "100x100")
                if not p and aid in big_photo:
                    p = fetch_photo(cover, "100x100")
                if p:
                    b["photo"] = p
            briefs[aid] = b
        print("\r%d / %d" % (i, len(ids)), end="", flush=True)
        time.sleep(PAUSE)
    print()

    if not briefs:
        sys.exit("Не получил ни одного ответа от Яндекса. Проверь VPN.")
    print("Отправляю в таблицу…")
    out = {}
    CH = 40   # маленькими пачками: большой пост через VPN чаще рвётся
    items = list(briefs.items())
    for i in range(0, len(items), CH):
        part = dict(items[i:i + CH])
        print("  пачка %d–%d из %d" % (i + 1, i + len(part), len(items)))
        out = webapp(cfg, body={"secret": cfg["secret"], "briefs": part})
        if out.get("log"):
            print(out["log"])
    if no_release:
        print("Без последнего релиза (нет в ответе Яндекса): %d из %d" % (len(no_release), len(briefs)))
    if bad:
        print("Не удалось получить данные для id: " + ", ".join(bad[:20]) + (" …" if len(bad) > 20 else ""))
    print("Готово.")


if __name__ == "__main__":
    main()
