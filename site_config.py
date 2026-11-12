"""Конфіг клієнта: config/site.yaml → перевірка → зручна структура для сайту.

Усе, що відрізняє один сайт від іншого (назва, контакти, об'єкти, ціни, тексти, тема),
лежить в ОДНОМУ файлі config/site.yaml. Код і шаблони під клієнта не правляться.

  load(path)      — прочитати, перевірити й нормалізувати конфіг (помилка → ConfigError);
  validate(raw)   — список зрозумілих помилок і попереджень українською;
  SITE_CONFIG     — змінна оточення зі шляхом до конфігу (типово config/site.yaml).

ПРІОРИТЕТ ДАНИХ. Ціни, кількість гостей, одиниць, мінімум ночей, сезони й ціни послуг із конфігу —
лише ПОЧАТКОВІ: вони один раз записуються в базу (seed), далі діють значення з адмінки.
Тексти, контакти, фото, тема, правила — завжди беруться з конфігу.

Секретів (паролі, токени) у конфігу немає — вони тільки в .env.
"""

import os
import re
from datetime import date

import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(BASE_DIR, "config", "site.yaml")

THEMES = ("dark", "wood", "forest")
# Одиниця ціни послуги → (підпис, множник: n — ночі, g — гості).
EXTRA_UNITS = {
    "evening": "за вечір",
    "once": "за бронювання",
    "night": "за ніч",
    "person": "за людину",
    "person_night": "за людину за ніч",
}
SECTIONS = ("about", "extras", "gallery", "prices", "reviews", "faq", "nearby", "map")
RESERVED_IDS = {"admin", "api", "static", "media", "favicon", "robots", "sitemap"}
SECRET_WORDS = ("password", "token", "secret", "chat_id", "пароль", "токен")

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")


class ConfigError(Exception):
    """Конфіг не пройшов перевірку. errors — список рядків українською."""

    def __init__(self, path, errors):
        self.path, self.errors = path, list(errors)
        super().__init__(f"Конфіг {path} містить помилки:\n" + "\n".join(f"  • {e}" for e in self.errors))


# ---------- YAML: дати й час лишаються рядками ----------
# Стандартний YAML сам перетворює 2026-12-30 на дату, 15:00 — на число 900, а 001 — на 1.
# Тут це вимкнено, щоб «2026-13-45» давало зрозумілу помилку, а «15:00» і «001» лишались як написано.

class _Loader(yaml.SafeLoader):
    pass


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers
         if tag not in ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:int", "tag:yaml.org,2002:float")]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver("tag:yaml.org,2002:int", re.compile(r"^-?(?:0|[1-9][0-9]*)$"), list("-0123456789"))
_Loader.add_implicit_resolver("tag:yaml.org,2002:float", re.compile(r"^-?(?:0|[1-9][0-9]*)\.[0-9]+$"),
                              list("-0123456789"))


def read_yaml(path):
    """Повертає dict із файлу. Помилки синтаксису — ConfigError з номером рядка."""
    if not os.path.exists(path):
        raise ConfigError(path, [f"Файл не знайдено. Створіть його командою: python manage.py new-client"])
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = yaml.load(f, Loader=_Loader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"рядок {mark.line + 1}, позиція {mark.column + 1}: " if mark else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise ConfigError(path, [f"Синтаксис YAML — {where}{problem}. Перевірте відступи (лише пробіли), "
                                 f"двокрапки й лапки."])
    if not isinstance(raw, dict):
        raise ConfigError(path, ["Файл порожній або це не набір полів «ключ: значення»."])
    return raw


def config_path():
    """Шлях до конфігу: SITE_CONFIG з оточення (відносний — від папки проєкту) або config/site.yaml."""
    path = os.environ.get("SITE_CONFIG", "").strip() or DEFAULT_PATH
    return path if os.path.isabs(path) else os.path.join(BASE_DIR, path)


# ---------- Перевірка ----------

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_date(v):
    """«2026-12-30» → date або None, якщо це не справжня дата."""
    if isinstance(v, date):
        return v
    if not isinstance(v, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()):
        return None
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        return None


def known_icons():
    """Назви іконок із templates/_icons.html (для поля icon)."""
    try:
        with open(os.path.join(BASE_DIR, "templates", "_icons.html"), encoding="utf-8") as f:
            return set(re.findall(r'^\s*"([a-z0-9-]+)":', f.read(), re.M))
    except OSError:
        return set()


class _Check:
    """Збирає помилки (err) і попередження (warn) із зрозумілим шляхом до поля."""

    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, where, text):
        self.errors.append(f"{where}: {text}")

    def warn(self, where, text):
        self.warnings.append(f"{where}: {text}")

    def text(self, d, key, where, required=False, max_len=None):
        v = d.get(key)
        if v in (None, ""):
            if required:
                self.err(f"{where} → {key}", "обов'язкове поле, а його немає або воно порожнє")
            return ""
        if isinstance(v, (dict, list)) or isinstance(v, bool):
            self.err(f"{where} → {key}", "має бути текст")
            return ""
        v = str(v).strip()
        if max_len and len(v) > max_len:
            self.err(f"{where} → {key}", f"задовгий текст ({len(v)} символів, можна до {max_len})")
        return v

    def integer(self, d, key, where, required=False, default=None, low=None, high=None):
        v = d.get(key)
        if v in (None, ""):
            if required:
                self.err(f"{where} → {key}", "обов'язкове поле, а його немає")
            return default
        if not _is_int(v):
            self.err(f"{where} → {key}", f"має бути ціле число без лапок і пробілів, а вказано «{v}»")
            return default
        if low is not None and v < low:
            self.err(f"{where} → {key}", f"не може бути менше {low} (вказано {v})")
        if high is not None and v > high:
            self.err(f"{where} → {key}", f"не може бути більше {high} (вказано {v})")
        return v

    def section(self, raw, key, kind, required=False):
        v = raw.get(key)
        if v is None:
            if required:
                self.err(key, "немає цього розділу — він обов'язковий")
            return kind()
        if not isinstance(v, kind):
            what = "список (рядки, що починаються з «- »)" if kind is list else "набір полів «ключ: значення»"
            self.err(key, f"має бути {what}")
            return kind()
        return v

    def icon(self, d, where, icons):
        v = d.get("icon")
        if v and icons and v not in icons:
            self.err(f"{where} → icon", f"немає іконки «{v}». Доступні: {', '.join(sorted(icons))}")

    def time(self, d, key, where):
        v = d.get(key)
        if v in (None, ""):
            return
        if not isinstance(v, str) or not TIME_RE.match(v.strip()):
            self.err(f"{where} → {key}", f"час має бути у форматі ГГ:ХХ, напр. \"15:00\" (вказано «{v}»)")


def _find_secrets(node, path, c):
    if isinstance(node, dict):
        for k, v in node.items():
            if any(w in str(k).lower() for w in SECRET_WORDS):
                c.err(f"{path}{k}", "схоже на секрет (пароль / токен / chat id). Секрети зберігаються ТІЛЬКИ у файлі .env")
            _find_secrets(v, f"{path}{k} → ", c)
    elif isinstance(node, list):
        for i, v in enumerate(node, 1):
            _find_secrets(v, f"{path}№{i} → ", c)


def _ranges_overlap(a, b):
    return a[0] <= b[1] and b[0] <= a[1]


def validate(raw, check_photos=True, static_dir=None, media="media"):
    """Перевіряє «сирий» конфіг. Повертає (errors, warnings) — списки рядків українською."""
    c = _Check()
    icons = known_icons()
    _find_secrets(raw, "", c)

    known_top = {"brand", "contacts", "objects", "extras", "seasons", "rules", "sections", "about", "perks",
                 "gallery", "reviews", "faq", "nearby", "seo", "studio", "integrations"}
    for key in raw:
        if key not in known_top:
            c.warn(str(key), "невідомий розділ — сайт його не використовує (можливо, помилка в назві)")

    # --- brand ---
    brand = c.section(raw, "brand", dict, required=True)
    c.text(brand, "name", "brand", required=True, max_len=60)
    c.text(brand, "tagline", "brand", max_len=140)
    theme = brand.get("theme")
    if theme in (None, ""):
        c.err("brand → theme", f"не вказано тему. Оберіть одну з: {', '.join(THEMES)}")
    elif theme not in THEMES:
        c.err("brand → theme", f"немає теми «{theme}». Доступні: {', '.join(THEMES)}")
    for key in ("primary_color", "accent_color"):
        v = brand.get(key)
        if v not in (None, "") and not (isinstance(v, str) and COLOR_RE.match(v.strip())):
            c.err(f"brand → {key}", f"колір має бути у форматі \"#a06a3c\" (у лапках), а вказано «{v}»")
    prefix = brand.get("booking_prefix")
    if prefix not in (None, "") and not re.match(r"^[A-Z0-9]{2,5}$", str(prefix)):
        c.err("brand → booking_prefix", "2–5 великих латинських літер або цифр, напр. RH")

    # --- contacts ---
    contacts = c.section(raw, "contacts", dict, required=True)
    phone = c.text(contacts, "phone", "contacts", required=True)
    if phone and not 9 <= len(re.sub(r"\D", "", phone)) <= 15:
        c.err("contacts → phone", f"не схоже на номер телефону: «{phone}». Приклад: \"+380 67 123 45 67\"")
    for key in ("viber", "whatsapp"):
        v = c.text(contacts, key, "contacts")
        if v and not 9 <= len(re.sub(r"\D", "", v)) <= 15:
            c.err(f"contacts → {key}", f"тут потрібен номер телефону (напр. \"+380671234567\"), а вказано «{v}»")
    for key in ("instagram", "telegram", "tiktok"):
        v = c.text(contacts, key, "contacts")
        if v and ("/" in v or " " in v):
            c.err(f"contacts → {key}", f"вкажіть лише нік без @ і без посилання (вказано «{v}»)")
    email = c.text(contacts, "email", "contacts")
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        c.err("contacts → email", f"не схоже на електронну адресу: «{email}»")
    c.text(contacts, "address", "contacts", required=True)
    coords = contacts.get("coordinates")
    if coords not in (None, "", []):
        ok = (isinstance(coords, list) and len(coords) == 2
              and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in coords)
              and -90 <= coords[0] <= 90 and -180 <= coords[1] <= 180)
        if not ok:
            c.err("contacts → coordinates", "потрібні два числа [широта, довгота], напр. [48.8372, 23.4456]")

    # --- rules ---
    rules = c.section(raw, "rules", dict, required=True)
    c.integer(rules, "prepayment_percent", "rules", required=True, low=0, high=100)
    c.time(rules, "check_in", "rules")
    c.time(rules, "check_out", "rules")
    cancel = rules.get("cancellation")
    if cancel is not None:
        if not isinstance(cancel, dict):
            c.err("rules → cancellation", "має містити поля days і text")
        else:
            c.integer(cancel, "days", "rules → cancellation", low=0, high=365)
            c.text(cancel, "text", "rules → cancellation", required=True)
    for key in ("pets", "smoking", "quiet"):
        c.text(rules, key, "rules")

    # --- objects ---
    objects = c.section(raw, "objects", list, required=True)
    if "objects" in raw and isinstance(raw["objects"], list) and not objects:
        c.err("objects", "потрібен хоча б один об'єкт")
    ids = []
    for i, o in enumerate(objects, 1):
        if not isinstance(o, dict):
            c.err(f"objects №{i}", "кожен об'єкт — це набір полів (id, name, price…)")
            continue
        oid = o.get("id")
        where = f"objects №{i}" + (f" «{o.get('name')}»" if o.get("name") else "")
        if oid in (None, ""):
            c.err(f"{where} → id", "обов'язкове поле, а його немає")
        elif not isinstance(oid, str) or not ID_RE.match(oid):
            c.err(f"{where} → id", f"лише малі латинські літери, цифри й дефіс (напр. big-cottage), а вказано «{oid}». "
                                   f"Якщо id складається з цифр — візьміть його в лапки: \"001\"")
        elif oid in RESERVED_IDS:
            c.err(f"{where} → id", f"«{oid}» зайнято самим сайтом — оберіть інший id")
        elif oid in ids:
            c.err(f"{where} → id", f"id «{oid}» уже використано в іншого об'єкта — id мають бути різні")
        ids.append(oid)
        c.text(o, "name", where, required=True, max_len=60)
        c.text(o, "type", where, max_len=40)
        if not o.get("description"):
            c.warn(where, "немає опису (description) — сторінка об'єкта буде порожньою")
        units = c.integer(o, "units", where, default=1, low=1, high=50)
        c.integer(o, "price", where, required=True, low=1, high=1_000_000)
        base = c.integer(o, "base_guests", where, low=1, high=50)
        top = c.integer(o, "max_guests", where, required=True, low=1, high=50)
        fee = c.integer(o, "extra_guest_price", where, default=0, low=0, high=100_000)
        if _is_int(base) and _is_int(top):
            if base > top:
                c.err(where, f"гостей у базовій ціні (base_guests = {base}) більше, ніж максимум (max_guests = {top})")
            elif base < top and not fee:
                c.warn(where, f"базова ціна — за {base} гостей, максимум {top}, але доплату (extra_guest_price) "
                              f"не вказано — додаткові гості житимуть безкоштовно")
        c.integer(o, "min_nights", where, default=1, low=1, high=30)
        c.integer(o, "bedrooms", where, low=0, high=30)
        c.integer(o, "bathrooms", where, low=0, high=30)
        c.time(o, "check_in", where)
        c.time(o, "check_out", where)
        c.icon(o, where, icons)
        am = o.get("amenities")
        if am is not None and not (isinstance(am, list) and all(isinstance(a, (str, int, float)) for a in am)):
            c.err(f"{where} → amenities", "має бути список рядків (кожен з нового рядка, починається з «- »)")
        tiers = o.get("long_stay")
        if tiers is not None:
            if not isinstance(tiers, list):
                c.err(f"{where} → long_stay", "має бути список: - {nights: 3, price: 4000}")
            else:
                seen = set()
                for t in tiers:
                    if not (isinstance(t, dict) and _is_int(t.get("nights")) and _is_int(t.get("price"))):
                        c.err(f"{where} → long_stay", "кожен рядок: {nights: скільки ночей, price: ціна за ніч}")
                    elif not 2 <= t["nights"] <= 60 or t["price"] < 1:
                        c.err(f"{where} → long_stay", f"nights — від 2 до 60, price — більше 0 (вказано {t})")
                    elif t["nights"] in seen:
                        c.err(f"{where} → long_stay", f"поріг «від {t['nights']} ночей» указано двічі")
                    else:
                        seen.add(t["nights"])
        if check_photos and isinstance(oid, str) and ID_RE.match(oid) and static_dir:
            import gallery
            if not gallery.list_photos(f"{media}/objects/{oid}", static_dir):
                c.warn(where, f"немає фото. Покладіть їх у {media}/objects/{oid}/ і запустіть: python manage.py photos "
                              f"(поки що на сайті буде заглушка)")
    valid_ids = {x for x in ids if isinstance(x, str)}

    # --- extras ---
    extra_ids = []
    for i, e in enumerate(c.section(raw, "extras", list), 1):
        if not isinstance(e, dict):
            c.err(f"extras №{i}", "кожна послуга — це набір полів (id, name, price…)")
            continue
        where = f"extras №{i}" + (f" «{e.get('name')}»" if e.get("name") else "")
        eid = e.get("id")
        if eid in (None, ""):
            c.err(f"{where} → id", "обов'язкове поле, а його немає")
        elif not isinstance(eid, str) or not ID_RE.match(eid):
            c.err(f"{where} → id", f"лише малі латинські літери, цифри й дефіс (напр. chan), а вказано «{eid}»")
        elif eid in extra_ids:
            c.err(f"{where} → id", f"id «{eid}» уже використано в іншої послуги")
        extra_ids.append(eid)
        c.text(e, "name", where, required=True, max_len=60)
        c.integer(e, "price", where, required=True, low=1, high=1_000_000)
        unit = e.get("unit")
        if unit not in (None, "") and unit not in EXTRA_UNITS:
            c.err(f"{where} → unit", f"невідома одиниця «{unit}». Доступні: " +
                  ", ".join(f"{k} ({v})" for k, v in EXTRA_UNITS.items()))
        c.icon(e, where, icons)
        gp = e.get("guest_prices")
        if gp is not None:
            if not isinstance(gp, list):
                c.err(f"{where} → guest_prices", "має бути список: - {up_to: 2, price: 2500}")
            else:
                last = 0
                for t in gp:
                    if not (isinstance(t, dict) and _is_int(t.get("up_to")) and _is_int(t.get("price"))):
                        c.err(f"{where} → guest_prices", "кожен рядок: {up_to: до скількох гостей, price: ціна}")
                    elif t["up_to"] <= last:
                        c.err(f"{where} → guest_prices", f"пороги up_to мають зростати (…{last}, потім {t['up_to']})")
                    elif t["price"] < 1:
                        c.err(f"{where} → guest_prices", f"ціна має бути більша за 0 (вказано {t['price']})")
                    else:
                        last = t["up_to"]

    # --- seasons ---
    spans = []  # (ключ об'єкта або None, початок, кінець, назва)
    for i, s in enumerate(c.section(raw, "seasons", list), 1):
        if not isinstance(s, dict):
            c.err(f"seasons №{i}", "кожен сезон — це набір полів (name, start, end, price…)")
            continue
        where = f"seasons №{i}" + (f" «{s.get('name')}»" if s.get("name") else "")
        c.text(s, "name", where, required=True, max_len=60)
        start, end = parse_date(s.get("start")), parse_date(s.get("end"))
        for key, val in (("start", start), ("end", end)):
            if s.get(key) in (None, ""):
                c.err(f"{where} → {key}", "немає дати")
            elif val is None:
                c.err(f"{where} → {key}", f"неправильна дата «{s.get(key)}». Формат: РРРР-ММ-ДД, напр. 2026-12-30")
        if start and end and end < start:
            c.err(where, f"кінець сезону ({end}) раніше за початок ({start})")
        given = [k for k in ("price", "prices", "on_request") if s.get(k) not in (None, "", False)]
        scopes = []
        if len(given) != 1:
            c.err(where, "вкажіть рівно одне з трьох: price (одна ціна для всіх об'єктів), "
                         "prices (ціна для кожного об'єкта) або on_request: true (ціна за домовленістю)")
        elif given[0] == "price":
            c.integer(s, "price", where, low=1, high=1_000_000)
            scopes = [None]
        elif given[0] == "on_request":
            scopes = [None]
        else:
            prices = s["prices"]
            if not isinstance(prices, dict) or not prices:
                c.err(f"{where} → prices", "має бути у вигляді «id об'єкта: ціна», напр. big: 12000")
            else:
                for key, price in prices.items():
                    key = str(key)
                    if key not in valid_ids:
                        c.err(f"{where} → prices", f"немає об'єкта з id «{key}». Є: {', '.join(sorted(valid_ids)) or '—'}")
                    elif not _is_int(price) or not 1 <= price <= 1_000_000:
                        c.err(f"{where} → prices → {key}", f"ціна має бути цілим числом більше 0 (вказано «{price}»)")
                    else:
                        scopes.append(key)
        if start and end and end >= start:
            for scope in scopes:
                for other in spans:
                    if other[0] == scope and _ranges_overlap((start, end), other[1:3]):
                        what = "для всіх об'єктів" if scope is None else f"для об'єкта «{scope}»"
                        c.err(where, f"сезони перетинаються {what}: {start} – {end} і «{other[3]}» "
                                     f"({other[1]} – {other[2]}). Змініть дати так, щоб вони не накладались")
                spans.append((scope, start, end, s.get("name") or f"№{i}"))

    # --- sections ---
    sections = c.section(raw, "sections", dict)
    for key, v in sections.items():
        if key not in SECTIONS:
            c.warn(f"sections → {key}", f"невідомий блок. Доступні: {', '.join(SECTIONS)}")
        elif not isinstance(v, bool):
            c.err(f"sections → {key}", f"має бути true або false (вказано «{v}»)")

    # --- списки текстів ---
    for i, r in enumerate(c.section(raw, "reviews", list), 1):
        if not isinstance(r, dict):
            c.err(f"reviews №{i}", "кожен відгук — поля text і author")
            continue
        c.text(r, "text", f"reviews №{i}", required=True)
        c.text(r, "author", f"reviews №{i}", required=True)
    for i, q in enumerate(c.section(raw, "faq", list), 1):
        if not isinstance(q, dict):
            c.err(f"faq №{i}", "кожне питання — поля q (питання) та a (відповідь)")
            continue
        c.text(q, "q", f"faq №{i}", required=True)
        c.text(q, "a", f"faq №{i}", required=True)
    for key in ("nearby", "perks"):
        for i, n in enumerate(c.section(raw, key, list), 1):
            if not isinstance(n, dict):
                c.err(f"{key} №{i}", "кожен пункт — поля title і text")
                continue
            c.text(n, "title", f"{key} №{i}", required=True)
            c.icon(n, f"{key} №{i}", icons)
    for key, v in sections.items():
        if v is True and key in ("reviews", "faq", "nearby") and not raw.get(key):
            c.warn(f"sections → {key}", f"блок увімкнено, але список «{key}» порожній — блок не покажеться")

    # --- seo ---
    seo = c.section(raw, "seo", dict)
    c.text(seo, "title", "seo", max_len=90)
    c.text(seo, "description", "seo", max_len=300)
    lang = seo.get("lang")
    if lang not in (None, "") and not re.match(r"^[a-z]{2}(-[A-Z]{2})?$", str(lang)):
        c.err("seo → lang", f"код мови з двох літер, напр. uk (вказано «{lang}»)")
    return c.errors, c.warnings


# ---------- Нормалізація ----------

def _digits(phone):
    return re.sub(r"[^\d+]", "", str(phone or ""))


def _paragraphs(value):
    if isinstance(value, list):
        return [str(p).strip() for p in value if str(p).strip()]
    return [p.strip() for p in re.split(r"\n\s*\n", str(value or "")) if p.strip()]


def plural(n, one, few, many):
    """1 гість, 2 гості, 5 гостей."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def guests_word(n):
    return plural(n, "гість", "гості", "гостей")


def guests_gen(n):
    """Родовий відмінок: для 1 гостя, для 2 гостей."""
    return "гостя" if n % 10 == 1 and n % 100 != 11 else "гостей"


class SiteConfig:
    """Нормалізований конфіг. У шаблонах: site.brand.name, site.contacts.phone, site.objects…"""

    def __init__(self, raw, path):
        self.raw, self.path = raw, path
        self.key = os.path.splitext(os.path.basename(path))[0]      # site / ramshill / blackhouse
        # Корінь фото відносно static/: для site.yaml — media, для інших конфігів — media/examples/<назва>.
        self.media_root = media_root(path)
        g = lambda d, k, default="": (d.get(k) if d.get(k) not in (None, "") else default)  # noqa: E731

        b, s = raw.get("brand") or {}, raw.get("seo") or {}
        name = str(b["name"]).strip()
        self.brand = {
            "name": name, "kind": g(b, "kind"), "tagline": g(b, "tagline"), "description": g(b, "description"),
            "logo": g(b, "logo"), "logo_light": g(b, "logo_light") or g(b, "logo"), "favicon": g(b, "favicon"),
            "theme": b["theme"], "primary_color": g(b, "primary_color"), "accent_color": g(b, "accent_color"),
            "booking_prefix": g(b, "booking_prefix") or _prefix(name),
        }
        self.brand["full_name"] = f"{self.brand['kind']} {name}".strip()

        c = raw.get("contacts") or {}
        coords = c.get("coordinates") or None
        self.contacts = {
            "phone": str(c["phone"]).strip(), "phone_href": _digits(c["phone"]),
            "viber": _digits(g(c, "viber")), "whatsapp": _digits(g(c, "whatsapp")).lstrip("+"),
            "instagram": g(c, "instagram"), "telegram": g(c, "telegram"), "tiktok": g(c, "tiktok"),
            "email": g(c, "email"), "address": g(c, "address"), "region": g(c, "region"),
            "coordinates": coords, "directions": _paragraphs(g(c, "directions")),
        }
        query = f"{coords[0]},{coords[1]}" if coords else f"{self.contacts['address']} {self.contacts['region']}"
        self.contacts["map_query"] = query.strip()

        r = raw.get("rules") or {}
        cancel = r.get("cancellation") or {}
        self.rules = {
            "prepayment_percent": r["prepayment_percent"],
            "check_in": g(r, "check_in", "14:00"), "check_out": g(r, "check_out", "12:00"),
            "cancellation_days": cancel.get("days"), "cancellation_text": g(cancel, "text"),
            "pets": g(r, "pets"), "smoking": g(r, "smoking"), "quiet": g(r, "quiet"),
            "extra": [x for x in (r.get("extra") or []) if isinstance(x, dict) and x.get("title")],
        }

        self.objects = []
        for i, o in enumerate(raw.get("objects") or []):
            paragraphs = _paragraphs(o.get("description"))
            top = o["max_guests"]
            base = min(o.get("base_guests") or top, top)
            self.objects.append({
                "key": o["id"], "slug": o["id"], "folder": f"{self.media_root}/objects/{o['id']}",
                "name": str(o["name"]).strip(), "short": g(o, "short") or str(o["name"]).strip(),
                "type": g(o, "type"), "tagline": g(o, "tagline") or g(o, "type"),
                "intro": paragraphs[0] if paragraphs else "", "description": paragraphs,
                "units": o.get("units") or 1, "price": o["price"], "base_guests": base, "max_guests": top,
                "extra_guest_price": o.get("extra_guest_price") or 0, "min_nights": o.get("min_nights") or 1,
                "tiers": sorted(({"nights": t["nights"], "price": t["price"]} for t in o.get("long_stay") or []),
                                key=lambda t: t["nights"]),
                "bedrooms": o.get("bedrooms"), "bathrooms": o.get("bathrooms"),
                "amenities": [str(a) for a in o.get("amenities") or []],
                "icon": g(o, "icon", "house"), "cover": g(o, "cover"), "featured": bool(o.get("featured")),
                "check_in": g(o, "check_in") or self.rules["check_in"],
                "check_out": g(o, "check_out") or self.rules["check_out"],
                "tone": i % 3 + 1,
            })
        self.object_by_key = {o["key"]: o for o in self.objects}

        self.extras = []
        for e in raw.get("extras") or []:
            unit = g(e, "unit", "evening")
            self.extras.append({
                "key": e["id"], "name": str(e["name"]).strip(), "description": g(e, "description"),
                "price": e["price"], "unit": unit, "unit_label": EXTRA_UNITS[unit],
                "guest_prices": [{"upTo": t["up_to"], "price": t["price"]} for t in e.get("guest_prices") or []],
                "icon": g(e, "icon", "star"), "photo": g(e, "photo") or e["id"],
            })
        self.extra_by_key = {e["key"]: e for e in self.extras}

        # Сезон → рядки для таблиці periods: (ключ об'єкта | None, назва, початок, кінець, ціна | None).
        self.seasons = []
        for s_ in raw.get("seasons") or []:
            start, end = parse_date(s_["start"]).isoformat(), parse_date(s_["end"]).isoformat()
            if s_.get("prices"):
                for key, price in s_["prices"].items():
                    self.seasons.append({"object": str(key), "name": s_["name"], "start": start, "end": end, "price": price})
            else:
                self.seasons.append({"object": None, "name": s_["name"], "start": start, "end": end,
                                     "price": None if s_.get("on_request") else s_["price"]})

        sec = raw.get("sections") or {}
        self.sections = {k: bool(sec.get(k, True)) for k in SECTIONS}
        about = raw.get("about") or {}
        self.about = {"title": g(about, "title"), "text": _paragraphs(about.get("text"))}
        gal = raw.get("gallery") or {}
        self.gallery = {"title": g(gal, "title", "Територія та атмосфера"), "text": g(gal, "text")}
        self.perks = [{"icon": g(p, "icon", "check"), "title": p["title"], "text": g(p, "text")} for p in raw.get("perks") or []]
        self.reviews = [{"text": x["text"], "author": x["author"], "meta": g(x, "meta")} for x in raw.get("reviews") or []]
        self.faq = [{"q": x["q"], "a": x["a"]} for x in raw.get("faq") or []]
        self.nearby = [{"icon": g(n, "icon", "compass"), "title": n["title"], "text": g(n, "text"),
                        "distance": g(n, "distance")} for n in raw.get("nearby") or []]

        self.seo = {
            "title": g(s, "title") or f"{self.brand['full_name']} — {self.brand['tagline']}".rstrip(" —"),
            "description": g(s, "description") or self.brand["description"] or self.brand["tagline"],
            "og_image": g(s, "og_image"), "lang": g(s, "lang", "uk"),
        }
        studio = raw.get("studio") or {}
        self.studio = {"name": g(studio, "name", "Yalott Studio"),
                       "url": g(studio, "url", "https://yalott-studio.netlify.app")}
        # Зарезервовано під v2 (iCal, онлайн-оплата, Telegram-бот). Зараз сайт цей розділ лише зберігає.
        self.integrations = raw.get("integrations") or {}

    def media(self, sub):
        """Папка фото відносно static/: media("hero") → media/hero."""
        return f"{self.media_root}/{sub}"

    def public_rules(self):
        """Те, що потрібно браузеру для розрахунку."""
        return {"prepaymentPercent": self.rules["prepayment_percent"]}


def media_root(path):
    key = os.path.splitext(os.path.basename(path))[0]
    return "media" if key == "site" else f"media/examples/{key}"


def _prefix(name):
    """Префікс коду бронювання з назви: «Ramshill» → RA, «Black House» → BH; кирилиця → BK."""
    words = re.findall(r"[A-Za-z]+", name)
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words and len(words[0]) >= 2:
        return words[0][:2].upper()
    return "BK"


def load(path=None, check_photos=False):
    """Читає, перевіряє й нормалізує конфіг. Якщо є помилки — ConfigError зі списком."""
    path = path or config_path()
    raw = read_yaml(path)
    errors, _warnings = validate(raw, check_photos=check_photos)
    if errors:
        raise ConfigError(path, errors)
    return SiteConfig(raw, path)
