"""Анкета клієнта в чаті (WhatsApp / Viber / Telegram) → config/site.yaml.

  QUESTIONNAIRE          — повідомлення з 12 питань, яке копіюється клієнту в чат;
  parse_chat(text)       — відповіді «як є», текстом із чату → (дані для конфігу, звіт);
  followup_message(rep)  — готове повідомлення-дозапит лише про те, чого не вистачило.

Розбір — правилами, без зовнішніх сервісів: номери питань, ключові слова, числа, дати, посилання.
Усе, що не вдалося розпізнати певно, позначається в конфігу коментарем:
  «ПЕРЕВІРИТИ: …» — значення взято з чату, але варто глянути;
  «ЗАМІНИТИ: …»   — даних немає, стоїть заглушка (manage.py check не пропустить такий сайт до деплою).
Нерозпізнані шматки відповідей лишаються коментарями в кінці конфігу — нічого не губиться.
"""

import re
from datetime import date

# ---------- опитувальник ----------

QUESTIONS = [
    # (номер, коротка назва для звіту, питання для клієнта)
    (1, "назва й адреса",
     "Як називається ваш заклад (як має бути на сайті) і де він: населений пункт, вулиця?"),
    (2, "котеджі й ціни",
     "Які у вас котеджі? Для кожного одним рядком: назва — скільки таких однакових — до скількох гостей — "
     "ціна за ніч і за скільки гостей вона — доплата за додаткового гостя.\n"
     "Наприклад: «Великий котедж — 2 шт — до 6 гостей — 8500 за 4 гостей — +500 за кожного наступного»"),
    (3, "що є в котеджах",
     "Що є в кожному котеджі? Скільки спалень і санвузлів, камін, кухня, тераса, чан тощо. "
     "Кожен котедж — окремим рядком, починаючи з назви."),
    (4, "святкові ціни",
     "Чи є особливі ціни на свята чи сезон? Напишіть дати й ціну. "
     "Наприклад: «28.12–08.01 — Великий 12000, Маленький 8000» або «на Новий рік — за домовленістю»."),
    (5, "додаткові послуги",
     "Які додаткові послуги є і скільки коштують — чан, баня, сніданки, трансфер? "
     "І за що ціна: за вечір, за людину чи за ніч. Наприклад: «Чан — 2500 за вечір»."),
    (6, "заїзд і виїзд",
     "О котрій заїзд і виїзд? Чи є мінімальна кількість ночей? "
     "Якщо в котеджів різний час — напишіть для кожного."),
    (7, "передоплата й скасування",
     "Яка передоплата (скільки %) і які умови скасування чи перенесення бронювання?"),
    (8, "правила",
     "Які правила: чи можна з тваринами, де можна курити, з котрої години тиша?"),
    (9, "телефон",
     "Номер телефону для гостей. Чи є на ньому Viber, WhatsApp, Telegram?"),
    (10, "соцмережі",
     "Ваш Instagram (та інші соцмережі, якщо є) і email — якщо хочете, щоб вони були на сайті."),
    (11, "як доїхати",
     "Як до вас доїхати? І надішліть, будь ласка, точку на Google Maps (посилання)."),
    (12, "про вас",
     "Коротко: чим ви особливі, 1–3 речення для головної сторінки (краєвид, чан під зорями, тиша…)."),
]
QUESTION_TITLE = {n: title for n, title, _ in QUESTIONS}

QUESTIONNAIRE = (
    "Добрий день! Щоб зробити ваш сайт, дайте, будь ласка, відповіді на кілька питань. "
    "Можна коротко, своїми словами — по одному повідомленню або все разом, головне з номерами питань 🙂\n\n"
    + "\n\n".join(f"{n}. {text}" for n, _, text in QUESTIONS)
    + "\n\nФото надішліть окремо: для кожного котеджу — підпишіть, який це котедж. Дякую!"
)


def followup_message(report):
    """Повідомлення-дозапит клієнту: лише питання, на які не вистачило відповіді."""
    asks = report.get("ask") or []
    if not asks:
        return ""
    lines = ["Дякую за відповіді! Уточніть, будь ласка, ще кілька моментів:", ""]
    lines += [f"{i}. {text}" for i, text in enumerate(asks, 1)]
    return "\n".join(lines)


# ---------- підготовка тексту з чату ----------

# Службові рядки експорту чатів: «[17.11.26, 14:05:32] Олена: …», «17.11.2026, 14:05 - Олена: …»,
# «Олена, [17.11.2026 14:05]» (Telegram), «14:05» окремим рядком (Viber).
_CHAT_PREFIXES = [
    re.compile(r"^\[\d{1,2}[./]\d{1,2}[./]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\]\s*[^:\n]{1,40}:\s?"),
    re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*[-–—]\s*[^:\n]{1,40}:\s?"),
    re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}\s+\d{1,2}:\d{2}\s+[^:\n]{1,40}:\s?"),
]
_CHAT_HEADERS = [
    re.compile(r"^[^\n\[]{1,40},\s*\[\d{1,2}[./]\d{1,2}[./]\d{2,4}\s+\d{1,2}:\d{2}\]\s*$"),
    re.compile(r"^\d{1,2}:\d{2}$"),
    re.compile(r"^(?:<Медіафайли пропущено>|<Media omitted>|Це повідомлення видалено|This message was deleted)$", re.I),
]


def clean_chat(text):
    """Прибирає дати, час і імена з експорту чату; лишає сам текст відповідей."""
    out = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.replace("‎", "").replace("‏", "").replace("\xa0", " ").strip()
        if any(h.match(line) for h in _CHAT_HEADERS):
            continue
        for p in _CHAT_PREFIXES:
            line = p.sub("", line, count=1)
        if any(h.match(line.strip()) for h in _CHAT_HEADERS):
            continue
        out.append(line.rstrip())
    return "\n".join(out).strip()


# Номер питання на початку рядка: «1.», «1)», «1 -», «№1», «1:», «Питання 1».
_QNUM = re.compile(r"^\s*(?:(?:питання\s*|№\s*)(\d{1,2})\s*[.):\-–—]?|(\d{1,2})\s*(?:[.)]|[-–—:]\s))\s*", re.I)


def split_answers(text):
    """{номер питання: текст відповіді}; текст без номера → ключ 0. Повторний номер дописується."""
    sections, current = {}, 0
    for line in text.split("\n"):
        m = _QNUM.match(line)
        if m and 1 <= int(m.group(1) or m.group(2)) <= len(QUESTIONS):
            current = int(m.group(1) or m.group(2))
            line = line[m.end():]
        if line.strip() or sections.get(current):
            sections.setdefault(current, []).append(line)
    return {n: "\n".join(lines).strip() for n, lines in sections.items() if "\n".join(lines).strip()}


# ---------- числа ----------

NUMBER_WORDS = {
    "один": 1, "одна": 1, "одне": 1, "одного": 1, "два": 2, "дві": 2, "двох": 2, "три": 3, "трьох": 3,
    "чотири": 4, "чотирьох": 4, "п'ять": 5, "пʼять": 5, "п’ять": 5, "п'ятьох": 5, "шість": 6, "шести": 6,
    "шістьох": 6, "сім": 7, "семи": 7, "сімох": 7, "вісім": 8, "восьми": 8, "дев'ять": 9, "десять": 10,
}
_NUMBER_WORD_RE = re.compile(r"(?<![\w'ʼ’])(" + "|".join(sorted(map(re.escape, NUMBER_WORDS), key=len, reverse=True))
                             + r")(?![\w'ʼ’])", re.I)


def words_to_digits(text):
    return _NUMBER_WORD_RE.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), text)


# Гроші: «8500», «8 500», «8,5 тис», «8.5к», «2500грн».
_MONEY = re.compile(r"(?<![\d.,:])(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s*(тис\.?|тисяч[іа]?|к|k)?(?![\d:]|\s*%)",
                    re.I)


def money_values(text, minimum=50):
    """Усі суми в тексті з позиціями: [(значення, початок, кінець)]."""
    out = []
    for m in _MONEY.finditer(text):
        raw, thousands = m.group(1), m.group(2)
        try:
            value = float(raw.replace(" ", "").replace(" ", "").replace(",", "."))
        except ValueError:
            continue
        if thousands:
            value *= 1000
        elif "," in raw or "." in raw:
            continue          # 8.5 без «тис» — не ціна
        value = int(round(value))
        if value >= minimum:
            out.append((value, m.start(), m.end()))
    return out


def _blank(text, start, end):
    """Замінює шматок пробілами (щоб позиції решти тексту не зсувались)."""
    return text[:start] + " " * (end - start) + text[end:]


# ---------- телефони, посилання, нікнейми ----------

_PHONE = re.compile(r"(?<!\d)(?:\+?\s*3\s*8\s*)?\(?\s*0\s*\d\s*\d\s*\)?[\s\-.]*\d{3}[\s\-.]*\d{2}[\s\-.]*\d{2}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://\S+")
_NEGATIVE = re.compile(r"\b(?:нема|немає|ні|не\s+маю|не\s+користу|відсутн|no)\b", re.I)


def format_phone(raw):
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0") and len(digits) == 10:
        digits = "38" + digits
    if len(digits) != 12 or not digits.startswith("380"):
        return None
    return f"+{digits[:3]} {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:]}"


def find_phones(text):
    out = []
    for m in _PHONE.finditer(text):
        phone = format_phone(m.group(0))
        if phone and phone not in out:
            out.append(phone)
    return out


def _handle_after(text, words):
    """Нік після слова: «інста: @ramshill», «Instagram ramshill_slavske»."""
    m = re.search(rf"(?:{words})\w*\s*[:\-–—]?\s*@?([A-Za-z0-9_.]{{2,30}})", text, re.I)
    return m.group(1).strip(".") if m else ""


def coordinates_from(text):
    """Координати з посилання Google Maps або з тексту «48.8372, 23.4456»."""
    patterns = (r"@(-?\d{1,2}\.\d{3,}),\s*(-?\d{1,3}\.\d{3,})",
                r"[?&](?:q|ll|query|center|destination)=(-?\d{1,2}\.\d{3,})(?:,|%2C)\s*(-?\d{1,3}\.\d{3,})",
                r"!3d(-?\d{1,2}\.\d{3,})!4d(-?\d{1,3}\.\d{3,})",
                r"(?<![\d.])(4[4-9]\.\d{3,})\s*[,;]\s*(2[2-9]\.\d{3,}|3[0-9]\.\d{3,})(?![\d.])")
    for p in patterns:
        m = re.search(p, text)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return [round(lat, 6), round(lng, 6)]
    return None


# ---------- назви ----------

GENERIC_WORDS = {"котедж", "котеджі", "котеджа", "котеджу", "будинок", "будиночок", "будинку", "шале", "хатинка",
                 "хата", "апартаменти", "номер", "дім", "вілла", "a-frame", "а-фрейм"}
KINDS = ("Приватна садиба", "Еко-садиба", "Гостьовий дім", "База відпочинку", "Садиба", "Котеджі", "Котедж",
         "Шале", "Комплекс", "Еко-комплекс", "Вілла")


def stems(name):
    """Значущі основи слів назви для порівняння: «Великому котеджі» → {"велик"}."""
    words = re.findall(r"[\w'ʼ’-]+", (name or "").lower())
    significant = [w for w in words if w not in GENERIC_WORDS and not w.isdigit() and len(w) >= 3]
    return {w[:5] for w in significant} or {w[:5] for w in words if len(w) >= 3}


def match_object(text, objects):
    """Індекс об'єкта, чия назва згадана на початку тексту, інакше None (і якщо збіг неоднозначний)."""
    head = (text or "")[:60].lower()
    exact = [i for i, o in enumerate(objects) if o["name"].lower() in head]
    if len(exact) == 1:
        return exact[0]
    numbers = set(re.findall(r"\b\d{1,4}\b", head))          # «Котедж 001», «Будинок 2»
    by_number = [i for i, o in enumerate(objects) if numbers & set(re.findall(r"\b\d{1,4}\b", o["name"]))]
    if len(by_number) == 1:
        return by_number[0]
    words = {w[:5] for w in re.findall(r"[\w'ʼ’-]+", head)}
    scores = [(len(stems(o["name"]) & words), i) for i, o in enumerate(objects)]
    best = max(scores, default=(0, None))
    if best[0] and [sc for sc, _ in scores].count(best[0]) == 1:
        return best[1]
    return None


def tidy(text, limit=None):
    """Охайний текст із відповіді клієнта: без зайвих пробілів, з великої літери, з крапкою в кінці."""
    s = " ".join(str(text or "").split()).strip(" -–—:;,")
    if not s:
        return ""
    s = s[0].upper() + s[1:]
    if s[-1] not in ".!?…)»":
        s += "."
    if limit and len(s) > limit:
        cut = s[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        s = cut + "…"
    return s


def _chunks(text):
    """Рядки відповіді; якщо все в одному рядку — ділимо за «;»."""
    lines = [l.strip(" -•*–—\t") for l in text.split("\n")]
    lines = [l for l in lines if l]
    if len(lines) == 1 and ";" in lines[0]:
        lines = [p.strip() for p in lines[0].split(";") if p.strip()]
    return lines


_LIST_HEADER = re.compile(r"^[^:]{0,40}?\b\d{1,2}\s+\w*(?:будин|будиноч|котедж|шале|хат|апарт|номер|послуг)\w*\s*:\s*", re.I)


def _items(text, minimum):
    """Позиції списку: рядки, а рядок із кількома цінами («Дубовий 3500, Сосновий 5000 і ще А-фрейм 2800»)
    ділиться на частини. Заголовок «три будиночки:» відкидається."""
    out = []
    for line in _chunks(text):
        line = _LIST_HEADER.sub("", words_to_digits(line)) if _LIST_HEADER.match(words_to_digits(line)) else line
        if len(money_values(line, minimum)) >= 2:
            parts = [p.strip(" ,;") for p in re.split(r",\s+(?:і\s+(?:ще\s+)?)?|;\s*|\s+і\s+ще\s+|\s+а\s+ще\s+", line)]
            merged = []
            for p in parts:
                # нова позиція — лише частина, що починається з назви й має свою ціну; «до 4 гостей»,
                # «4500 за 2 гостей», «+500 за кожного», «3000 для 3–4» — продовження попередньої
                starts_with_name = re.match(r"[A-Za-zА-Яа-яІіЇїЄєҐґ'ʼ’-]{2,}", p) and not re.match(
                    rf"(?:до|за|на|для|по|з|від|кожн\w*|доплат\w*|додатков\w*|плюс|ціна|{_GUEST})\b", p, re.I)
                if merged and not (starts_with_name and money_values(p, minimum)):
                    merged[-1] += ", " + p
                elif p:
                    merged.append(p)
            out += merged
        else:
            out.append(line)
    return out


# ---------- об'єкти (питання 2) ----------

_GUEST = r"(?:гост\w*|ос(?:і|о)б\w*|ос\.|люд\w*|чол\w*|дорослих|місц\w*|персон\w*|pax)"


def parse_object_line(line):
    """«Великий котедж — 2 шт — до 6 гостей — 8500 за 4 гостей — +500 за кожного наступного» → dict або None."""
    flags = {}
    work = words_to_digits(line)

    units = None
    for p in (r"(?:×|\bx|\bх)\s*(\d{1,2})\b", r"\b(\d{1,2})\s*(?:шт\w*|штук\w*|однаков\w*|таких|одиниц\w*)",
              r"(?:таких|однакових|їх)\s*(?:у нас\s*)?(\d{1,2})\b"):
        m = re.search(p, work, re.I)
        if m:
            units = int(m.group(1))
            work = _blank(work, m.start(), m.end())
            break

    max_guests = None
    for p in (rf"(?:до|макс\w*|максимум|вміщ\w*|розрахован\w* на)\s*(\d{{1,2}})\s*{_GUEST}?",
              r"\b(\d{1,2})\s*[-–]?\s*місн\w*", rf"\b(\d{{1,2}})\s*{_GUEST}(?!\s*(?:у|в)\s*ціні)",
              r"(?:для|на)\s+(\d)\b(?!\s*(?:ноч|доб|діб|шт|тис|к\b|грн|\d))"):
        m = re.search(p, work, re.I)
        if m:
            max_guests = int(m.group(1))
            work = _blank(work, m.start(), m.end())
            break

    extra = None
    m = re.search(r"\+\s*(\d[\d ]{1,6})", work) or re.search(
        r"(?:доплат\w*|додатков\w*\s+(?:гост|ос|люд)\w*|кожн\w+\s+(?:наступн|додатков)\w*)[^\d]{0,25}(\d[\d ]{1,6})",
        work, re.I) or re.search(r"(\d[\d ]{1,6})\s*(?:грн\.?\s*)?(?:за|з)\s+кожн\w+", work, re.I)
    if m:
        extra = int(re.sub(r"\D", "", m.group(1)))
        work = _blank(work, m.start(), m.end())

    base_guests = None
    m = re.search(rf"(?:за|на|для)\s*(\d{{1,2}})\s*(?:-?х\s*)?{_GUEST}", work, re.I) or \
        re.search(rf"(\d{{1,2}})\s*{_GUEST}\s*(?:у|в)\s*ціні", work, re.I)
    if m:
        base_guests = int(m.group(1))
        work = _blank(work, m.start(), m.end())

    prices = [v for v, *_ in money_values(work, minimum=300)]
    price = max(prices) if prices else None
    if len(set(prices)) > 1:
        flags["price"] = f"ПЕРЕВІРИТИ: у чаті кілька сум ({', '.join(map(str, prices))}) — взято найбільшу"

    if price is None and max_guests is None:
        return None

    # назва — текст до першого розділювача («—», «:», кома, дужка); якщо їх немає — до першої ціни чи «до N»
    parts = re.split(r"\s+[-–—]\s+|\s*[–—:]\s*|,\s|\(", line, maxsplit=1)
    name = parts[0]
    name = re.split(r"\s(?:до|за|на|по|для)\s+(?:\d|двох|трьох|чотирьох|п'ятьох|шістьох)|\s(?!0)\d{4,}|\s\d+[,.]?\d*\s*"
                    r"(?:шт|грн|гост|ос|люд|тис|к\b)|\s×", name, maxsplit=1, flags=re.I)[0]
    name = re.sub(r"^\d{1,2}\s+(?=\D)", "", name).strip(" -–—:.")
    m_count = re.match(r"^(один|одна|одне|єдиний)\s+(\w+)$", name, re.I)
    if m_count:
        name = m_count.group(2)
        units = units or 1
    m = re.match(r"(\d{1,2})\s+(\D+)", line.strip())
    if units is None and m and re.search(r"котедж|будин|шале|хат|апарт|номер", m.group(2), re.I):
        units = int(m.group(1))                        # «2 великих котеджі по 8500»
        flags["name"] = "ПЕРЕВІРИТИ: назву взято з «" + line.strip()[:40] + "» — можливо, у множині"
    if not name or len(name) > 60:
        name = ""
    return {"name": name[:1].upper() + name[1:] if name else "", "units": units, "price": price,
            "max_guests": max_guests, "base_guests": base_guests, "extra_guest_price": extra, "_flags": flags,
            "_source": line.strip()}


# ---------- дати сезонів (питання 4) ----------

MONTHS = {"січ": 1, "лют": 2, "бер": 3, "квіт": 4, "трав": 5, "черв": 6, "лип": 7, "серп": 8, "вер": 9,
          "жовт": 10, "лист": 11, "груд": 12}
_MONTH_RE = r"(січ\w*|лют\w*|берез\w*|квіт\w*|трав\w*|черв\w*|лип\w*|серп\w*|верес\w*|жовт\w*|листоп\w*|груд\w*)"
_D1 = r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?"
_D2 = r"(\d{1,2})\s+" + _MONTH_RE


def _month(word):
    word = word.lower()
    for key, n in MONTHS.items():
        if word.startswith(key):
            return n
    return None


def _year(day, month, year, after):
    if year:
        year = int(year)
        return year + 2000 if year < 100 else year
    candidate = date(after.year, month, min(day, 28))
    return after.year if candidate >= date(after.year, after.month, 1) else after.year + 1


def find_date_range(text, today):
    """Перший діапазон дат у тексті → (початок, кінець, початок_позиції, кінець_позиції) або None."""
    numeric = rf"{_D1}\s*(?:[-–—]|по|до)\s*{_D1}"
    m = re.search(numeric, text)
    if m:
        d1, m1, y1, d2, m2, y2 = m.groups()
        parts = (int(d1), int(m1), y1, int(d2), int(m2), y2)
    else:
        m = re.search(rf"(?:з\s+)?(\d{{1,2}})(?:\s+{_MONTH_RE})?\s*(?:[-–—]|по|до)\s*{_D2}", text, re.I)
        if not m:
            return None
        d1, mon1, d2, mon2 = m.groups()
        month2 = _month(mon2)
        parts = (int(d1), _month(mon1) if mon1 else month2, None, int(d2), month2, None)
    d1, m1, y1, d2, m2, y2 = parts
    try:
        start = date(_year(d1, m1, y1, today), m1, d1)
        end = date(_year(d2, m2, y2, today) if y2 else start.year, m2, d2)
        if end < start:
            end = date(end.year + 1, m2, d2)
    except (ValueError, TypeError):
        return None
    return start, end, m.start(), m.end()


SEASON_NAMES = (
    (r"нов\w*\s*р|новоріч|різдв", "Новорічні свята"), (r"травнев", "Травневі свята"), (r"великд", "Великдень"),
    (r"літ", "Літній сезон"), (r"зим", "Зимовий сезон"), (r"свят", "Святкові дні"), (r"сезон", "Високий сезон"),
)


def _season_name(text):
    for pattern, name in SEASON_NAMES:
        if re.search(pattern, text, re.I):
            return name
    return "Святкові дні"


# ---------- головна функція ----------

DEFAULT_CHECK_IN, DEFAULT_CHECK_OUT = "14:00", "12:00"


def _time(text, words):
    m = re.search(rf"(?:{words})\w*[^0-9\n]{{0,20}}?(\d{{1,2}})(?:[:.](\d{{2}}))?", text, re.I)
    if not m or not 0 <= int(m.group(1)) <= 23:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2) or '00'}"


def _min_nights(text):
    m = re.search(r"(?:мін\w*|не менше|від)\s*(\d{1,2})\s*(?:ноч|доб|діб|дн)", words_to_digits(text), re.I)
    return int(m.group(1)) if m else None


def parse_chat(text, today=None, slugify=None):
    """Текст із чату → (d, report). d — дані для manage.render_config; report — що знайдено й чого бракує.

    report: {"found": [рядки], "check": [рядки ⚠], "missing": [рядки ✗], "ask": [питання для дозапиту],
             "sections": {номер: текст}}
    """
    today = today or date.today()
    if slugify is None:
        from manage import slugify
    clean = clean_chat(text)
    sec = split_answers(clean)
    whole = clean
    found, check, missing, ask, unparsed = [], [], [], [], []

    def need(question, what, ask_text):
        missing.append(f"{what} (питання {question} — «{QUESTION_TITLE[question]}»)")
        ask.append(ask_text)

    def part(n):
        return sec.get(n, "")

    d = {"_flags": {}, "kind": "", "tagline": "", "description": "", "theme": "pine", "viber": "", "whatsapp": "",
         "telegram": "", "instagram": "", "tiktok": "", "email": "", "region": "", "coordinates": "",
         "directions": "", "pets": "", "smoking": "", "quiet": ""}
    flags = d["_flags"]
    flags["theme"] = ("ПЕРЕВІРИТИ: тему обирає студія — палітра pine, graphite, terracotta, night, linen, lake, "
                       "birch або ember (порівняти: docs/design/)")

    # 1. назва й адреса
    first = part(1)
    name, address = "", ""
    if first:
        labelled = re.search(r"назва\w*\s*[:\-–—]\s*(.+)", first, re.I)
        addr_labelled = re.search(r"адрес\w*\s*[:\-–—]\s*(.+)", first, re.I)
        if labelled:
            name = labelled.group(1).split("\n")[0]
        if addr_labelled:
            address = addr_labelled.group(1).split("\n")[0]
        if not name:
            head = first.split("\n")[0]
            pieces = re.split(r"\s*[,—–]\s+|\s+-\s+|\.\s+|\n", head, maxsplit=1)
            name = pieces[0]
            if not address:
                rest = first[len(pieces[0]):].strip(" ,.-–—\n")
                address = rest
        name = re.sub(r"^(?:ми\s+)?(?:називаємося|називаємось|назва|це)\s*[:\-–—]?\s*", "", name, flags=re.I)
        name = name.strip(" «»\"'.,")
        address = re.sub(r"^(?:ми\s+)?(?:знаходимося|знаходимось|розташовані|адреса)\s*[:\-–—]?\s*(?:в|у)?\s*", "",
                         address, flags=re.I).strip(" .,")
    if not first:
        quoted = re.search(r"[«\"“„]([^»\"”“\n]{2,40})[»\"”“]", whole)
        if quoted:
            name = quoted.group(1).strip()
            before = whole[max(0, quoted.start() - 30):quoted.start()]
            kind = re.search(r"(садиб\w*|котедж\w*|шале|база\s+відпочинку|гостьов\w*\s+дім)\s*$", before, re.I)
            if kind:
                d["kind"] = {"сади": "Садиба", "коте": "Котеджі", "шале": "Шале", "база": "База відпочинку",
                             "гост": "Гостьовий дім"}[kind.group(1).lower()[:4]]
            d["_flags"]["name"] = "ПЕРЕВІРИТИ: назву взято з лапок у чаті"
        place = re.search(r"\b(?:с\.|смт\.?|м\.|село|селище|місто)\s*[А-ЯІЇЄҐ][\w'ʼ’-]+(?:,\s*(?:вул\.?|вулиця)\s*[^,\n]+)?", whole)
        if place:
            address = place.group(0).strip(" ,.")
            d["_flags"]["address"] = "ПЕРЕВІРИТИ: лише населений пункт — уточніть вулицю"
    for kind in KINDS:
        if name.lower().startswith(kind.lower() + " ") and len(name) > len(kind) + 1:
            d["kind"], name = kind, name[len(kind):].strip(" «»\"")
            break
    m = re.search(r"(\w+(?:ськ|цьк|зьк)\w*)\s+обл\w*\.?", whole, re.I)
    if m:
        d["region"] = re.sub(r"(ськ|цьк|зьк)\w*$", r"\1а", m.group(1).lower()).capitalize() + " область"
        address = re.sub(r",?\s*" + re.escape(m.group(1)) + r"\s+обл\w*\.?", "", address).strip(" ,.")
    if name:
        d["name"] = name[:60]
        found.append(f"Назва: {d['name']}" + (f" ({d['kind']})" if d["kind"] else ""))
    else:
        d["name"] = "Назва"
        flags["name"] = "ЗАМІНИТИ: назву не знайдено"
        need(1, "назва закладу", "Як точно має називатися ваш заклад на сайті?")
    if address:
        d["address"] = address[:120]
        found.append(f"Адреса: {d['address']}")
    else:
        d["address"] = "ЗАМІНИТИ: адреса"
        need(1, "адреса", "Яка точна адреса (населений пункт, вулиця, номер)?")

    # 2. котеджі
    objects, raw_objects = [], []
    source2 = part(2) or ("\n".join(l for l in _chunks(whole) if re.search(r"котедж|будин|шале|апарт|хат|фрейм", l, re.I)
                                    and money_values(l, 300) and not find_date_range(l, today)))
    for line in _items(source2, 300):
        o = parse_object_line(line)
        if o:
            raw_objects.append(o)
        elif part(2):
            unparsed.append(("питання 2", line))
    for i, o in enumerate(raw_objects, 1):
        f = o["_flags"]
        if not o["name"]:
            o["name"] = f"Котедж {i}"
            f["name"] = "ЗАМІНИТИ: назву котеджу не розпізнано"
            need(2, f"назва котеджу №{i}", f"Як називається котедж №{i}? ({o['_source'][:50]})")
        if o["price"] is None:
            f["price"] = "ЗАМІНИТИ: ціну не розпізнано"
            need(2, f"ціна «{o['name']}»", f"Скільки коштує ніч у «{o['name']}» і за скільки гостей ця ціна?")
            o["price"] = 1
        if o["max_guests"] is None:
            o["max_guests"] = o["base_guests"] or 2
            f["max_guests"] = "ЗАМІНИТИ: максимум гостей не розпізнано"
            need(2, f"максимум гостей «{o['name']}»", f"На скільки гостей максимум розрахований «{o['name']}»?")
        if o["base_guests"] is None:
            o["base_guests"] = o["max_guests"]
            if o["extra_guest_price"]:
                f["base_guests"] = "ПЕРЕВІРИТИ: не сказано, за скільки гостей ціна"
                need(2, f"скільки гостей у ціні «{o['name']}»", f"Ціна «{o['name']}» — за скількох гостей?")
            else:
                f["base_guests"] = "ПЕРЕВІРИТИ: ціна за весь котедж (доплати за гостей не згадано)"
        o["base_guests"] = min(o["base_guests"], o["max_guests"])
        if o["extra_guest_price"] is None:
            o["extra_guest_price"] = 0
            if o["base_guests"] < o["max_guests"]:
                f["extra_guest_price"] = "ПЕРЕВІРИТИ: доплату за додаткового гостя не згадано"
                need(2, f"доплата за гостя «{o['name']}»",
                     f"Чи є доплата за кожного гостя понад {o['base_guests']} у «{o['name']}» і скільки?")
        if o["units"] is None:
            o["units"] = 1
        base_id = slugify(o["name"]) or f"cottage-{i}"
        oid, n = base_id, 2
        while oid in {x["id"] for x in objects} or oid in {"admin", "api", "static", "media"}:
            oid, n = f"{base_id}-{n}", n + 1
        objects.append({"id": oid, "name": o["name"], "type": "Котедж", "tagline": "", "description": "",
                        "units": o["units"], "price": o["price"], "base_guests": o["base_guests"],
                        "max_guests": o["max_guests"], "extra_guest_price": o["extra_guest_price"], "min_nights": 1,
                        "bedrooms": None, "bathrooms": None, "check_in": DEFAULT_CHECK_IN,
                        "check_out": DEFAULT_CHECK_OUT, "amenities": [], "_flags": f})
        found.append(f"Котедж «{o['name']}»" + (f" × {o['units']}" if o["units"] > 1 else "")
                     + f": {o['price']} грн/ніч за {o['base_guests']}, до {o['max_guests']} гостей"
                     + (f", +{o['extra_guest_price']} за гостя" if o["extra_guest_price"] else ""))
    if not objects:
        objects.append({"id": "cottage", "name": "Котедж", "type": "Котедж", "tagline": "", "description": "",
                        "units": 1, "price": 1, "base_guests": 2, "max_guests": 2, "extra_guest_price": 0,
                        "min_nights": 1, "bedrooms": None, "bathrooms": None, "check_in": DEFAULT_CHECK_IN,
                        "check_out": DEFAULT_CHECK_OUT, "amenities": [],
                        "_flags": {"name": "ЗАМІНИТИ: котеджі не розпізнано", "price": "ЗАМІНИТИ: ціна"}})
        need(2, "котеджі й ціни", QUESTIONS[1][2])
    d["objects"] = objects

    # 3. що є в котеджах
    lines3 = _chunks(part(3))
    for idx, line in enumerate(lines3):
        i = match_object(line, objects)
        if i is None and len(lines3) == len(objects):
            i = idx
        targets = [objects[i]] if i is not None else objects
        body = line
        if i is not None:
            body = re.sub(r"^[^:\-–—]{1,40}[:\-–—]\s*", "", line) if re.match(r"^[^:\-–—]{1,40}[:\-–—]", line) else line
        body_n = words_to_digits(body)
        bedrooms = re.search(r"(\d{1,2})\s*спал\w*", body_n, re.I)
        bathrooms = re.search(r"(\d{1,2})\s*(?:санвузл|с/в|ванн|туалет)\w*", body_n, re.I)
        items = [tidy(x).rstrip(".") for x in re.split(r"[,;]|\s+і\s+|\s+та\s+", body) if x.strip()]
        items = [x for x in items if x and not re.match(r"^\d{1,2}\s*(?:спал|санвуз|с/в|ванн)", words_to_digits(x), re.I)]
        for o in targets:
            if bedrooms:
                o["bedrooms"] = int(bedrooms.group(1))
            if bathrooms:
                o["bathrooms"] = int(bathrooms.group(1))
            o["amenities"] += [x for x in items if x not in o["amenities"]][:15]
            if i is None and len(objects) > 1:
                o["_flags"]["amenities"] = "ПЕРЕВІРИТИ: незрозуміло, до якого котеджу рядок — додано до всіх"
    if lines3:
        found.append("Зручності: " + "; ".join(f"{o['name']} — {len(o['amenities'])}" for o in objects))
    else:
        need(3, "що є в котеджах", "Що є в кожному котеджі (спальні, санвузли, камін, кухня, тераса)?")

    # 4. сезони
    seasons = []
    text4 = part(4)
    source4 = text4 or "\n".join(l for l in _chunks(whole) if find_date_range(l, today))
    if text4 and re.fullmatch(r"\W*(?:ні|немає|нема|не має|без|однакові|ціни однакові)\W*.*", text4, re.I | re.S) \
            and not find_date_range(text4, today):
        found.append("Святкових цін немає")
    else:
        for line in _chunks(source4):
            rng = find_date_range(line, today)
            if not rng:
                if text4 and re.search(r"\d", line):
                    unparsed.append(("питання 4", line))
                continue
            start, end, a, b = rng
            rest = _blank(line, a, b)
            season = {"name": _season_name(line), "start": start.isoformat(), "end": end.isoformat(), "_flags": {}}
            if re.search(r"домовл|договір|договірн|уточню", rest, re.I) and not money_values(rest, 300):
                season["on_request"] = True
            else:
                per_object = {}
                for piece in re.split(r"[,;/]|\s+і\s+", rest):
                    i = match_object(piece.strip(" -–—:"), objects)
                    vals = money_values(piece, 300)
                    if i is not None and vals:
                        per_object[objects[i]["id"]] = vals[0][0]
                prices = money_values(rest, 300)
                if per_object:
                    season["prices"] = per_object
                elif len(prices) == 1:
                    if len(objects) == 1:
                        season["prices"] = {objects[0]["id"]: prices[0][0]}
                    else:
                        season["price"] = prices[0][0]
                        season["_flags"]["price"] = "ПЕРЕВІРИТИ: одна ціна — поставлено для всіх котеджів"
                elif prices and len(prices) == len(objects):
                    season["prices"] = {o["id"]: p[0] for o, p in zip(objects, prices)}
                    season["_flags"]["prices"] = "ПЕРЕВІРИТИ: ціни розставлено за порядком котеджів"
                else:
                    season["on_request"] = True
                    season["_flags"]["name"] = "ЗАМІНИТИ: ціну сезону не розпізнано — стоїть «за домовленістю»"
                    need(4, f"ціна на {season['name']}", f"Яка ціна з {start:%d.%m} по {end:%d.%m} для кожного котеджу?")
            if start.year != end.year or (end - start).days > 120:
                season["_flags"]["dates"] = f"ПЕРЕВІРИТИ: {start:%d.%m.%Y} – {end:%d.%m.%Y}"
            if any(s["start"] <= season["end"] and season["start"] <= s["end"] for s in seasons):
                unparsed.append(("питання 4 (перетин дат)", line))
                continue
            seasons.append(season)
            what = "за домовленістю" if season.get("on_request") else \
                ", ".join(f"{k} {v}" for k, v in season.get("prices", {}).items()) or str(season.get("price"))
            found.append(f"Сезон «{season['name']}» {start:%d.%m.%Y}–{end:%d.%m.%Y}: {what}")
        if not text4 and not seasons:
            need(4, "святкові ціни", "Чи є особливі ціни на свята (Новий рік, травневі)? Якщо так — дати й ціни.")
    d["seasons"] = seasons

    # 5. послуги
    extras = []
    known = r"чан|баня|бан[іь]|сауна|сніданок|сніданк|обід|вечер|трансфер|квадро|риболов|мангал|дрова|джакузі|купіль|масаж|прокат|екскурс"
    text5 = part(5)
    source5 = text5 or "\n".join(l for l in _chunks(whole) if re.search(known, l, re.I) and money_values(l, 50))
    if text5 and re.fullmatch(r"\W*(?:ні|немає|нема|не має|без)\W*", text5, re.I):
        found.append("Додаткових послуг немає")
    else:
        for line in _items(source5, 50):
            vals = money_values(line, 50)
            if not vals:
                if text5:
                    unparsed.append(("питання 5", line))
                continue
            name = re.split(r"\s+[-–—:]\s+|\s*[-–—:]\s+|\s\d|\(", line, maxsplit=1)[0].strip(" -–—:")
            if not name or len(name) > 40:
                unparsed.append(("питання 5", line))
                continue
            e = {"id": slugify(name) or f"extra-{len(extras) + 1}", "name": tidy(name).rstrip("."), "description": "",
                 "guest_prices": [], "_flags": {}}
            tiers = re.findall(rf"(\d[\d ]{{1,6}})\s*(?:грн\.?)?\s*(?:для|за|на|\()\s*(?:до\s*)?(\d{{1,2}})"
                               rf"(?:\s*[-–]\s*(\d{{1,2}}))?\s*{_GUEST}?", words_to_digits(line), re.I)
            if len(tiers) >= 2:
                e["guest_prices"] = sorted(({"up_to": int(c or b), "price": int(re.sub(r"\D", "", a))}
                                            for a, b, c in tiers), key=lambda t: t["up_to"])
                e["price"] = e["guest_prices"][-1]["price"]
            else:
                e["price"] = vals[0][0]
            low = line.lower()
            per_person = re.search(r"(?:за|з|на)\s+(?:1\s+)?(?:люд|ос[іо]б|гост|персон|чол)", low)
            per_night = re.search(r"(?:за|на)\s+(?:1\s+)?(?:ніч|доб|день)", low)
            if per_person and (per_night or re.search(r"сніданк|сніданок|харчув", low)):
                e["unit"] = "person_night"
                if not per_night:
                    e["_flags"]["unit"] = "ПЕРЕВІРИТИ: сніданок рахується за людину за кожну ніч"
            elif per_person:
                e["unit"] = "person"
            elif per_night:
                e["unit"] = "night"
            elif re.search(r"вечір|сеанс|чан|бан|саун|джакузі|купіл", low):
                e["unit"] = "evening"
            else:
                e["unit"] = "once"
                e["_flags"]["unit"] = "ПЕРЕВІРИТИ: одиницю ціни не названо — «за бронювання»"
            base, n = e["id"], 2
            while e["id"] in {x["id"] for x in extras}:
                e["id"], n = f"{base}-{n}", n + 1
            extras.append(e)
            tiers_text = ", ".join(f"до {t['up_to']} — {t['price']}" for t in e["guest_prices"])
            found.append(f"Послуга «{e['name']}»: {tiers_text or e['price']} ({e['unit']})")
        if not text5 and not extras:
            need(5, "додаткові послуги", "Чи є додаткові послуги (чан, баня, сніданки, трансфер) і скільки коштують?")
    d["extras"] = extras

    # 6. заїзд, виїзд, мінімум ночей
    text6 = part(6) or "\n".join(l for l in _chunks(whole) if re.search(r"заїзд|виїзд|заселен|виселен", l, re.I))
    check_in = _time(text6, r"заїзд|заселен|check-?in|приїзд")
    check_out = _time(text6, r"виїзд|виселен|check-?out|від'?їзд")
    d["check_in"], d["check_out"] = check_in or DEFAULT_CHECK_IN, check_out or DEFAULT_CHECK_OUT
    for line in _chunks(text6):
        i = match_object(line, objects) if len(objects) > 1 else None
        if i is not None:
            objects[i]["check_in"] = _time(line, r"заїзд|заселен|check-?in|приїзд") or objects[i]["check_in"]
            objects[i]["check_out"] = _time(line, r"виїзд|виселен|check-?out|від'?їзд") or objects[i]["check_out"]
            nights = _min_nights(line)
            if nights:
                objects[i]["min_nights"] = nights
    if not any(match_object(l, objects) is not None for l in _chunks(text6)) or len(objects) == 1:
        for o in objects:
            o["check_in"], o["check_out"] = d["check_in"], d["check_out"]
    nights = _min_nights(text6)
    if nights and not any(match_object(l, objects) is not None for l in _chunks(text6) if _min_nights(l)):
        for o in objects:
            o["min_nights"] = nights
    if check_in and check_out:
        times = sorted({(o["check_in"], o["check_out"]) for o in objects})
        found.append("Заїзд/виїзд: " + "; ".join(f"{a}/{b}" for a, b in times)
                     + (f", мінімум ночей: {nights}" if nights else ""))
    else:
        for key, value in (("check_in", check_in), ("check_out", check_out)):
            if not value:
                flags[key] = "ПЕРЕВІРИТИ: не сказано — стоїть типовий час"
        need(6, "час заїзду/виїзду", "О котрій заїзд і до котрої виїзд?")

    # 7. передоплата й скасування
    text7 = part(7) or "\n".join(l for l in _chunks(whole) if re.search(r"передоплат|скасуван|завдат|аванс", l, re.I))
    m = re.search(r"(\d{1,3})\s*(?:%|відсот)", text7) or re.search(r"(?:передоплат|завдат|аванс)\w*[^\d\n]{0,15}(\d{1,3})\b", text7, re.I)
    if m and int(m.group(1)) <= 100:
        d["prepayment"] = int(m.group(1))
    elif re.search(r"половин", text7, re.I):
        d["prepayment"] = 50
    elif re.search(r"без\s+передоплат|передоплат\w*\s+(?:немає|не\s+бер)", text7, re.I):
        d["prepayment"] = 0
    else:
        d["prepayment"] = 30
        flags["prepayment"] = "ЗАМІНИТИ: передоплату не названо (стоїть 30%)"
        need(7, "передоплата", "Яку передоплату ви берете (скільки відсотків)?")
    if "prepayment" not in flags:
        found.append(f"Передоплата: {d['prepayment']}%")
    days = re.search(r"(?:за|до|не\s+пізніше\s+ніж\s+за)\s*(\d{1,3})\s*(?:\+\s*)?(?:дн|діб|доб)", words_to_digits(text7), re.I)
    d["cancel_days"] = int(days.group(1)) if days else 7
    cancel = re.sub(r"[^.\n]*(?:передоплат|завдат|аванс)[^.\n]*?\d{1,3}\s*(?:%|відсот\w*)[^.\n]*[.\n]?", "", text7,
                    flags=re.I).strip()
    if cancel and re.search(r"скасу|перенес|поверт|відмов", cancel, re.I):
        d["cancel_text"] = tidy(cancel, 300)
        flags["cancel_text"] = "ПЕРЕВІРИТИ: текст клієнта — за потреби відредагуйте"
        found.append(f"Скасування: {d['cancel_text'][:70]}")
    else:
        d["cancel_text"] = (f"Якщо попередити не пізніше ніж за {d['cancel_days']} днів до заїзду — перенесемо дати. "
                            f"Пізніше передоплата не повертається.")
        flags["cancel_text"] = "ЗАМІНИТИ: умови скасування не названо — стоїть типовий текст"
        need(7, "умови скасування", "Які умови скасування чи перенесення бронювання (за скільки днів)?")
    if not days:
        flags["cancel_days"] = "ПЕРЕВІРИТИ: кількість днів не названо"

    # 8. правила
    text8 = part(8)
    for piece in re.split(r"(?<=[.!?;\n])\s*|,\s+(?=[а-яіїєґ]+\s)", text8):
        piece = piece.strip(" ,;")
        if not piece:
            continue
        low = piece.lower()
        if re.search(r"твар|собак|кіт|котик|пес|песик|pet", low) and not d["pets"]:
            d["pets"] = tidy(piece, 150)
        elif re.search(r"кур|сигар|вейп|кальян", low) and not d["smoking"]:
            d["smoking"] = tidy(piece, 150)
        elif re.search(r"тиш|шум|гучн", low) and not d["quiet"]:
            d["quiet"] = tidy(piece, 150)
        elif text8:
            unparsed.append(("питання 8", piece))
    if text8:
        found.append("Правила: " + ", ".join(k for k, v in (("тварини", d["pets"]), ("куріння", d["smoking"]),
                                                             ("тиша", d["quiet"])) if v))
    else:
        need(8, "правила (тварини, куріння, тиша)", "Чи можна з тваринами, де можна курити, з котрої години тиша?")

    # 9–10. контакти (телефон і посилання шукаємо в усьому чаті)
    text9 = part(9)
    phones = find_phones(text9) or find_phones(whole)
    if phones:
        d["phone"] = phones[0]
        found.append(f"Телефон: {d['phone']}")
        if len(phones) > 1:
            flags["phone"] = "ПЕРЕВІРИТИ: у чаті кілька номерів — " + ", ".join(phones[:3])
    else:
        d["phone"] = "+380 00 000 00 00"
        flags["phone"] = "ЗАМІНИТИ: телефон не знайдено"
        need(9, "телефон для гостей", "Який номер телефону показувати гостям на сайті?")
    messenger_text = text9 or whole
    for key, word in (("viber", r"viber|вайбер|вайбері|вібер"), ("whatsapp", r"whats\s*app|вотсап|ватсап|вацап")):
        m = re.search(rf"(?:[^.\n]{{0,25}})(?:{word})(?:[^.\n,]{{0,15}})", messenger_text, re.I)
        all_msg = re.search(r"(?:усі|всі|всюди|скрізь)\s*(?:месенджер|є)", messenger_text, re.I)
        if (m and not _NEGATIVE.search(m.group(0))) or all_msg:
            d[key] = (phones[0] if phones else "")
            found.append(f"{key.capitalize()}: {d[key] or 'так, але номер не знайдено'}")
    social = part(10) or whole
    for key, pattern, host in (("instagram", r"інст|insta|instagram|інстаграм", "instagram.com"),
                               ("tiktok", r"tik\s*tok|тікток|тік-ток", "tiktok.com"),
                               ("telegram", r"telegram|телеграм|тг\b", "t.me")):
        m = re.search(rf"{re.escape(host)}/@?([A-Za-z0-9_.]{{2,30}})", social, re.I)
        handle = m.group(1).strip(".") if m else _handle_after(social, pattern)
        if handle and handle.lower() not in {"немає", "нема", "ні", "є", "так", "теж", "також"} and \
                re.fullmatch(r"[A-Za-z0-9_.]{2,30}", handle):
            d[key] = handle
            found.append(f"{key.capitalize()}: {handle}")
    if not d["instagram"]:
        m = re.search(r"(?<![\w.])@([A-Za-z0-9_.]{3,30})(?![\w.@])", part(10))
        if m:
            d["instagram"] = m.group(1)
            flags["instagram"] = "ПЕРЕВІРИТИ: нік без назви соцмережі — вважаю, що це Instagram"
            found.append(f"Instagram: {d['instagram']}")
    if re.search(r"telegram|телеграм", text9, re.I) and not d["telegram"] and not _NEGATIVE.search(text9):
        flags["telegram"] = "ПЕРЕВІРИТИ: Telegram є, але потрібен нік (без нього кнопки не буде)"
        ask.append("Який у вас нік у Telegram (як @nickname)? Без нього кнопки Telegram на сайті не буде.")
    emails = _EMAIL.findall(part(10) or whole)
    if emails:
        d["email"] = emails[0]
        found.append(f"Email: {d['email']}")

    # 11. як доїхати
    text11 = part(11)
    coords = coordinates_from(text11 or whole)
    if coords:
        d["coordinates"] = f"[{coords[0]}, {coords[1]}]"
        found.append(f"Координати: {coords[0]}, {coords[1]}")
    else:
        links = [u for u in _URL.findall(text11 or whole) if re.search(r"goo\.gl|google\.\w+/maps|maps\.app", u)]
        if links:
            flags["coordinates"] = ("ЗАМІНИТИ: з короткого посилання координати не видно — відкрийте "
                                    f"{links[0][:60]} у браузері, клацніть на точці й скопіюйте координати")
            missing.append("координати (посилання є, але коротке — див. коментар у конфігу)")
        else:
            need(11, "точка на карті", "Надішліть, будь ласка, точку на Google Maps — посилання на ваше розташування.")
    directions = _URL.sub("", text11).strip(" \n")
    if directions:
        d["directions"] = "\n\n".join(tidy(p, 400) for p in re.split(r"\n\s*\n|\n", directions) if p.strip())
        found.append("Як доїхати: є")
    else:
        need(11, "як доїхати", "Як до вас доїхати (автівкою, потягом)? Кількома реченнями для гостей.")

    # 12. опис
    text12 = part(12)
    if text12:
        d["description"] = tidy(text12, 300)
        first_sentence = re.split(r"(?<=[.!?…])\s", d["description"], maxsplit=1)[0]
        d["tagline"] = first_sentence.rstrip(".")[:90] if len(first_sentence) <= 90 else ""
        found.append(f"Опис: {d['description'][:70]}…" if len(d["description"]) > 70 else f"Опис: {d['description']}")
        flags["description"] = "ПЕРЕВІРИТИ: текст клієнта — відредагуйте під сайт"
    else:
        d["description"] = f"{d['name']} — затишний відпочинок у Карпатах."
        flags["description"] = "ЗАМІНИТИ: опису немає — стоїть заглушка"
        need(12, "опис для головної", "Напишіть, будь ласка, 1–3 речення: чим ваш заклад особливий?")
    if not d["tagline"]:
        d["tagline"] = "Котеджі в Карпатах"
        flags["tagline"] = "ПЕРЕВІРИТИ: слоган-заглушка"
    for o in objects:
        if not o["description"]:
            o["description"] = f"{o['name']} — {('до ' + str(o['max_guests']) + ' гостей') if o['max_guests'] else 'затишний котедж'}."
            o["_flags"]["description"] = "ПЕРЕВІРИТИ: короткий опис-заглушка — допишіть"

    d["seo_title"] = f"{(d['kind'] + ' ') if d['kind'] else ''}{d['name']} — {d['tagline']}"[:90]

    # без номера питання — у звіт і в кінець конфігу
    if sec.get(0):
        leftover = re.sub(r"(?im)^\W*(?:добр\w+\s+(?:день|ранок|вечір)|вітаю|привіт|доброго\s+дня|дякую|відповідаю"
                          r"|ось|ось відповіді|відповіді)\W*(?:(?:добр\w+\s+(?:день|ранок|вечір)|вітаю|відповідаю)\W*)*$",
                          "", sec[0])
        for value in [d.get("phone"), d.get("email")] + phones:
            if value:
                leftover = leftover.replace(value, "")
        if leftover.strip() and any(sec.get(n) for n in range(1, 13)):
            unparsed.append(("без номера питання", leftover.strip()[:500]))
    d["_unparsed"] = unparsed

    for o in objects:
        for key, text in o["_flags"].items():
            (missing if text.startswith("ЗАМІНИТИ") else check).append(f"{o['name']} → {key}: {text.split(': ', 1)[1]}")
    for e in extras:
        for key, text in e["_flags"].items():
            check.append(f"Послуга {e['name']} → {key}: {text.split(': ', 1)[1]}")
    for s in seasons:
        for key, text in s["_flags"].items():
            (missing if text.startswith("ЗАМІНИТИ") else check).append(f"Сезон {s['name']} → {key}: {text.split(': ', 1)[1]}")
    for key, text in flags.items():
        if text.startswith("ПЕРЕВІРИТИ") and key != "theme":
            check.append(f"{key}: {text.split(': ', 1)[1]}")
    answered = sorted(n for n in sec if n)
    report = {"found": found, "check": check, "missing": _dedupe(missing), "ask": _dedupe(ask),
              "unparsed": unparsed, "answered": answered,
              "unanswered": [n for n, *_ in QUESTIONS if n not in sec]}
    return d, report


def _dedupe(items):
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out
