"""Технічне SEO — автоматично для кожного сайту з конфігу клієнта.

  • title (до 60 символів) і meta description (до 160) — унікальні для кожної сторінки:
    назва + тип житла + населений пункт (+ орієнтир із конфігу: «3 км до Буковеля»);
  • canonical, Open Graph і Twitter Card з абсолютними адресами від SITE_URL (.env);
  • schema.org у JSON-LD: LodgingBusiness на головній і в контактах, Accommodation + BreadcrumbList
    на сторінці котеджу. Рейтинг і відгуки — ЛИШЕ якщо в конфігу є справжні дані (rating,
    reviews з оцінкою); заглушки на кшталт «Тут текст відгуку» в розмітку не потрапляють;
  • sitemap.xml і robots.txt;
  • зображення для соцмереж 1200×630 JPEG (/og/<сторінка>.jpg) — його показують Viber, Telegram і Facebook;
  • alt для фото: з підпису (captions.txt) чи назви файлу, інакше «назва котеджу — фото N».

Усе формується з конфігу — під клієнта нічого в коді не змінюється.
"""

import functools
import hashlib
import io
import os
import re
from datetime import date
from xml.sax.saxutils import escape as xml_escape

TITLE_MAX = 60
DESCRIPTION_MAX = 160
OG_SIZE = (1200, 630)
CONTACTS_SLUG = "kontakty"

# Множина для типу житла, коли в конфігу немає brand.kind: «Котедж» → «Котеджі».
PLURAL_TYPES = {"котедж": "Котеджі", "будинок": "Будинки", "будиночок": "Будиночки", "шале": "Шале",
                "апартаменти": "Апартаменти", "хатинка": "Хатинки", "хата": "Хати", "вілла": "Вілли",
                "а-фрейм": "А-фрейми", "глемпінг": "Глемпінг", "садиба": "Садиба", "номер": "Номери"}

_SETTLEMENT = re.compile(r"^(?:смт\.?|с\.|с-ще|селище|село|м\.|місто)\s*", re.I)
_STREET = re.compile(r"^(?:вул\.?|вулиця|просп\.?|проспект|пров\.?|провулок|пл\.?|площа|буд\.?|№)\s|\d", re.I)
_PLACEHOLDER_REVIEW = re.compile(r"тут текст відгуку|ім'я гостя|ім’я гостя|імʼя гостя|lorem ipsum", re.I)

# Що на фото — за словом у назві файлу (латиницею після manage.py photos або англійською).
PHOTO_WORDS = [
    (r"vitaln|living|lounge", "вітальня"), (r"spaln|bedroom|bed\b", "спальня"), (r"kukhn|kitchen", "кухня"),
    (r"sanvuz|bath|wc|dush|shower|vanna", "санвузол"), (r"teras|terrace|balkon|balcon", "тераса"),
    (r"chan\b|chan-|hot-?tub|jacuzzi|dzhakuz", "чан"), (r"bany|sauna|lazn", "баня"), (r"kamin|fireplace", "камін"),
    (r"fasad|facade|exterior|outside|zovni", "будинок зовні"), (r"vyd|view|panoram|hory|mountain", "вид на гори"),
    (r"basein|pool", "басейн"), (r"altank|gazebo|besidk", "альтанка"), (r"dvir|yard|terytor", "територія"),
    (r"zym|winter|snih|snow", "взимку"), (r"nich|night|vechir|evening", "увечері"), (r"snidan|breakfast", "сніданок"),
    (r"stolov|dining|yidaln", "їдальня"), (r"mangal|bbq|grill", "мангал"), (r"lis|forest", "ліс поруч"),
]


# ---------- текст ----------

def clip(text, limit):
    """Обрізає за словом, щоб уміститися в limit символів (з «…»)."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,.;:—–-")
    return cut + "…"


def first_fit(candidates, limit):
    """Перший варіант, що вміщується в limit; якщо жоден — обрізаний останній."""
    options = [" ".join(c.split()) for c in candidates if c and c.strip()]
    for option in options:
        if len(option) <= limit:
            return option
    return clip(options[-1], limit) if options else ""


def join_fit(sentences, limit):
    """Речення одне за одним, поки вміщуються; перше — обрізається, якщо саме задовге."""
    out = ""
    for s in (x.strip() for x in sentences if x and x.strip()):
        s = s if s[-1] in ".!?…" else s + "."
        candidate = f"{out} {s}".strip()
        if len(candidate) <= limit:
            out = candidate
        elif not out:
            return clip(s, limit)
    return out


def _sentence(text):
    return re.split(r"(?<=[.!?…])\s", str(text or "").strip(), maxsplit=1)[0]


# ---------- дані з конфігу ----------

def locality(site):
    """Населений пункт: contacts.locality з конфігу або з адреси («смт Славське, вул. …» → «Славське»)."""
    if site.contacts.get("locality"):
        return site.contacts["locality"]
    parts = [p.strip() for p in str(site.contacts.get("address") or "").split(",") if p.strip()]
    for p in parts:
        if _SETTLEMENT.match(p):
            return _SETTLEMENT.sub("", p).strip()
    for p in parts:
        if not _STREET.match(p):
            return p
    return ""


def kind_label(site):
    """Тип житла для заголовка: brand.kind або множина типу котеджів («Котеджі»)."""
    if site.brand.get("kind"):
        return site.brand["kind"]
    types = {str(o.get("type") or "").strip().lower() for o in site.objects} - {""}
    if len(types) == 1:
        t = types.pop()
        return PLURAL_TYPES.get(t, t[:1].upper() + t[1:])
    return "Котеджі" if not types or "котедж" in types else "Відпочинок"


def real_reviews(site):
    """Відгуки, які можна показати в розмітці: з оцінкою 1–5 і не заглушки."""
    return [r for r in site.reviews if r.get("rating") and not _PLACEHOLDER_REVIEW.search(f"{r['text']} {r['author']}")]


def photo_alt(name, filename, caption=None, index=None):
    """alt фото: «Назва — підпис» / «Назва — що на фото (з назви файлу)» / «Назва — фото N»."""
    if caption:
        caption = caption.strip()
        return caption if name and name.lower() in caption.lower() else (f"{name} — {caption[:1].lower()}{caption[1:]}"
                                                                         if name else caption)
    stem = os.path.splitext(os.path.basename(filename or ""))[0].lower()
    found = []
    for pattern, words in PHOTO_WORDS:
        if re.search(pattern, stem) and words not in found:
            found.append(words)
    if found:
        return f"{name} — {', '.join(found[:2])}" if name else ", ".join(found[:2]).capitalize()
    return f"{name} — фото {index}" if name and index else (name or "Фото")


# ---------- заголовки й описи ----------

def home_meta(site, price_from):
    place, kind, name = locality(site), kind_label(site), site.brand["name"]
    landmark = site.seo.get("landmark", "")
    head = name if kind.lower() in name.lower() else f"{kind} {name}"
    explicit = site.seo.get("title_explicit", "")
    title = first_fit([explicit if len(explicit) <= TITLE_MAX else "",
                       f"{head} — {place}, {landmark}" if place and landmark else "",
                       f"{head} — {place}" if place else "", f"{name} — {place}" if place else "", head, name],
                      TITLE_MAX)
    explicit_d = site.seo.get("description_explicit", "")
    count = len(site.objects)
    offer = (f"{count} {_plural(count, 'варіант', 'варіанти', 'варіантів')} відпочинку від {price_from} грн за ніч"
             if count > 1 else f"Від {price_from} грн за ніч")
    description = clip(explicit_d, DESCRIPTION_MAX) if explicit_d else join_fit(
        [site.brand.get("description") or site.brand.get("tagline"), f"{offer}{', ' + place if place else ''}",
         "Онлайн-бронювання без комісій"], DESCRIPTION_MAX)
    return title, description


def object_meta(site, obj):
    place, name = locality(site), site.brand["name"]
    title = first_fit([f"{obj['name']} — {name}, {place}" if place else "", f"{obj['name']} — {name}",
                       obj["name"]], TITLE_MAX)
    facts = [f"до {obj['max_guests']} {_plural(obj['max_guests'], 'гостя', 'гостей', 'гостей')}"]
    if obj.get("bedrooms"):
        facts.append(f"{obj['bedrooms']} {_plural(obj['bedrooms'], 'спальня', 'спальні', 'спалень')}")
    facts.append(f"від {obj['price_from']} грн за ніч")
    description = join_fit([_sentence(obj.get("intro")) or obj["name"], ", ".join(facts).capitalize(),
                            f"{site.brand['full_name']}{', ' + place if place else ''}"], DESCRIPTION_MAX)
    return title, description


def contacts_meta(site):
    place, name, c = locality(site), site.brand["name"], site.contacts
    title = first_fit([f"Контакти й як доїхати — {name}, {place}" if place else "",
                       f"Контакти — {name}, {place}" if place else "", f"Контакти й як доїхати — {name}",
                       f"Контакти — {name}"], TITLE_MAX)
    address = ", ".join(x for x in (c.get("address"), c.get("region")) if x)
    description = join_fit([f"{site.brand['full_name']}: {address}" if address else site.brand["full_name"],
                            f"Телефон {c['phone']}", _sentence(c["directions"][0]) if c.get("directions") else "",
                            "Карта й маршрут"], DESCRIPTION_MAX)
    return title, description


def _plural(n, one, few, many):
    from site_config import plural
    return plural(n, one, few, many)


# ---------- schema.org (JSON-LD) ----------

def _address(site):
    c, place = site.contacts, locality(site)
    street = ", ".join(p.strip() for p in str(c.get("address") or "").split(",")
                       if p.strip() and not _SETTLEMENT.match(p.strip()) and p.strip() != place)
    out = {"@type": "PostalAddress", "addressCountry": "UA"}
    if street:
        out["streetAddress"] = street
    if place:
        out["addressLocality"] = place
    if c.get("region"):
        out["addressRegion"] = c["region"]
    return out


def lodging(site, base, cards, images):
    """LodgingBusiness для головної й контактів: лише дані з конфігу; рейтинг і відгуки — якщо справжні."""
    c = site.contacts
    prices = [x["price_from"] for x in cards] + [x["price"] for x in cards]
    data = {
        "@context": "https://schema.org", "@type": "LodgingBusiness", "@id": f"{base}/#lodging",
        "name": site.brand["full_name"], "url": f"{base}/",
        "description": clip(site.brand.get("description") or site.brand.get("tagline") or site.brand["full_name"], 300),
        "telephone": c["phone_href"], "address": _address(site),
        "priceRange": f"{min(prices)}–{max(prices)} грн за ніч" if prices else None,
        "currenciesAccepted": "UAH",
        "checkinTime": site.rules.get("check_in"), "checkoutTime": site.rules.get("check_out"),
        "image": images[:6] or None, "email": c.get("email") or None,
    }
    if c.get("coordinates"):
        data["geo"] = {"@type": "GeoCoordinates", "latitude": c["coordinates"][0], "longitude": c["coordinates"][1]}
        data["hasMap"] = f"https://www.google.com/maps?q={c['coordinates'][0]},{c['coordinates'][1]}"
    same_as = [f"https://instagram.com/{c['instagram']}" if c.get("instagram") else None,
               f"https://www.tiktok.com/@{c['tiktok']}" if c.get("tiktok") else None,
               f"https://t.me/{c['telegram']}" if c.get("telegram") else None]
    if any(same_as):
        data["sameAs"] = [x for x in same_as if x]
    if cards:
        data["containsPlace"] = [{"@type": "Accommodation", "name": x["name"], "url": f"{base}/{x['slug']}"}
                                 for x in cards]
    rating = site.rating
    if rating:
        data["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": rating["value"],
                                   "reviewCount": rating["count"], "bestRating": 5, "worstRating": 1}
    reviews = real_reviews(site)
    if reviews:
        data["review"] = [{"@type": "Review", "reviewBody": r["text"], "author": {"@type": "Person", "name": r["author"]},
                           "reviewRating": {"@type": "Rating", "ratingValue": r["rating"], "bestRating": 5},
                           **({"datePublished": r["date"]} if r.get("date") else {})} for r in reviews]
    return {k: v for k, v in data.items() if v not in (None, "", [])}


def accommodation(site, base, obj, images):
    data = {
        "@context": "https://schema.org", "@type": "Accommodation", "@id": f"{base}/{obj['slug']}#accommodation",
        "name": obj["name"], "url": f"{base}/{obj['slug']}",
        "description": clip(" ".join(obj.get("description") or []) or obj.get("intro") or obj["name"], 500),
        "occupancy": {"@type": "QuantitativeValue", "maxValue": obj["max_guests"], "unitText": "гостей"},
        "image": images[:10] or None,
        "containedInPlace": {"@type": "LodgingBusiness", "@id": f"{base}/#lodging", "name": site.brand["full_name"],
                             "address": _address(site), "telephone": site.contacts["phone_href"]},
    }
    if obj.get("bedrooms"):
        data["numberOfBedrooms"] = obj["bedrooms"]
    if obj.get("bathrooms"):
        data["numberOfBathroomsTotal"] = obj["bathrooms"]
    if obj.get("amenities"):
        data["amenityFeature"] = [{"@type": "LocationFeatureSpecification", "name": a, "value": True}
                                  for a in obj["amenities"][:20]]
    return {k: v for k, v in data.items() if v not in (None, "", [])}


def breadcrumbs(base, home_name, items):
    trail = [("/", home_name)] + list(items)
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": name, "item": f"{base}{path}"}
                                for i, (path, name) in enumerate(trail, 1)]}


# ---------- sitemap і robots ----------

def robots_txt(base, closed=False):
    if closed:      # демо: жодної індексації
        return "User-agent: *\nDisallow: /\n"
    return ("User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\nDisallow: /demo/\n\n"
            f"Sitemap: {base}/sitemap.xml\n")


def sitemap_xml(pages):
    """pages: [{"loc": абсолютна адреса, "lastmod": date | None, "images": [абсолютні адреси]}]."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">']
    for p in pages:
        out.append("  <url>")
        out.append(f"    <loc>{xml_escape(p['loc'])}</loc>")
        if p.get("lastmod"):
            out.append(f"    <lastmod>{p['lastmod'].isoformat()}</lastmod>")
        for img in p.get("images", [])[:20]:
            out.append(f"    <image:image><image:loc>{xml_escape(img)}</image:loc></image:image>")
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def lastmod(*paths):
    """Дата останньої зміни файлів (конфіг, фото сторінки) для sitemap."""
    times = []
    for path in paths:
        if os.path.isdir(path):
            times += [os.path.getmtime(os.path.join(path, n)) for n in os.listdir(path)
                      if os.path.isfile(os.path.join(path, n))]
        elif os.path.isfile(path):
            times.append(os.path.getmtime(path))
    return date.fromtimestamp(max(times)) if times else None


# ---------- зображення для соцмереж ----------

def og_image(src_path, cache_dir, focus=""):
    """JPEG 1200×630 з фото (кадрування по центру або за brand.hero_focus «50% 30%»). Шлях до файлу в кеші."""
    stat = os.stat(src_path)
    key = hashlib.sha256(f"{src_path}|{stat.st_mtime_ns}|{stat.st_size}|{focus}|1".encode()).hexdigest()[:32]
    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    target = os.path.join(cache_dir, key + ".jpg")
    if not os.path.exists(target):
        data = _render_og(src_path, focus)
        tmp = f"{target}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    return target


def _render_og(src_path, focus=""):
    from PIL import Image, ImageOps
    m = re.match(r"\s*(\d{1,3})%\s+(\d{1,3})%\s*$", focus or "")
    centering = (min(int(m.group(1)), 100) / 100, min(int(m.group(2)), 100) / 100) if m else (0.5, 0.5)
    with Image.open(src_path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = ImageOps.fit(im, OG_SIZE, Image.LANCZOS, centering=centering)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True, progressive=True)      # без EXIF
    return buf.getvalue()


@functools.lru_cache(maxsize=1024)
def _size(path, mtime):
    from PIL import Image
    with Image.open(path) as im:
        return im.size


def image_size(static_dir, src):
    """(ширина, висота) фото static/<src> або (0, 0)."""
    path = os.path.join(static_dir, src or "")
    try:
        return _size(path, os.path.getmtime(path))
    except Exception:  # noqa: BLE001 — розміри просто не вкажемо
        return (0, 0)
