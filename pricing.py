"""Розрахунок ціни й доступності. Чисті функції: нічого не знають про базу, конфіг чи Flask.

Формула:
    разом = Σ по ночах (ціна сезону, якщо ніч у сезоні, інакше базова)
          + ночі × гості понад базу × доплата за гостя
          + додаткові послуги

  • Об'єкт (рядок таблиці objects): price — базова ціна за ніч за baseGuests гостей;
    extraGuestPrice — доплата за кожного гостя понад baseGuests за кожну ніч; tiers — необов'язкова
    знижка за тривалість [{"nights": 3, "price": 4000}] (діє найбільший досягнутий поріг).
  • Сезон (таблиця periods): price задано — на ці ночі діє вона (бронь може перетинати межу сезону,
    кожна ніч рахується за своєю ціною); price порожня — «ціна за домовленістю», сума не рахується.
    Сезон конкретного об'єкта має пріоритет над сезоном «для всіх».
  • Послуга (extras): ціна може залежати від кількості гостей (guestPrices), а одиниця (unit)
    визначає множник: за вечір / за бронювання — ×1, за ніч — ×ночі, за людину — ×гості,
    за людину за ніч — ×гості×ночі.

Браузер рахує те саме (static/js/pricing.js — копія цього файлу). Сервер завжди перераховує
суму сам — підробити її з браузера не можна.
"""

from datetime import date, timedelta


def _d(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def nights_between(check_in, check_out):
    """Список ночей (ISO-дати) між заїздом і виїздом: ніч = дата, з якої вона починається."""
    start, end = _d(check_in), _d(check_out)
    out = []
    while start < end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def rate_for(obj, nights):
    """Базова ціна за ніч для бронювання на nights ночей (зі знижкою за тривалість) і поріг, що спрацював."""
    price, tier = obj["price"], None
    for t in sorted(obj.get("tiers") or [], key=lambda t: t["nights"]):
        if nights >= t["nights"]:
            price, tier = t["price"], t["nights"]
    return price, tier


def min_price(obj):
    return min([obj["price"]] + [t["price"] for t in obj.get("tiers") or []])


def period_for(periods, object_id, iso):
    """Сезон для ночі: спершу окремий для об'єкта, потім — для всіх об'єктів."""
    general = None
    for p in periods:
        if p["start"] <= iso <= p["end"]:
            if p["objectId"] == object_id:
                return p
            if p["objectId"] is None and general is None:
                general = p
    return general


def extra_unit_price(extra, guests):
    """Ціна послуги для такої кількості гостей: перший поріг guestPrices, у який вони вміщаються."""
    tiers = sorted(extra.get("guestPrices") or [], key=lambda t: t["upTo"])
    for t in tiers:
        if guests <= t["upTo"]:
            return int(t["price"])
    return int(tiers[-1]["price"]) if tiers else int(extra["price"])


def extra_quantity(unit, nights, guests):
    return {"night": nights, "person": guests, "person_night": nights * guests}.get(unit, 1)


def quote(obj, periods, extras, check_in, check_out, guests, extra_keys=(), prepayment_percent=0):
    """Розрахунок вартості. total = None, якщо хоч одна ніч «за домовленістю».

    obj    — {"id", "price", "tiers", "baseGuests", "extraGuestPrice"}
    extras — [{"key", "name", "price", "unit", "guestPrices"}] (усі доступні послуги)
    """
    nights = nights_between(check_in, check_out)
    n = len(nights)
    guests = max(1, int(guests))
    rate, tier = rate_for(obj, n)

    groups, missing, accommodation = {}, [], 0
    for iso in nights:
        p = period_for(periods, obj["id"], iso)
        if p and p.get("price") is None:
            missing.append(iso)
            continue
        if p:
            price, kind, label = int(p["price"]), "period", p.get("name") or "особливий період"
        else:
            price, kind, label = rate, ("tier" if tier else "base"), (f"від {tier} ночей" if tier else "")
        g = groups.setdefault((price, kind, label), {"price": price, "kind": kind, "label": label,
                                                     "count": 0, "first": iso})
        g["count"] += 1
        accommodation += price
    lines = [dict(g, sum=g["price"] * g["count"]) for g in sorted(groups.values(), key=lambda g: g["first"])]
    for line in lines:
        line.pop("first")

    # Доплата за гостей понад базу — за кожну ніч із відомою ціною.
    base_guests = int(obj.get("baseGuests") or guests)
    extra_guests = max(0, guests - base_guests)
    fee = int(obj.get("extraGuestPrice") or 0)
    priced_nights = n - len(missing)
    guests_sum = extra_guests * fee * priced_nights
    guests_line = ({"count": extra_guests, "price": fee, "nights": priced_nights, "sum": guests_sum}
                   if guests_sum else None)

    extra_lines = []
    for e in extras:
        if e["key"] in extra_keys:
            price = extra_unit_price(e, guests)
            qty = extra_quantity(e.get("unit"), n, guests)
            extra_lines.append({"key": e["key"], "name": e["name"], "unit": e.get("unit") or "evening",
                                "price": price, "qty": qty, "sum": price * qty})
    extras_total = sum(e["sum"] for e in extra_lines)

    on_request = bool(missing)
    total = None if on_request else accommodation + guests_sum + extras_total
    prepayment = None if on_request else round(total * prepayment_percent / 100)
    return {
        "objectId": obj["id"],
        "nights": n,
        "guests": guests,
        "basePrice": obj["price"],
        "rate": rate,
        "tier": tier,
        "lines": lines,
        "accommodation": None if on_request else accommodation,
        "extraGuests": guests_line,
        "extras": extra_lines,
        "extrasTotal": extras_total,
        "total": total,
        "prepayment": prepayment,
        "prepaymentPercent": prepayment_percent,
        "onRequest": on_request,
        "missingNights": missing,
    }


def is_free(occupied, units, check_in, check_out):
    """Чи є хоч одна вільна одиниця на всі ночі періоду.

    occupied — {ніч: скільки одиниць зайнято}; units — скільки однакових одиниць в об'єкта.
    Одиниці однакові й гостя можна поселити в будь-яку, тому достатньо, щоб у жодну ніч
    не було зайнято всі одиниці (класична задача про розклад інтервалів).
    """
    nights = nights_between(check_in, check_out)
    return bool(nights) and all(occupied.get(n, 0) < units for n in nights)


def format_uah(n):
    return f"{int(round(n)):,}".replace(",", " ") + " грн"
