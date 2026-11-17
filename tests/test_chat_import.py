"""Анкета в чаті → конфіг: опитувальник, розбір відповідей «як є», звіт і дозапит, команди manage.py."""

import os
import re
from datetime import date

import pytest

import chat_import as C
import manage
import site_config
from conftest import ROOT

FIXTURES = os.path.join(ROOT, "tests", "fixtures", "chats")
TODAY = date(2026, 11, 17)


def chat(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def parse(name):
    return C.parse_chat(chat(name), today=TODAY, slugify=manage.slugify)


def to_config(data, tmp_path, name="site.yaml"):
    """Розібрані дані → файл конфігу → SiteConfig (той самий шлях, що й у manage.py from-chat)."""
    path = tmp_path / name
    path.write_text(manage.render_config(data, source="test"), encoding="utf-8")
    errors, _ = site_config.validate(site_config.read_yaml(str(path)), check_photos=False)
    assert errors == [], errors
    return site_config.load(str(path)), path.read_text(encoding="utf-8")


# ---------- опитувальник ----------

def test_questionnaire_is_short_numbered_and_plain():
    numbers = [int(n) for n in re.findall(r"(?m)^(\d{1,2})\. ", C.QUESTIONNAIRE)]
    assert numbers == list(range(1, 13))                       # не більше 12 питань, по порядку
    for n, _, text in C.QUESTIONS:
        assert len(text) < 320, n                              # коротко, щоб клієнт не злякався
        assert not re.search(r"[{}<>`]|config|yaml|base_guests", text, re.I), n   # жодних технічних слів
    assert "фото" in C.QUESTIONNAIRE.lower()


def test_questionnaire_copy_in_docs_is_up_to_date():
    with open(os.path.join(ROOT, "docs", "anketa-dlya-klienta.txt"), encoding="utf-8") as f:
        assert f.read().strip() == C.QUESTIONNAIRE.strip(), "оновіть: python manage.py anketa > docs/anketa-dlya-klienta.txt"


# ---------- текст із чату ----------

def test_chat_prefixes_removed():
    text = ("[17.11.26, 14:02:40] Олена: 1) Ramshill\n"
            "17.11.2026, 14:03 - Олена Петрівна: 2. Котедж\n"
            "Олена, [17.11.2026 14:05]\n9 - 0671234567\n"
            "14:07\n10: @ramshill\n"
            "[17.11.26, 14:09:15] Олена: <Медіафайли пропущено>")
    assert C.clean_chat(text) == "1) Ramshill\n2. Котедж\n9 - 0671234567\n10: @ramshill"


def test_answers_split_by_question_number():
    sec = C.split_answers("Привіт\n1. Назва\n2) Котедж\nдругий рядок\n№5 Чан 2000\n9 - 0671234567\n13. не питання")
    assert sec == {0: "Привіт", 1: "Назва", 2: "Котедж\nдругий рядок", 5: "Чан 2000", 9: "0671234567\n13. не питання"}


@pytest.mark.parametrize("text, expected", [
    ("8500", [8500]), ("8 500 грн", [8500]), ("8,5 тис", [8500]), ("3.5к", [3500]), ("5 тис.", [5000]),
    ("заїзд 14:00", []), ("передоплата 50%", []), ("до 6 гостей", []), ("8500 за 4, +500", [8500, 500]),
])
def test_money_values(text, expected):
    assert [v for v, *_ in C.money_values(text, minimum=100)] == expected


@pytest.mark.parametrize("raw", ["+380 67 123 45 67", "0671234567", "067-123-45-67", "(067) 123 45 67", "38 067 123 4567"])
def test_phones_normalized(raw):
    assert C.find_phones(f"тел {raw}, дякую") == ["+380 67 123 45 67"]


@pytest.mark.parametrize("text, coords", [
    ("https://www.google.com/maps/place/X/@48.8372,23.4456,17z", [48.8372, 23.4456]),
    ("https://maps.google.com/?q=48.83721,23.44562", [48.83721, 23.44562]),
    ("https://www.google.com/maps/place/X/data=!3d48.8372!4d23.4456", [48.8372, 23.4456]),
    ("координати 48.8372, 23.4456", [48.8372, 23.4456]),
    ("https://maps.app.goo.gl/AbCdEf123", None),
])
def test_coordinates(text, coords):
    assert C.coordinates_from(text) == coords


@pytest.mark.parametrize("text, start, end", [
    ("28.12–08.01 — 12000", "2026-12-28", "2027-01-08"),
    ("з 30 грудня по 2 січня", "2026-12-30", "2027-01-02"),
    ("1-3 травня 9000", "2027-05-01", "2027-05-03"),
    ("28.12.2026 - 08.01.2027", "2026-12-28", "2027-01-08"),
    ("з 1 по 10 серпня", "2027-08-01", "2027-08-10"),
])
def test_date_ranges(text, start, end):
    s, e, *_ = C.find_date_range(text, TODAY)
    assert (s.isoformat(), e.isoformat()) == (start, end)


def test_number_words():
    assert C.words_to_digits("два котеджі для трьох, чотири спальні") == "2 котеджі для 3, 4 спальні"


# ---------- Ramshill: акуратні відповіді з номерами ----------

def test_ramshill_numbered(tmp_path):
    data, report = parse("ramshill_numbered.txt")
    cfg, text = to_config(data, tmp_path)
    assert (cfg.brand["name"], cfg.contacts["address"], cfg.contacts["region"]) == \
        ("Ramshill", "смт Славське, вул. Курортна 12", "Львівська область")
    big, small = cfg.objects
    assert (big["name"], big["units"], big["price"], big["base_guests"], big["max_guests"], big["extra_guest_price"]) == \
        ("Великий котедж", 2, 8500, 4, 6, 500)
    assert (small["name"], small["units"], small["price"], small["base_guests"], small["max_guests"]) == \
        ("Маленький котедж", 4, 6000, 2, 3)
    assert (big["bedrooms"], big["bathrooms"]) == (2, 2) and "Камін" in big["amenities"]
    assert "Тераса з чаном" in big["amenities"] and "Кухонний куточок" in small["amenities"]
    assert all(o["min_nights"] == 2 and (o["check_in"], o["check_out"]) == ("14:00", "12:00") for o in cfg.objects)
    assert cfg.seasons == [
        {"object": big["key"], "name": "Новорічні свята", "start": "2026-12-28", "end": "2027-01-08", "price": 12000},
        {"object": small["key"], "name": "Новорічні свята", "start": "2026-12-28", "end": "2027-01-08", "price": 8000}]
    chan = cfg.extras[0]
    assert (chan["name"], chan["price"], chan["unit"]) == ("Чан", 2500, "evening")
    assert cfg.rules["prepayment_percent"] == 30 and cfg.rules["cancellation_days"] == 7
    assert "тварин" in cfg.rules["pets"].lower() and "терасі" in cfg.rules["smoking"] and "22:00" in cfg.rules["quiet"]
    c = cfg.contacts
    assert (c["phone"], c["viber"], c["whatsapp"]) == ("+380 67 123 45 67", "+380671234567", "380671234567")
    assert (c["instagram"], c["email"], c["coordinates"]) == ("ramshill.slavske", "ramshill@gmail.com", [48.8372, 23.4456])
    assert "вказівник" in " ".join(c["directions"]) and "смерек" in cfg.brand["description"]
    assert report["missing"] == [] and report["ask"] == [] and C.followup_message(report) == ""
    assert "ЗАМІНИТИ" not in text


def test_site_from_chat_actually_runs(make_site, tmp_path):
    """Наскрізно: чат → конфіг → живий сайт із бронюванням за цінами з чату."""
    data, _ = parse("ramshill_numbered.txt")
    _, _ = to_config(data, tmp_path, "ramshill.yaml")
    s = make_site(str(tmp_path / "ramshill.yaml"))
    assert "Ramshill" in s.html("/") and "Великий котедж" in s.html("/velykyi-kotedzh")
    assert s.total("velykyi-kotedzh", "2026-11-10", "2026-11-12", guests=6, extras=["chan"]) == 2 * 8500 + 2 * 2 * 500 + 2500
    assert s.book("velykyi-kotedzh", "2026-11-20", "2026-11-21").status_code == 400      # мінімум 2 ночі з чату


# ---------- Black House: експорт WhatsApp, не по порядку, частина відповідей ----------

def test_blackhouse_whatsapp_export(tmp_path):
    data, report = parse("blackhouse_whatsapp.txt")
    cfg, text = to_config(data, tmp_path)
    one, two = cfg.objects
    assert (one["name"], one["price"], one["base_guests"], one["max_guests"], one["extra_guest_price"]) == \
        ("Котедж 001", 4500, 2, 4, 500)
    assert (two["name"], two["price"]) == ("Котедж 002", 4000)
    assert (one["check_in"], one["check_out"], two["check_in"], two["check_out"]) == ("15:00", "12:00", "14:00", "11:00")
    jacuzzi = cfg.extras[0]
    assert jacuzzi["guest_prices"] == [{"upTo": 2, "price": 2500}, {"upTo": 4, "price": 3000}] and jacuzzi["unit"] == "evening"
    assert cfg.rules["prepayment_percent"] == 50 and cfg.rules["cancellation_days"] == 10
    assert "9 днів" in cfg.rules["cancellation_text"]
    assert (cfg.contacts["viber"], cfg.contacts["whatsapp"]) == ("+380677654321", "")   # «вотсапу нема»
    assert cfg.contacts["instagram"] == "blackhouse.slavske"
    # коротке посилання на карту — координат не видно, це заглушка «ЗАМІНИТИ» з поясненням
    assert "ЗАМІНИТИ: з короткого посилання" in text and "maps.app.goo.gl/AbCdEf123" in text
    assert report["unanswered"] == [3, 4, 8, 12]
    msg = C.followup_message(report)
    assert msg.startswith("Дякую за відповіді!")
    for part in ("Що є в кожному котеджі", "особливі ціни на свята", "з тваринами", "чим ваш заклад особливий",
                 "Як до вас доїхати"):
        assert part in msg, part
    assert "Медіафайли" not in text and "Добрий день" not in text


# ---------- вільний текст без номерів ----------

def test_freeform_chat_without_numbers(tmp_path):
    data, report = parse("messy_freeform.txt")
    cfg, text = to_config(data, tmp_path)
    assert (cfg.brand["name"], cfg.brand["kind"], cfg.contacts["address"], cfg.contacts["region"]) == \
        ("Лісова Тиша", "Садиба", "с. Мигове", "Чернівецька область")
    assert [(o["name"], o["price"], o["max_guests"]) for o in cfg.objects] == \
        [("Дубовий", 3500, 4), ("Сосновий", 5000, 6), ("А-фрейм", 2800, 2)]
    assert [(e["name"], e["price"], e["unit"]) for e in cfg.extras] == [("Чан", 2000, "evening"), ("Баня", 1500, "person")]
    assert cfg.seasons == [{"object": None, "name": "Новорічні свята", "start": "2026-12-30", "end": "2027-01-02",
                            "price": None}]                                    # «ціни договірні»
    assert cfg.contacts["phone"] == "+380 50 111 22 33"
    assert "ЗАМІНИТИ: передоплату не названо" in text
    assert len(report["ask"]) >= 6


# ---------- мінімальні відповіді: заглушки й дозапит ----------

def test_minimal_answers_are_safe_placeholders(tmp_path, capsys):
    data, report = parse("minimal.txt")
    cfg, text = to_config(data, tmp_path)
    assert cfg.objects[0]["name"] == "Будиночок" and cfg.objects[0]["max_guests"] == 4
    assert "ЗАМІНИТИ: ціну не розпізнано" in text
    assert any("ціна" in m for m in report["missing"])
    assert "Скільки коштує ніч" in C.followup_message(report)


def test_unrecognized_text_is_kept_in_config(tmp_path):
    data, report = C.parse_chat("1. Ramshill, Славське\n2. Великий котедж — до 6 гостей — 8500\n"
                                "щось незрозуміле про котедж\n5. Чан 2500 за вечір\nпро баню ще подумаємо",
                                today=TODAY, slugify=manage.slugify)
    _, text = to_config(data, tmp_path)
    assert "щось незрозуміле про котедж" in text and "про баню ще подумаємо" in text
    assert "НЕ РОЗПІЗНАНО З ЧАТУ" in text


def test_no_secrets_from_chat():
    data, _ = C.parse_chat("9. 0671234567\nпароль від адмінки qwerty123, токен бота 123:ABC", today=TODAY,
                           slugify=manage.slugify)
    text = manage.render_config(data)
    errors, _ = site_config.validate(__import__("yaml").safe_load(text), check_photos=False)
    assert not [e for e in errors if "Секрети" in e]                        # секрети не стають полями конфігу


# ---------- команди ----------

def test_anketa_command(capsys):
    assert manage.main(["anketa"]) == 0
    assert capsys.readouterr().out.strip() == C.QUESTIONNAIRE.strip()


def test_from_chat_command(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(manage, "BASE_DIR", str(tmp_path))
    out = tmp_path / "config" / "blackhouse.yaml"
    assert manage.main(["from-chat", os.path.join(FIXTURES, "blackhouse_whatsapp.txt"), "--output", str(out),
                        "--theme", "dark"]) == 0
    printed = capsys.readouterr().out
    for part in ("Конфіг збережено", "Розпізнано:", "Котедж «Котедж 001»", "Бракує", "Повідомлення клієнту",
                 "Дякую за відповіді!"):
        assert part in printed, part
    cfg = site_config.load(str(out))
    assert cfg.brand["theme"] == "dark"
    assert (tmp_path / "media" / "examples" / "blackhouse" / "objects" / "kotedzh-001").is_dir()

    # наявний файл не перезаписується без --force; з --force — копія .bak
    assert manage.main(["from-chat", os.path.join(FIXTURES, "minimal.txt"), "--output", str(out)]) == 1
    assert "уже існує" in capsys.readouterr().out
    assert manage.main(["from-chat", os.path.join(FIXTURES, "minimal.txt"), "--output", str(out), "--force"]) == 0
    assert (tmp_path / "config" / "blackhouse.yaml.bak").exists()


def test_from_chat_reads_pasted_text(tmp_path, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(chat("ramshill_numbered.txt")))
    out = tmp_path / "site.yaml"
    assert manage.main(["from-chat", "--output", str(out)]) == 0
    assert "Повідомлення клієнту" not in capsys.readouterr().out          # усе є — дозапит не потрібен
    assert site_config.load(str(out)).brand["name"] == "Ramshill"


def test_check_blocks_placeholders_from_chat(tmp_path, capsys, monkeypatch):
    data, _ = parse("minimal.txt")
    path = tmp_path / "site.yaml"
    path.write_text(manage.render_config(data), encoding="utf-8")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "x.db"))
    assert manage.main(["check", "--config", str(path)]) == 1
    printed = capsys.readouterr().out
    assert "лишились заглушки" in printed and "позначок «ПЕРЕВІРИТИ»" in printed
