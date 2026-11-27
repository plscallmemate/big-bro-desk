#!/usr/bin/env python3
"""
Big Bro Desk: смотрит твои чаты в Telegram и сообщает в таблицу, с кем из артистов давно не было контакта
и кто ждёт ответа.

Что уходит в таблицу: ТОЛЬКО даты, где был контакт (личка или название группы) и кто писал последним.
Тексты сообщений никуда не отправляются и даже не читаются дальше этого скрипта.

Первый раз (войти в свой Telegram, код придёт в приложение):
    .venv/bin/python tg_watch.py --login
Дальше запускается сам раз в 30 минут (install_tgwatch.sh), руками:
    .venv/bin/python tg_watch.py

Нужно в config.json рядом (кроме webapp_url и secret, которые уже есть):
    "tg_api_id": 1234567, "tg_api_hash": "..."      ← с my.telegram.org → API development tools
Сессия Telegram сохраняется в tg_watch.session: это ключ к твоему аккаунту, никому не отдавай и в гит не клади.

Как артист связывается с чатами: по его @юзернейму из Artists (колонки «ТГ» и «Доп. контакты»):
  • личка: твоя переписка с этим юзернеймом;
  • группы: твои группы, где этот юзернейм есть среди участников.
Последний контакт = самое свежее сообщение из ВСЕХ его чатов (переписка в личке закрывает тишину в группе).
«Ждёт ответа» = последнее в чате написал артист, а после него никто не ответил. Не считается:
твоя реакция на его сообщение, стикер, «спасибо / ок / договорились», одни эмодзи (проверка на маке, текст не уходит).
"""
import asyncio
import json
import os
import stat
import sys
import time

from ym_sync import load_config, webapp   # тот же config.json и тот же способ ходить в Apps Script

try:
    from telethon import TelegramClient
    from telethon.tl.types import User
except ImportError:
    sys.exit("Нет библиотеки telethon. Поставь: python3 -m venv .venv && .venv/bin/pip install telethon")

HERE = os.path.dirname(os.path.abspath(__file__))
SESSION = os.path.join(HERE, "tg_watch")             # Telethon сам допишет .session
CACHE = os.path.join(HERE, "tg_watch_cache.json")     # участники групп, чтобы не дёргать Telegram каждые 30 минут
MEMBERS_TTL = 12 * 3600       # участников группы перечитываем раз в 12 часов
MAX_GROUP = 300               # большие группы (каналы-болталки) пропускаем, рабочие чаты маленькие
GROUP_MSGS = 40               # сколько последних сообщений группы смотреть, чтобы понять, ждёт ли артист ответа
DM_MSGS = 30


def ms(dt):
    return int(dt.timestamp() * 1000) if dt else None


def handles_of(entity):
    out = set()
    if getattr(entity, "username", None):
        out.add(entity.username.lower())
    for u in getattr(entity, "usernames", None) or []:   # коллекционные юзернеймы
        if getattr(u, "username", None):
            out.add(u.username.lower())
    return out


def load_cache():
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_cache(c):
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(c, f)
    os.chmod(CACHE, stat.S_IRUSR | stat.S_IWUSR)


# Сообщения, на которые отвечать не нужно. Проверка идёт тут же, на маке: текст никуда не уходит.
ACK = set("""спасибо спасиб пасиб пасибо спс спсб благодарю благодарим сенкс thanks thank thx ty
ок окей окк ok okay ага угу пон понял поняла поняли принял приняла принято ясно ясненько хорошо хорош добро
договорились забились отлично супер круто класс кайф топ огонь пушка имба бомба норм нормально збс красава красавчик
лады ладно давай го на связи до связи пока спокойной ночи доброй""".split())
FILLER = set("""большое огромное бро братан брат братик тебе вам тебя вас ещё еще раз и очень всё все ну да
спасибочки ))) )) ) пасибки""".split())


def my_reaction(m):
    """Я поставил реакцию на это сообщение (значит, видел и ответил)."""
    r = getattr(m, "reactions", None)
    return bool(r and any(getattr(x, "chosen_order", None) is not None for x in (getattr(r, "results", None) or [])))


def needs_reply(m):
    """Грубо, но без нейросетей: стикеры, гифки, «спасибо», «ок, договорились», одни эмодзи = ответ не нужен.
    Вопрос, файл, голосовое, ссылка и всё длинное = нужен."""
    if getattr(m, "sticker", None) or getattr(m, "gif", None) or getattr(m, "dice", None):
        return False
    if getattr(m, "media", None) and not getattr(m, "web_preview", None):
        return True          # трек, фото, голосовое, файл: такое обычно ждёт реакции
    t = (getattr(m, "message", None) or "").strip().lower()
    if not t:
        return False
    if "?" in t or "http" in t or len(t) > 60:
        return True
    words = "".join(ch if ch.isalnum() or ch in " )" else " " for ch in t).split()
    if not words:
        return False         # одни эмодзи / знаки
    return not all(w in ACK or w in FILLER for w in words)


def waiting_since(msgs, is_artist):
    """msgs: от новых к старым. Ищет неотвеченные сообщения артиста в конце чата:
    - пока идут сообщения артиста, запоминает самое раннее, на которое нужен ответ;
    - моя реакция на сообщение артиста = ответ (дальше в прошлое не смотрим);
    - сообщение от кого-то другого = ответ.
    Вернёт время первого неотвеченного сообщения или None."""
    since = None
    for m in msgs:
        if getattr(m, "action", None):        # служебные («вступил в группу», «закрепил») не считаем
            continue
        if not is_artist(m) or my_reaction(m):
            break
        if needs_reply(m):
            since = m.date
    return since


async def members(client, dialog, cache, now):
    """{юзернейм: id} участников группы (из кэша, если свежий)."""
    key = str(dialog.id)
    c = cache.get(key)
    if c and now - c.get("at", 0) < MEMBERS_TTL:
        return c["m"]
    m = {}
    try:
        async for u in client.iter_participants(dialog.entity, limit=MAX_GROUP):
            for h in handles_of(u):
                m[h] = u.id
    except Exception as e:   # скрытый список участников и т.п.: свяжем по тем, кто писал
        print("  не вижу участников «%s» (%s), смотрю по авторам сообщений" % (dialog.name, type(e).__name__))
        async for msg in client.iter_messages(dialog.entity, limit=200):
            s = msg.sender
            if isinstance(s, User):
                for h in handles_of(s):
                    m[h] = s.id
    cache[key] = {"at": now, "m": m}
    return m


async def run(login):
    cfg = load_config()
    if not cfg.get("tg_api_id") or not cfg.get("tg_api_hash"):
        sys.exit("В config.json нет tg_api_id и tg_api_hash (их выдают на my.telegram.org → API development tools).")

    client = TelegramClient(SESSION, int(cfg["tg_api_id"]), cfg["tg_api_hash"], flood_sleep_threshold=120)
    if login:
        await client.start()        # спросит телефон, код из Telegram и облачный пароль, если он есть
    else:
        await client.connect()
        if not await client.is_user_authorized():
            sys.exit("Не залогинен в Telegram. Один раз запусти: .venv/bin/python tg_watch.py --login")
    if os.path.exists(SESSION + ".session"):
        os.chmod(SESSION + ".session", stat.S_IRUSR | stat.S_IWUSR)

    async with client:
        me = await client.get_me()
        print("Telegram: вошёл как %s" % (me.first_name or me.username or me.id))
        if login:
            print("Сессия сохранена. Дальше скрипт будет работать сам.")

        t = webapp(cfg, params={"secret": cfg["secret"], "action": "chatTargets"})
        if not t or t.get("error"):
            sys.exit("Apps Script не отдал список артистов: %s (залил новую версию big-bro-collector.gs?)" % (t or {}).get("error"))
        artists = [a for a in t.get("artists", []) if a.get("handles")]
        by_handle = {}
        for a in artists:
            for h in a["handles"]:
                by_handle.setdefault(h.lower(), []).append(a["name"])
        print("Артистов с юзернеймом: %d" % len(artists))

        now = time.time()
        cache = load_cache()
        dms = {}        # юзернейм -> dialog
        groups = []     # (dialog, {юзернейм: id})
        async for d in client.iter_dialogs(archived=None):
            e = d.entity
            if d.is_user:
                if isinstance(e, User) and not e.bot and not e.is_self:
                    for h in handles_of(e):
                        if h in by_handle:
                            dms[h] = d
            elif d.is_group:
                cnt = getattr(e, "participants_count", None)
                if cnt and cnt > MAX_GROUP:
                    continue
                groups.append(d)

        # в группах ищем только тех, у кого есть юзернейм из Artists
        group_members = []
        for d in groups:
            m = await members(client, d, cache, now)
            hit = {h: uid for h, uid in m.items() if h in by_handle}
            if hit:
                group_members.append((d, hit))
        save_cache(cache)

        rows = {}       # имя артиста -> сводка
        def put(name, when, where, frm, wait):
            r = rows.setdefault(name, {"artist": name, "last_ts": None, "last_where": "", "last_from": "", "wait_ts": None, "wait_where": "", "chats": 0})
            r["chats"] += 1
            if when and (r["last_ts"] is None or when > r["last_ts"]):
                r["last_ts"], r["last_where"], r["last_from"] = when, where, frm
            if wait and (r["wait_ts"] is None or wait < r["wait_ts"]):
                r["wait_ts"], r["wait_where"] = wait, where

        for h, d in dms.items():
            last = d.message
            wait = None
            if last is not None and not last.out:
                msgs = [m async for m in client.iter_messages(d.entity, limit=DM_MSGS)]
                wait = ms(waiting_since(msgs, lambda m: not m.out))
            for name in by_handle[h]:
                put(name, ms(last.date) if last else None, "личка", "me" if last is not None and last.out else "artist", wait)

        for d, hit in group_members:
            msgs = [m async for m in client.iter_messages(d.entity, limit=GROUP_MSGS)]
            last = next((m for m in msgs if not getattr(m, "action", None)), None) or d.message
            for h, uid in hit.items():
                w = ms(waiting_since(msgs, lambda m, uid=uid: m.sender_id == uid))
                frm = "" if last is None else ("me" if last.out else "artist" if last.sender_id == uid else "team")
                for name in by_handle[h]:
                    put(name, ms(last.date) if last else None, d.name, frm, w)

        found = set(rows)
        missing = sorted(a["name"] for a in artists if a["name"] not in found)
        print("Нашёл чаты у %d артистов, не нашёл у %d" % (len(found), len(missing)))
        if missing:
            print("  без чата: " + ", ".join(missing[:30]) + (" …" if len(missing) > 30 else ""))

        out = webapp(cfg, body={"secret": cfg["secret"], "chats": {"owner_id": str(me.id), "rows": list(rows.values())}})
        if not out or out.get("error"):
            sys.exit("Apps Script не принял: %s" % (out or {}).get("error"))
        print(out.get("log", "готово"))


if __name__ == "__main__":
    asyncio.run(run("--login" in sys.argv))
