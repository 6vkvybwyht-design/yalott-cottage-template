#!/usr/bin/env python3
"""Команди для роботи із сайтом. Запуск із папки проєкту:

    python manage.py anketa         повідомлення-опитувальник для клієнта (скопіювати в WhatsApp / Viber)
    python manage.py from-chat      відповіді клієнта з чату → config/site.yaml + список, чого бракує
    python manage.py new-client     майстер: питає назву, контакти, об'єкти, ціни → config/site.yaml
    python manage.py validate       перевірити конфіг (зрозумілі помилки українською)
    python manage.py seed           залити конфіг у базу (безпечно запускати повторно)
    python manage.py photos         обробити фото з media/ → static/media/
    python manage.py check          чи все готово до деплою
    python manage.py demo-link      посилання на демо-версію з терміном дії (demo.enabled у конфігу)
    python manage.py demo-find ФАЙЛ чи є в збереженій сторінці / тексті позначка нашого демо
    python manage.py set-password   змінити пароль адмінки

Інший конфіг: додайте  --config config/examples/ramshill.yaml  (або змінну SITE_CONFIG).
"""

import argparse
import getpass
import json
import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ["YALOTT_NO_APP"] = "1"   # команди не піднімають вебзастосунок

import site_config  # noqa: E402

OK, WARN, FAIL = "  ✓", "  ⚠", "  ✗"


def _path(args):
    path = getattr(args, "config", None) or site_config.config_path()
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


def _rel(path):
    return os.path.relpath(path, BASE_DIR)


def _load_env():
    import app as app_module   # читає .env (YALOTT_NO_APP=1 — сам сайт не створюється)
    return app_module


def _db_path(cfg):
    _load_env()
    instance = os.environ.get("INSTANCE_PATH") or os.path.join(BASE_DIR, "instance")
    return os.environ.get("DATABASE_PATH") or os.path.join(instance, f"{cfg.key}.db")


def _load(args):
    """Конфіг або зрозумілий вихід із помилками."""
    try:
        return site_config.load(_path(args))
    except site_config.ConfigError as exc:
        print(f"\nКонфіг {_rel(exc.path)} містить помилки:\n")
        for e in exc.errors:
            print(f"{FAIL} {e}")
        print("\nВиправте їх і запустіть: python manage.py validate\n")
        sys.exit(1)


# ---------- validate ----------

def cmd_validate(args):
    path = _path(args)
    print(f"\nПеревіряю {_rel(path)} …\n")
    try:
        raw = site_config.read_yaml(path)
    except site_config.ConfigError as exc:
        for e in exc.errors:
            print(f"{FAIL} {e}")
        print()
        return 1
    errors, warnings = site_config.validate(raw, static_dir=os.path.join(BASE_DIR, "static"),
                                            media=site_config.media_root(path))
    for e in errors:
        print(f"{FAIL} {e}")
    for w in warnings:
        print(f"{WARN} {w}")
    if errors:
        print(f"\nПомилок: {len(errors)}. Виправте їх — із таким конфігом сайт не запуститься.\n")
        return 1
    cfg = site_config.SiteConfig(raw, path)
    print(f"{OK} Конфіг правильний: «{cfg.brand['full_name']}», тема {cfg.brand['theme']}, "
          f"об'єктів — {len(cfg.objects)}, послуг — {len(cfg.extras)}, сезонів — {len(raw.get('seasons') or [])}.")
    if warnings:
        print(f"\nПопереджень: {len(warnings)} — сайт працюватиме, але варто переглянути.")
    print()
    return 0


# ---------- seed ----------

def cmd_seed(args):
    import database as db_
    cfg = _load(args)
    path = _db_path(cfg)
    if args.reset and not args.yes:
        print("\nУВАГА: --reset замінить ціни й параметри об'єктів, ціни послуг і ВСІ сезони значеннями з конфігу.")
        print("Правки, зроблені власником в адмінці, буде втрачено. Бронювання не зміняться.")
        if input("Продовжити? Напишіть «так»: ").strip().lower() not in ("так", "yes", "y"):
            print("Скасовано.")
            return 1
    os.makedirs(os.path.dirname(path), exist_ok=True)
    report = db_.init_db(path, cfg, with_demo=False)      # таблиці + те, чого в базі бракує
    conn = db_.connect(path)
    try:
        if args.reset:
            report = db_.seed(conn, cfg, reset=True)
        print(f"\nБаза: {path}\nКонфіг: {_rel(cfg.path)}\n")
        for title, key, mark in (("Додано з конфігу", "added", "+"), ("Оновлено з конфігу", "updated", "~"),
                                 ("Уже є в базі — не чіпаю (діють значення з адмінки)", "kept", "="),
                                 ("Пропущено", "skipped", "!")):
            if report[key]:
                print(f"{title}:")
                for line in report[key]:
                    print(f"  {mark} {line}")
        if not report["added"] and not report["updated"]:
            print("\nНічого нового — база вже відповідає конфігу. Повторний запуск безпечний.")
        if args.clear_demo:
            blocked, bookings = db_.clear_demo(conn)
            print(f"\nДемо-дані прибрано: закритих ночей — {blocked}, демо-заявок — {bookings}.")
        elif args.demo:
            from datetime import date
            added = db_.seed_demo(conn, cfg, date.today())
            print("\nДемо-зайнятість і демо-заявки додано." if added
                  else "\nДемо-дані не додано: вони вже були або в базі є справжні бронювання.")
    finally:
        conn.close()
    print()
    return 0


# ---------- photos ----------

def cmd_photos(args):
    import photos
    cfg = _load(args)
    src = os.path.join(BASE_DIR, cfg.media_root)
    print(f"\nОбробляю фото: {cfg.media_root}/ → static/{cfg.media_root}/\n")
    if not photos.folders(src):
        print(f"{WARN} У {cfg.media_root}/ немає папок із фото. Очікую:")
        for o in cfg.objects:
            print(f"      {cfg.media_root}/objects/{o['key']}/   — {o['name']}")
        print(f"      {cfg.media_root}/hero/, {cfg.media_root}/gallery/, {cfg.media_root}/extras/\n")
        return 0
    try:
        stats = photos.run(cfg.media_root, force=args.force, enhance=args.enhance)
    except RuntimeError as exc:
        print(f"{FAIL} {exc}\n")
        return 1
    print(f"\n{OK} Оброблено: {stats['done']}, без змін: {stats['skipped']}.")
    for name, error in stats["failed"]:
        print(f"{FAIL} {name}: не вдалося прочитати ({error})")
    known = {o["key"] for o in cfg.objects}
    objects_dir = os.path.join(src, "objects")
    for d in sorted(os.listdir(objects_dir)) if os.path.isdir(objects_dir) else []:
        if os.path.isdir(os.path.join(objects_dir, d)) and d not in known:
            print(f"{WARN} Папка objects/{d}/ не відповідає жодному об'єкту в конфігу (є: {', '.join(sorted(known))})")
    print()
    return 1 if stats["failed"] else 0


# ---------- check ----------

def cmd_check(args):
    import gallery
    import photos
    problems, notes = [], []

    def ok(text):
        print(f"{OK} {text}")

    def bad(text):
        problems.append(text)
        print(f"{FAIL} {text}")

    def note(text):
        notes.append(text)
        print(f"{WARN} {text}")

    path = _path(args)
    print(f"\nПеревірка готовності до деплою ({_rel(path)})\n\nКонфіг")
    cfg = None
    try:
        raw = site_config.read_yaml(path)
        errors, _ = site_config.validate(raw, check_photos=False)
        if errors:
            for e in errors:
                bad(e)
        else:
            cfg = site_config.SiteConfig(raw, path)
            ok(f"конфіг правильний: «{cfg.brand['full_name']}», об'єктів — {len(cfg.objects)}")
            text = open(path, encoding="utf-8").read()
            if "ЗАМІНИТИ" in text or "000 00 00" in text or "0000000" in text:
                bad("у конфігу лишились заглушки («ЗАМІНИТИ» або телефон із нулів) — впишіть справжні дані")
            if cfg.demo["enabled"]:
                note(f"сайт у ДЕМО-режимі (demo.enabled: true, домен {cfg.demo['domain']}): водяні знаки, noindex, "
                     f"доступ лише за посиланням. Для здачі клієнту — demo.enabled: false")
            pending = text.count("ПЕРЕВІРИТИ:")
            if pending:
                note(f"у конфігу {pending} позначок «ПЕРЕВІРИТИ» з розбору чату — перегляньте й приберіть")
    except site_config.ConfigError as exc:
        for e in exc.errors:
            bad(e)

    print("\nФайл .env")
    env_file = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_file):
        bad("немає файлу .env. Створіть: cp .env.example .env — і заповніть")
    _load_env()
    env = lambda k: os.environ.get(k, "").strip()  # noqa: E731
    import security
    try:
        security.require_secret_key(env("SECRET_KEY"))
        if security.weak_secret_key(env("SECRET_KEY")):
            bad("SECRET_KEY коротший за 32 символи. Згенеруйте: python -c \"import secrets; print(secrets.token_hex(32))\"")
        else:
            ok("SECRET_KEY задано")
    except security.SecurityConfigError:
        bad("SECRET_KEY не задано — без нього сайт не запуститься. "
            "Згенеруйте: python -c \"import secrets; print(secrets.token_hex(32))\"")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if len(password) >= 8 and password not in ("demo2026", "password", "12345678"):
        ok("ADMIN_PASSWORD задано")
    else:
        bad("ADMIN_PASSWORD не задано або він слабкий (потрібно від 8 символів) — інакше в адмінку пустить демо-пароль")
    if env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"):
        ok("Telegram налаштовано (перевірте кнопкою «Надіслати тестове сповіщення» в адмінці)")
    else:
        bad("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не задано — власник не отримає сповіщень про бронювання")
    if env("DEMO_DATA").lower() in ("1", "true", "yes", "on", "так"):
        note("DEMO_DATA=1 — у новій базі з'являться демо-броні. Для робочого сайту поставте 0 "
             "(прибрати наявні: python manage.py seed --clear-demo)")
    else:
        ok("DEMO_DATA вимкнено")
    if env("SESSION_COOKIE_SECURE").lower() in ("0", "false", "no", "off", "ні"):
        bad("SESSION_COOKIE_SECURE=0 — cookie входу піде й незахищеним каналом. На сервері приберіть рядок або поставте 1")
    if env("BEHIND_PROXY").lower() in ("0", "false", "no", "off", "ні"):
        note("BEHIND_PROXY=0 — за Caddy чи nginx поставте 1, інакше ліміти входу й заявок рахуватимуть IP вебсервера")

    if cfg:
        print("\nФото")
        pending = photos.pending(cfg.media_root)
        if pending:
            note(f"не оброблено оригіналів: {len(pending)} (напр. {pending[0]}). Запустіть: python manage.py photos")
        for o in cfg.objects:
            n = len(gallery.list_photos(o["folder"]))
            if n:
                ok(f"«{o['name']}»: фото — {n}")
            else:
                bad(f"«{o['name']}»: немає фото. Покладіть їх у {cfg.media_root}/objects/{o['key']}/ "
                    f"і запустіть: python manage.py photos")
        if gallery.first(cfg.media("hero")):
            ok("фото банера є")
        else:
            note(f"немає фото банера ({cfg.media_root}/hero/) — буде обкладинка першого об'єкта або фон теми")
        if cfg.sections["gallery"] and not gallery.list_photos(cfg.media("gallery")):
            note(f"блок «Галерея» увімкнено, але {cfg.media_root}/gallery/ порожня — блок не покажеться")
        for key in ("logo", "favicon"):
            if cfg.brand[key] and not gallery.exists(cfg.brand[key]):
                bad(f"brand → {key}: файлу static/{cfg.brand[key]} немає")

        print("\nБаза даних")
        import database as db_
        db_path = _db_path(cfg)
        try:
            db_.init_db(db_path, cfg, with_demo=False)
            conn = db_.connect(db_path)
            demo = conn.execute("SELECT COUNT(*) FROM bookings WHERE source = 'demo'").fetchone()[0] + \
                conn.execute("SELECT COUNT(*) FROM blocked_nights WHERE source = 'demo'").fetchone()[0]
            conn.close()
            ok(f"база доступна для запису: {db_path}")
            import stat as stat_
            for target, need, what in ((db_path, 0o600, "база"), (os.path.dirname(db_path), 0o700, "тека бази")):
                mode = stat_.S_IMODE(os.stat(target).st_mode)
                if mode & ~need:
                    bad(f"{what}: права {mode:o}, мають бути {need:o} — chmod {need:o} {target}")
                else:
                    ok(f"{what}: права {mode:o}")
            if demo:
                note("у базі є демо-дані. Перед запуском для гостей: python manage.py seed --clear-demo")
        except Exception as exc:
            bad(f"база {db_path}: {exc}")

    print()
    if problems:
        print(f"НЕ ГОТОВО: проблем — {len(problems)}" + (f", зауважень — {len(notes)}" if notes else "") + ".\n")
        return 1
    print("ГОТОВО до деплою." + (f" Зауважень: {len(notes)}." if notes else "") + " Далі — DEPLOY.md.\n")
    return 0


# ---------- set-password ----------

def cmd_set_password(args):
    import database as db_
    cfg = _load(args)
    path = _db_path(cfg)
    db_.init_db(path, cfg, with_demo=False)
    password = getpass.getpass("Новий пароль (від 8 символів): ")
    if len(password) < 8:
        print("Пароль закороткий.")
        return 1
    if getpass.getpass("Ще раз: ") != password:
        print("Паролі не збігаються.")
        return 1
    db_.set_password(path, args.username, password)
    print(f"Пароль збережено для «{args.username}».")
    return 0


# ---------- new-client ----------

TRANSLIT = dict(zip("абвгґдезийклмнопрстуфыэ", "abvhgdezyiklmnoprstufye"))
TRANSLIT.update({"є": "ie", "ж": "zh", "і": "i", "ї": "i", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
                 "ю": "iu", "я": "ia", "ь": "", "ъ": "", "'": "", "ʼ": "", "’": ""})


def slugify(text):
    """«Великий котедж» → velykyi-kotedzh."""
    out = "".join(TRANSLIT.get(ch, ch) for ch in text.lower())
    return re.sub(r"[^a-z0-9]+", "-", out).strip("-")[:40]


def ask(question, default=None, check=None, hint=""):
    """Питання в терміналі. Enter — значення за замовчуванням. check(value) повертає текст помилки або None."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            value = input(f"{question}{suffix}: ").strip()
        except EOFError:
            print("\nВведення перервано.")
            sys.exit(1)
        if not value and default is not None:
            value = str(default)
        error = check(value) if check else None
        if not error:
            return value
        print(f"   ↳ {error}{(' ' + hint) if hint else ''}")


def ask_int(question, default=None, low=0, high=1_000_000):
    def check(v):
        if not re.fullmatch(r"\d+", v.replace(" ", "")):
            return "Потрібне ціле число, напр. 4500."
        if not low <= int(v.replace(" ", "")) <= high:
            return f"Число від {low} до {high}."
    return int(ask(question, default, check).replace(" ", ""))


def ask_yes(question, default=True):
    value = ask(f"{question} (так/ні)", "так" if default else "ні",
                lambda v: None if v.lower() in ("так", "т", "ні", "н", "y", "n", "yes", "no") else "Відповідь: так або ні.")
    return value.lower() in ("так", "т", "y", "yes")


def _required(v):
    return None if v else "Це поле обов'язкове."


def _phone(v):
    return None if 9 <= len(re.sub(r"\D", "", v)) <= 15 else "Не схоже на номер. Приклад: +380 67 123 45 67"


def _time(v):
    return None if site_config.TIME_RE.match(v) else "Час у форматі ГГ:ХХ, напр. 15:00"


def q(value):
    """Рядок у подвійних лапках для YAML."""
    return json.dumps(str(value), ensure_ascii=False)


def render_config(d, source="python manage.py new-client"):
    """Дані майстра чи розбору чату → текст config/site.yaml з коментарями українською.

    Необов'язкове d["_flags"] / o["_flags"]: {поле: «ПЕРЕВІРИТИ: …» або «ЗАМІНИТИ: …»} — коментар біля поля.
    «ЗАМІНИТИ» не пропустить manage.py check, тож сайт із заглушкою не потрапить до гостей.
    d["_header"] — рядки коментаря на початку файлу; d["_unparsed"] — нерозпізнані шматки (у кінці файлу).
    """
    L = []
    add = L.append

    def note(obj, key):
        text = (obj.get("_flags") or {}).get(key)
        return f"   # {text}" if text else ""

    add(f"# Конфіг сайту — створено командою `{source}`.")
    for line in d.get("_header") or []:
        add(f"# {line}" if line else "#")
    add("# Докладний опис кожного поля з прикладами: config/examples/ та README.md.")
    add("# [БАЗА] — початкове значення: після першого запуску його змінює власник в адмінці,")
    add("#          і правка тут уже не діє (скинути: python manage.py seed --reset).")
    add("# Секрети (паролі, токени) — тільки у файлі .env, не тут.")
    add("")
    add("brand:")
    add(f"  name: {q(d['name'])}                # назва{note(d, 'name')}")
    add(f"  kind: {q(d['kind'])}                # тип закладу перед назвою (можна порожньо)")
    add(f"  tagline: {q(d['tagline'])}          # слоган, один рядок{note(d, 'tagline')}")
    add(f"  description: {q(d['description'])}  # 2–3 речення під заголовком на головній{note(d, 'description')}")
    add('  logo: ""                             # шлях у static/, напр. media/brand/logo.png. Порожньо — назва текстом')
    add('  logo_light: ""                       # логотип для темного тла (шапка). Порожньо = logo')
    add('  favicon: ""                          # іконка вкладки. Порожньо — літера з назви')
    add(f"  theme: {d['theme']}                 # dark | wood | forest | midnight | cabin{note(d, 'theme')}")
    add('  primary_color: ""                    # свій колір кнопок, напр. "#3a2a1d"')
    add('  accent_color: ""                     # свій акцентний колір')
    add("")
    add("contacts:")
    add(f"  phone: {q(d['phone'])}              # телефон, як показувати на сайті{note(d, 'phone')}")
    add(f"  viber: {q(d['viber'])}              # номер Viber. Порожньо — кнопки не буде")
    add(f"  whatsapp: {q(d['whatsapp'])}        # номер WhatsApp")
    add(f"  telegram: {q(d['telegram'])}        # нік без @ (для гостей; це не бот сповіщень){note(d, 'telegram')}")
    add(f"  instagram: {q(d['instagram'])}      # нік без @{note(d, 'instagram')}")
    if d.get("tiktok"):
        add(f"  tiktok: {q(d['tiktok'])}            # нік без @")
    add(f"  email: {q(d['email'])}")
    add(f"  address: {q(d['address'])}          # адреса{note(d, 'address')}")
    add(f"  region: {q(d['region'])}            # область / район")
    add(f"  coordinates: {d['coordinates'] or '[]'}   # [широта, довгота] для карти; [] — карта за адресою"
        f"{note(d, 'coordinates')}")
    add(f"  directions: {q(d['directions'])}    # як доїхати")
    add("")
    add("# Об'єкти. id — адреса сторінки й папка фото media/objects/<id>/. Після запуску id не змінюйте.")
    add("objects:")
    for i, o in enumerate(d["objects"]):
        add(f"  - id: {q(o['id'])}")
        add(f"    name: {q(o['name'])}{note(o, 'name')}")
        add(f"    type: {q(o['type'])}                # котедж, шале, апартаменти…")
        add(f"    tagline: {q(o['tagline'])}          # рядок над назвою")
        add("    # Опис: перший абзац — короткий вступ. Абзаци розділяйте порожнім рядком." + note(o, "description"))
        add("    description: |")
        for paragraph in str(o["description"]).split("\n"):
            add(f"      {paragraph}".rstrip())
        if i == 0 and len(d["objects"]) >= 3:
            add("    featured: true                     # великий блок на головній")
        add(f"    units: {o['units']}                  # [БАЗА] скільки однакових одиниць{note(o, 'units')}")
        add(f"    price: {o['price']}                  # [БАЗА] базова ціна за ніч, грн{note(o, 'price')}")
        add(f"    base_guests: {o['base_guests']}      # [БАЗА] гостей у базовій ціні{note(o, 'base_guests')}")
        add(f"    max_guests: {o['max_guests']}        # [БАЗА] максимум гостей{note(o, 'max_guests')}")
        add(f"    extra_guest_price: {o['extra_guest_price']}   # [БАЗА] доплата за гостя понад базу, грн за ніч"
            f"{note(o, 'extra_guest_price')}")
        add(f"    min_nights: {o['min_nights']}        # [БАЗА] мінімум ночей{note(o, 'min_nights')}")
        add("    # weekend_price: 4500              # [БАЗА] ціна ночі в пт і сб (необов'язково), порожньо — як у будні")
        add("    # weekend_min_nights: 2            # [БАЗА] мінімум ночей, якщо серед них є пт чи сб (необов'язково)")
        for key in ("bedrooms", "bathrooms"):
            if o.get(key) is not None:
                add(f"    {key}: {o[key]}")
        add(f"    check_in: {q(o['check_in'])}         # час заїзду{note(o, 'check_in')}")
        add(f"    check_out: {q(o['check_out'])}       # час виїзду{note(o, 'check_out')}")
        add("    amenities:" + ("" if o["amenities"] else " []") + note(o, "amenities"))
        for a in o["amenities"]:
            add(f"      - {q(a)}")
        add("")
    add("# Додаткові послуги. unit: evening (за вечір) | once (за бронювання) | night (за ніч) |")
    add("#                         person (за людину) | person_night (за людину за ніч)")
    add("extras:" + ("" if d["extras"] else " []"))
    for e in d["extras"]:
        add(f"  - id: {q(e['id'])}                    # фото: media/extras/{e['id']}.jpg")
        add(f"    name: {q(e['name'])}")
        add(f"    description: {q(e['description'])}")
        add(f"    price: {e['price']}                  # [БАЗА] ціна, грн{note(e, 'price')}")
        add(f"    unit: {e['unit']}{note(e, 'unit')}")
        add("    icon: hottub" if "чан" in e["name"].lower() else "    icon: star")
        if e["guest_prices"]:
            add("    guest_prices:                       # [БАЗА] ціна залежно від кількості гостей")
            for t in e["guest_prices"]:
                add(f"      - {{up_to: {t['up_to']}, price: {t['price']}}}")
    add("")
    add("# [БАЗА] Сезони з особливою ціною. Для кожного — одне з: price (для всіх об'єктів),")
    add("# prices: {id: ціна} або on_request: true (ціна за домовленістю). Дати: РРРР-ММ-ДД.")
    add("seasons:" + ("" if d["seasons"] else " []"))
    for s in d["seasons"]:
        add(f"  - name: {q(s['name'])}{note(s, 'name')}")
        add(f"    start: {s['start']}{note(s, 'dates')}")
        add(f"    end: {s['end']}")
        if s.get("prices"):
            add("    prices:" + note(s, "prices"))
            for key, price in s["prices"].items():
                add(f"      {q(key)}: {price}")
        elif s.get("price"):
            add(f"    price: {s['price']}                # для всіх об'єктів{note(s, 'price')}")
        else:
            add("    on_request: true")
    add("")
    add("rules:")
    add(f"  prepayment_percent: {d['prepayment']}   # передоплата, %{note(d, 'prepayment')}")
    add(f"  check_in: {q(d['check_in'])}{note(d, 'check_in')}")
    add(f"  check_out: {q(d['check_out'])}{note(d, 'check_out')}")
    add("  cancellation:")
    add(f"    days: {d['cancel_days']}{note(d, 'cancel_days')}")
    add(f"    text: {q(d['cancel_text'])}{note(d, 'cancel_text')}")
    add(f"  pets: {q(d['pets'])}                   # порожньо — пункт не показується")
    add(f"  smoking: {q(d['smoking'])}")
    add(f"  quiet: {q(d['quiet'])}")
    add("")
    add("# Блоки головної: true — показувати, false — приховати.")
    add("sections:")
    for key, value in (("about", "false"), ("extras", "true"), ("gallery", "true"), ("prices", "true"),
                       ("reviews", "false"), ("faq", "true"), ("nearby", "false"), ("map", "true")):
        add(f"  {key}: {value}")
    add("")
    add("# Переваги під банером (блок about): - {icon: mountain, title: Вид на гори, text: Панорама з вікон.}")
    add("perks: []")
    add("# Відгуки (блок reviews): - {text: …, author: …, meta: «Котедж · жовтень 2026»}")
    add("reviews: []")
    add("# Що поруч (блок nearby): - {icon: ski, title: Траси, text: …, distance: 2 км}")
    add("nearby: []")
    add("faq:")
    add("  - q: Як забронювати?")
    add("    a: Оберіть дати в календарі й залиште заявку — ми зателефонуємо, підтвердимо деталі й надішлемо реквізити.")
    add("")
    add("# Демо-версія для показу клієнту до оплати: водяні знаки, noindex, доступ за посиланням із терміном дії")
    add("# (python manage.py demo-link). Пароль демо, якщо потрібен, — лише в .env (див. .env.example).")
    add("# Після оплати клієнтом — enabled: false.")
    add("demo:")
    add("  enabled: false")
    add('  domain: ""                    # адреса демо на сервері, напр. назва.1-2-3-4.sslip.io')
    add("  days: 14                      # скільки діє посилання")
    add("  link_version: 1               # збільште, щоб скасувати всі видані посилання")
    add("  watermark: subtle             # знак у фото: subtle (підпис у куті) | grid (сітка) | off")
    add("")
    add("seo:")
    add(f"  title: {q(d['seo_title'])}")
    add(f"  description: {q(d['description'])}")
    add("  lang: uk")
    add("")
    if d.get("_unparsed"):
        add("# ── НЕ РОЗПІЗНАНО З ЧАТУ — перенесіть потрібне у поля вище й видаліть цей блок ──")
        for label, text in d["_unparsed"]:
            for i, line in enumerate(str(text).splitlines() or [""]):
                add(f"# {label}: {line}" if i == 0 else f"#     {line}")
        add("")
    return "\n".join(L)


def wizard():
    """Питає все потрібне й повертає дані для render_config."""
    print("\n══ Новий клієнт ══\nEnter — прийняти значення в [дужках]. Усе можна потім змінити у файлі конфігу.\n")
    d = {}
    print("— Бренд —")
    d["name"] = ask("Назва (напр. Ramshill)", check=_required)
    d["kind"] = ask("Тип закладу перед назвою (Котеджі / Приватна садиба; можна порожньо)", "")
    d["tagline"] = ask("Слоган, один рядок", "Котеджі в Карпатах")
    d["description"] = ask("Опис для головної, 1–2 речення", d["tagline"])
    themes = {"1": "dark", "2": "wood", "3": "forest", "4": "midnight", "5": "cabin"}
    choice = ask("Тема: 1 — dark (чорна, теплі вогні), 2 — wood (світла, дерево), 3 — forest (темно-зелена), "
                 "4 — midnight (темно-синя із золотом), 5 — cabin (тепле дерево, глибокий зелений, мідь)", "2",
                 lambda v: None if v in themes or v in themes.values() else "Введіть число від 1 до 5.")
    d["theme"] = themes.get(choice, choice)

    print("\n— Контакти —")
    d["phone"] = ask("Телефон (напр. +380 67 123 45 67)", check=_phone)
    digits = "+" + re.sub(r"\D", "", d["phone"])
    d["viber"] = digits if ask_yes("Цей номер є у Viber?", True) else ""
    d["whatsapp"] = digits if ask_yes("Цей номер є у WhatsApp?", False) else ""
    nick = lambda v: None if not v or re.fullmatch(r"[\w.]+", v) else "Лише нік без @ і без посилання."  # noqa: E731
    d["telegram"] = ask("Нік у Telegram без @ (можна порожньо)", "", nick)
    d["instagram"] = ask("Нік в Instagram без @ (можна порожньо)", "", nick)
    d["email"] = ask("Email (можна порожньо)", "",
                     lambda v: None if not v or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) else "Не схоже на email.")
    d["address"] = ask("Адреса (напр. смт Славське, вул. Франка, 1)", check=_required)
    d["region"] = ask("Область", "Львівська область")

    def coords(v):
        if not v:
            return None
        m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*", v)
        return None if m and abs(float(m[1])) <= 90 and abs(float(m[2])) <= 180 else "Два числа через кому: 48.8372, 23.4456"
    raw = ask("Координати для карти «широта, довгота» (можна порожньо)", "", coords)
    d["coordinates"] = "[" + ", ".join(re.split(r"[,;\s]+", raw.strip())) + "]" if raw else ""
    d["directions"] = ask("Як доїхати (можна порожньо)", "")

    print("\n— Правила —")
    d["prepayment"] = ask_int("Передоплата, %", 30, 0, 100)
    d["check_in"] = ask("Час заїзду", "14:00", _time)
    d["check_out"] = ask("Час виїзду", "12:00", _time)
    d["cancel_days"] = ask_int("За скільки днів до заїзду можна перенести / скасувати без втрат", 7, 0, 365)
    d["cancel_text"] = (f"Якщо попередити не пізніше ніж за {d['cancel_days']} днів до заїзду — перенесемо дати. "
                        f"Пізніше передоплата не повертається.")
    d["pets"] = ask("Домашні тварини (текст; порожньо — не показувати)", "За попередньою домовленістю.")
    d["smoking"] = ask("Куріння", "Не куримо всередині — лише надворі.")
    d["quiet"] = ask("Тиша", "Тиша після 22:00.")

    print("\n— Об'єкти (котеджі, будинки) —")
    d["objects"], used = [], set(site_config.RESERVED_IDS)
    while True:
        n = len(d["objects"]) + 1
        print(f"\nОб'єкт №{n}")
        o = {"name": ask("  Назва (напр. Великий котедж)", check=_required)}
        suggestion = slugify(o["name"]) or f"object-{n}"
        o["id"] = ask("  id латиницею (адреса сторінки й папка фото)", suggestion,
                      lambda v: None if site_config.ID_RE.match(v) and v not in used
                      else "Малі латинські літери, цифри й дефіс; id не має повторюватись.")
        used.add(o["id"])
        o["type"] = ask("  Тип", "Котедж")
        o["tagline"] = ask("  Короткий рядок над назвою (можна порожньо)", "")
        o["description"] = ask("  Опис, 1–3 речення", f"{o['name']} — затишний відпочинок у горах.")
        o["units"] = ask_int("  Скільки ОДНАКОВИХ таких об'єктів (бронюються окремо)", 1, 1, 50)
        o["price"] = ask_int("  Базова ціна за ніч, грн", low=1)
        o["max_guests"] = ask_int("  Максимум гостей", 4, 1, 50)
        o["base_guests"] = ask_int("  Скільки гостей входить у базову ціну", min(2, o["max_guests"]), 1, o["max_guests"])
        o["extra_guest_price"] = (ask_int("  Доплата за кожного гостя понад базу, грн за ніч", 500, 0, 100_000)
                                  if o["base_guests"] < o["max_guests"] else 0)
        o["min_nights"] = ask_int("  Мінімум ночей", 1, 1, 30)
        o["bedrooms"] = ask_int("  Спалень", 1, 0, 30)
        o["bathrooms"] = ask_int("  Санвузлів", 1, 0, 30)
        o["check_in"] = ask("  Час заїзду", d["check_in"], _time)
        o["check_out"] = ask("  Час виїзду", d["check_out"], _time)
        raw = ask("  Зручності через кому (Камін, Тераса, Wi-Fi)", "Wi-Fi, Парковка")
        o["amenities"] = [a.strip() for a in raw.split(",") if a.strip()]
        d["objects"].append(o)
        if not ask_yes("\nДодати ще один об'єкт?", False):
            break

    print("\n— Додаткові послуги (чан, баня, сніданки, трансфер) —")
    d["extras"], units = [], {"1": "evening", "2": "once", "3": "night", "4": "person", "5": "person_night"}
    while ask_yes("Додати послугу?" if not d["extras"] else "Додати ще одну послугу?", not d["extras"]):
        e = {"name": ask("  Назва (напр. Чан)", check=_required)}
        taken = {x["id"] for x in d["extras"]}
        e["id"] = ask("  id латиницею", slugify(e["name"]) or f"extra-{len(d['extras']) + 1}",
                      lambda v: None if site_config.ID_RE.match(v) and v not in taken else "Латиниця, цифри, дефіс; без повторів.")
        e["description"] = ask("  Опис, одне речення (можна порожньо)", "")
        u = ask("  Ціна: 1 — за вечір, 2 — за бронювання, 3 — за ніч, 4 — за людину, 5 — за людину за ніч", "1",
                lambda v: None if v in units else "Введіть число від 1 до 5.")
        e["unit"] = units[u]
        e["price"] = ask_int("  Ціна, грн", low=1)
        e["guest_prices"] = []
        if ask_yes("  Ціна залежить від кількості гостей? (напр. 2500 для 2, 3000 для 3–4)", False):
            last = 0
            while True:
                up_to = ask_int(f"    До скількох гостей (більше за {last})", low=last + 1, high=50)
                e["guest_prices"].append({"up_to": up_to, "price": ask_int(f"    Ціна до {up_to} гостей, грн", low=1)})
                last = up_to
                if not ask_yes("    Ще один поріг?", False):
                    break
            e["price"] = e["guest_prices"][-1]["price"]
        d["extras"].append(e)

    print("\n— Сезони —")
    d["seasons"] = []
    if ask_yes("Додати сезон «Новорічні свята» з окремими цінами?", False):
        day = lambda v: None if site_config.parse_date(v) else "Дата у форматі РРРР-ММ-ДД, напр. 2026-12-28"  # noqa: E731
        s = {"name": ask("  Назва", "Новорічні свята"), "start": ask("  Перша ніч (РРРР-ММ-ДД)", check=day)}
        s["end"] = ask("  Остання ніч (РРРР-ММ-ДД)",
                       check=lambda v: day(v) or (None if v >= s["start"] else "Кінець не може бути раніше за початок."))
        if ask_yes("  Вказати ціни зараз? (ні — «ціна за домовленістю»)", True):
            s["prices"] = {o["id"]: ask_int(f"    «{o['name']}», грн за ніч", o["price"], 1) for o in d["objects"]}
        d["seasons"].append(s)

    kind = f"{d['kind']} " if d["kind"] else ""
    d["seo_title"] = f"{kind}{d['name']} — {d['tagline']}"[:90]
    return d


def cmd_new_client(args):
    out = args.output if os.path.isabs(args.output) else os.path.join(BASE_DIR, args.output)
    if os.path.exists(out) and not args.force:
        print(f"\nФайл {_rel(out)} уже існує.")
        if not ask_yes("Замінити його? (старий збережеться як .bak)", False):
            print("Скасовано. Інший файл: python manage.py new-client --output config/назва.yaml")
            return 1
    data = wizard()
    text = render_config(data)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        shutil.copy2(out, out + ".bak")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    errors, _ = site_config.validate(site_config.read_yaml(out), check_photos=False)
    print(f"\n{OK} Конфіг збережено: {_rel(out)}")
    for e in errors:
        print(f"{FAIL} {e}")

    root = site_config.media_root(out)
    demo = os.path.join(BASE_DIR, "static", "media")
    if root == "media" and os.path.isdir(demo) and any(os.scandir(demo)):
        if ask_yes("\nУ static/media/ лежать демо-фото шаблону. Видалити їх?", True):
            for name in os.listdir(demo):
                if name != "examples":
                    path = os.path.join(demo, name)
                    shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)
            print(f"{OK} Демо-фото видалено.")
    for o in data["objects"]:
        os.makedirs(os.path.join(BASE_DIR, root, "objects", o["id"]), exist_ok=True)
    for sub in ("hero", "gallery", "extras", "brand"):
        os.makedirs(os.path.join(BASE_DIR, root, sub), exist_ok=True)

    flag = "" if root == "media" else f" --config {_rel(out)}"
    print("\nДалі:")
    print(f"  1. Покладіть фото:  {root}/objects/<id>/ (є папки: {', '.join(o['id'] for o in data['objects'])}),")
    print(f"     {root}/hero/ — одне фото для банера, {root}/gallery/ — територія.")
    print(f"  2. python manage.py photos{flag}      — обробити фото")
    print(f"  3. python manage.py validate{flag}    — перевірити конфіг")
    print("  4. cp .env.example .env  і заповніть паролі й Telegram")
    print(f"  5. python manage.py seed{flag}        — залити ціни в базу")
    print(f"  6. python manage.py check{flag}       — чи все готово до деплою")
    print("  7. python app.py  →  http://localhost:5000\n")
    return 1 if errors else 0


# ---------- демо-версія ----------

def cmd_demo_link(args):
    """Посилання на демо з терміном дії. Потрібен той самий SECRET_KEY, що й у сайту (запускати на сервері)."""
    import demo
    import security
    cfg = _load(args)
    if not cfg.demo["enabled"]:
        print(f"\nДемо-режим вимкнено. Увімкніть у {_rel(cfg.path)}:\n\n"
              "demo:\n  enabled: true\n  domain: НАЗВА.1-2-3-4.sslip.io   # адреса демо на сервері\n")
        return 1
    _load_env()
    try:
        secret = security.require_secret_key(os.environ.get("SECRET_KEY"))
    except security.SecurityConfigError as exc:
        print(f"\n{exc}\n")
        return 1
    days = args.days or cfg.demo["days"]
    token, expires = demo.make_link_token(cfg, secret, days=days)
    from datetime import datetime
    until = datetime.fromtimestamp(expires).strftime("%d.%m.%Y %H:%M")
    print(f"\nПосилання на демо «{cfg.brand['name']}» (діє {days} дн., до {until}):\n")
    print(f"https://{cfg.demo['domain']}/demo/{token}\n")
    if demo.password():
        print("Потрібен пароль (DEMO_PASSWORD з .env) — надішліть його клієнту окремим повідомленням.")
    fid = demo.fingerprint(cfg, secret)
    print(f"Ідентифікатор демо (для доказу авторства): yalott-demo:{fid}")
    if not args.no_warm:
        instance = os.environ.get("INSTANCE_PATH") or os.path.join(BASE_DIR, "instance")
        count = demo.warm(cfg, os.path.join(BASE_DIR, "static"), os.path.join(instance, "demo-cache"), fid)
        print(f"Фото з водяним знаком підготовлено заздалегідь: {count}.")
    print(f"Скасувати всі видані посилання: збільште demo.link_version у {_rel(cfg.path)} "
          f"(зараз {cfg.demo['link_version']}) і перезапустіть сайт.\n")
    return 0


def cmd_demo_find(args):
    """Шукає позначки нашого демо в збереженій сторінці, тексті чи фото чужого сайту."""
    import demo
    found, where = [], args.file or "вставлений текст"
    if args.file and args.file.lower().endswith((".webp", ".jpg", ".jpeg", ".png")):
        from PIL import Image
        with Image.open(args.file) as im:
            exif = im.getexif()
            text = " ".join(str(v) for v in exif.values())
    elif args.file:
        with open(args.file, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        if sys.stdin.isatty():
            print("Вставте текст чи HTML з підозрілого сайту, потім Ctrl+D:\n")
        text = sys.stdin.read()
    found = demo.find_marks(text)
    if not found:
        print(f"\nУ «{where}» позначок демо Yalott Studio не знайдено.\n")
        return 1
    print(f"\nУ «{where}» знайдено позначку демо: " + ", ".join(f"yalott-demo:{f}" for f in found))
    try:
        cfg = site_config.load(_path(args))
        _load_env()
        mine = demo.fingerprint(cfg, os.environ.get("SECRET_KEY", ""))
        if mine in found:
            print(f"Це демо «{cfg.brand['name']}» ({_rel(cfg.path)}) — збігається з ідентифікатором, "
                  f"який можна відтворити лише з нашим SECRET_KEY.")
    except Exception:
        pass
    print("Збережіть файл і посилання на сторінку як доказ.\n")
    return 0


# ---------- анкета в чаті ----------

def cmd_anketa(args):
    import chat_import
    print(chat_import.QUESTIONNAIRE)
    return 0


def _make_media_dirs(root, object_ids):
    for oid in object_ids:
        os.makedirs(os.path.join(BASE_DIR, root, "objects", oid), exist_ok=True)
    for sub in ("hero", "gallery", "extras", "brand"):
        os.makedirs(os.path.join(BASE_DIR, root, sub), exist_ok=True)


def cmd_from_chat(args):
    """Відповіді клієнта з чату (файл або вставлений текст) → конфіг + звіт + повідомлення-дозапит."""
    import chat_import
    out = args.output if os.path.isabs(args.output) else os.path.join(BASE_DIR, args.output)
    if os.path.exists(out) and not args.force:
        print(f"\nФайл {_rel(out)} уже існує. Додайте --force (старий збережеться як .bak) "
              f"або вкажіть інший: --output config/назва.yaml\n")
        return 1
    if args.file and args.file != "-":
        with open(args.file, encoding="utf-8-sig") as f:
            text = f.read()
    else:
        if sys.stdin.isatty():
            print("Вставте відповіді клієнта з чату як є, потім з нового рядка натисніть Ctrl+D "
                  "(у Windows — Ctrl+Z і Enter):\n")
        text = sys.stdin.read()
    if not text.strip():
        print("Порожній текст — нічого розбирати.")
        return 1

    data, report = chat_import.parse_chat(text, slugify=slugify)
    if args.theme:
        data["theme"] = args.theme
        data["_flags"].pop("theme", None)
    data["_header"] = [
        "Дані розібрано з відповідей клієнта в чаті. Перед запуском перегляньте коментарі:",
        "  «ПЕРЕВІРИТИ: …» — значення взято з чату, але варто глянути;",
        "  «ЗАМІНИТИ: …»   — даних немає, стоїть заглушка (python manage.py check не пропустить до деплою).",
        "Нерозпізнані шматки відповідей — у кінці файлу.",
    ]
    text_yaml = render_config(data, source="python manage.py from-chat")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        shutil.copy2(out, out + ".bak")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text_yaml)
    errors, _ = site_config.validate(site_config.read_yaml(out), check_photos=False)
    _make_media_dirs(site_config.media_root(out), [o["id"] for o in data["objects"]])

    print(f"\n{OK} Конфіг збережено: {_rel(out)}" + ("" if not os.path.exists(out + ".bak") else f" (попередній — {_rel(out)}.bak)"))
    print(f"   Відповіді є на питання: {', '.join(map(str, report['answered'])) or 'жодне з номером'}")
    print("\nРозпізнано:")
    for line in report["found"]:
        print(f"{OK} {line}")
    if report["check"]:
        print("\nПеревірити (у конфігу позначено «ПЕРЕВІРИТИ»):")
        for line in report["check"]:
            print(f"{WARN} {line}")
    if report["missing"]:
        print("\nБракує (у конфігу — «ЗАМІНИТИ», дозапитайте в клієнта або допишіть):")
        for line in report["missing"]:
            print(f"{FAIL} {line}")
    if report["unparsed"]:
        print("\nНе розпізнано (лежить коментарем у кінці конфігу):")
        for label, piece in report["unparsed"]:
            print(f"   [{label}] {piece[:100]}")
    for e in errors:
        print(f"{FAIL} конфіг: {e}")
    followup = chat_import.followup_message(report)
    if followup:
        print("\n──── Повідомлення клієнту (скопіюйте в чат) ────\n")
        print(followup)
        print("\n────────────────────────────────────────────────")
        print("Коли клієнт відповість — допишіть відповіді в конфіг або вставте весь чат ще раз з --force.")
    flag = "" if site_config.media_root(out) == "media" else f" --config {_rel(out)}"
    print(f"\nДалі: фото → {site_config.media_root(out)}/objects/<id>/, потім python manage.py photos{flag} "
          f"і python manage.py check{flag}\n")
    return 1 if errors else 0


# ---------- запуск ----------

def main(argv=None):
    parser = argparse.ArgumentParser(prog="manage.py", description="Команди сайту котеджу (шаблон Yalott Studio).")
    sub = parser.add_subparsers(dest="command", metavar="команда")

    def command(name, func, text):
        p = sub.add_parser(name, help=text, description=text)
        p.add_argument("--config", help="шлях до конфігу (типово config/site.yaml або змінна SITE_CONFIG)")
        p.set_defaults(func=func)
        return p

    p = sub.add_parser("anketa", help="повідомлення-опитувальник для клієнта (скопіювати в чат)")
    p.set_defaults(func=cmd_anketa)

    p = sub.add_parser("from-chat", help="відповіді клієнта з чату → config/site.yaml і список, чого бракує")
    p.add_argument("file", nargs="?", help="файл із текстом чату (без нього — вставити текст у термінал)")
    p.add_argument("--output", default=os.path.join("config", "site.yaml"), help="куди зберегти (типово config/site.yaml)")
    p.add_argument("--force", action="store_true", help="замінити наявний файл (старий збережеться як .bak)")
    p.add_argument("--theme", choices=site_config.THEMES, help="тема оформлення (типово wood)")
    p.set_defaults(func=cmd_from_chat)

    p = sub.add_parser("new-client", help="майстер: створити config/site.yaml для нового клієнта")
    p.add_argument("--output", default=os.path.join("config", "site.yaml"), help="куди зберегти (типово config/site.yaml)")
    p.add_argument("--force", action="store_true", help="замінити наявний файл без питань")
    p.set_defaults(func=cmd_new_client)

    command("validate", cmd_validate, "перевірити конфіг")
    p = command("seed", cmd_seed, "залити конфіг у базу (безпечно повторно)")
    p.add_argument("--reset", action="store_true", help="перезаписати ціни, параметри й сезони значеннями з конфігу")
    p.add_argument("--yes", action="store_true", help="не питати підтвердження для --reset")
    p.add_argument("--demo", action="store_true", help="додати демо-зайнятість і демо-заявки (для показу клієнту)")
    p.add_argument("--clear-demo", action="store_true", help="прибрати демо-дані")
    p = command("photos", cmd_photos, "обробити фото з media/ у static/media/")
    p.add_argument("--force", action="store_true", help="обробити всі фото заново")
    p.add_argument("--enhance", action="store_true", help="трохи підняти яскравість, контраст і насиченість")
    command("check", cmd_check, "перевірити готовність до деплою")
    p = command("demo-link", cmd_demo_link, "посилання на демо-версію з терміном дії")
    p.add_argument("--days", type=int, choices=range(1, 91), metavar="ДНІВ", help="скільки діє посилання (1–90)")
    p.add_argument("--no-warm", action="store_true", help="не готувати фото з водяним знаком заздалегідь")
    p = command("demo-find", cmd_demo_find, "знайти позначку нашого демо в чужій сторінці, тексті чи фото")
    p.add_argument("file", nargs="?", help="збережена сторінка (.html), текст або фото")
    p = command("set-password", cmd_set_password, "змінити пароль адмінки")
    p.add_argument("username", nargs="?", default="admin")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
