"""Ціни й доступність садиби Forest House — окремо для кожного з трьох будинків.

Ціна будинку (таблиця objects, змінюється в адмінці):
  • price — ціна за добу;
  • tiers — знижка за тривалість: [{"nights": 2, "price": 2200}, ...]. Діє ціна найбільшого
    порогу, якого досягає бронювання: А-фрейм на 6 діб → ціна «від 5 діб» за кожну добу.
Періоди (таблиця periods, напр. новорічні свята):
  • price задано — на ці доби діє ця ціна замість звичайної;
  • price порожня — «ціна за домовленістю»: сайт не рахує суму, а пише «Уточніть ціну у власника».
Додатково: чан і баня (галочки у формі) — фіксована сума за вечір, додається до підсумку.

Браузер рахує те саме (static/js/pricing.js — копія цього файлу). Сервер завжди перераховує
ціну сам — підробити її з браузера не можна.
"""

from datetime import date, timedelta

import site_content

CONFIG = dict(site_content.RULES)
OBJECT_IDS = tuple(o["id"] for o in site_content.OBJECTS)


def _d(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def nights_between(check_in, check_out):
    """Список діб (ISO-дати) між заїздом і виїздом: доба = дата, з якої починається ніч."""
    start, end = _d(check_in), _d(check_out)
    out = []
    while start < end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def rate_for(obj, nights):
    """Ціна за добу для бронювання на nights діб (зі знижкою за тривалість) і поріг, що спрацював."""
    price, tier = obj["price"], None
    for t in sorted(obj.get("tiers") or [], key=lambda t: t["nights"]):
        if nights >= t["nights"]:
            price, tier = t["price"], t["nights"]
    return price, tier


def min_price(obj):
    return min([obj["price"]] + [t["price"] for t in obj.get("tiers") or []])


def period_for(periods, object_id, iso):
    """Період для доби: спершу окремий для будинку, потім — для всіх будинків."""
    general = None
    for p in periods:
        if p["start"] <= iso <= p["end"]:
            if p["objectId"] == object_id:
                return p
            if p["objectId"] is None and general is None:
                general = p
    return general


def quote(obj, periods, extras_prices, check_in, check_out, guests, extras=()):
    """Розрахунок вартості. total = None, якщо хоч одна доба «за домовленістю»."""
    nights = nights_between(check_in, check_out)
    n = len(nights)
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
            price, kind, label = rate, ("tier" if tier else "base"), (f"від {tier} діб" if tier else "")
        g = groups.setdefault((price, kind, label), {"price": price, "kind": kind, "label": label,
                                                     "count": 0, "first": iso})
        g["count"] += 1
        accommodation += price
    lines = [dict(g, sum=g["price"] * g["count"]) for g in sorted(groups.values(), key=lambda g: g["first"])]
    for line in lines:
        line.pop("first")

    extra_lines = []
    for key in extras:
        if key in extras_prices:
            e = site_content.EXTRA_BY_KEY.get(key, {"name": key})
            extra_lines.append({"key": key, "name": e["name"], "price": int(extras_prices[key])})
    extras_total = sum(e["price"] for e in extra_lines)

    on_request = bool(missing)
    total = None if on_request else accommodation + extras_total
    prepayment = None if on_request else round(total * CONFIG["prepaymentPercent"] / 100)
    return {
        "objectId": obj["id"],
        "nights": n,
        "guests": max(1, int(guests)),
        "basePrice": obj["price"],
        "rate": rate,
        "tier": tier,
        "lines": lines,
        "accommodation": None if on_request else accommodation,
        "extras": extra_lines,
        "extrasTotal": extras_total,
        "total": total,
        "prepayment": prepayment,
        "prepaymentPercent": CONFIG["prepaymentPercent"],
        "onRequest": on_request,
        "missingNights": missing,
    }


def is_free(busy_nights, check_in, check_out):
    """Чи вільний будинок на всі доби періоду. busy_nights — set діб цього будинку."""
    nights = nights_between(check_in, check_out)
    return bool(nights) and not any(n in busy_nights for n in nights)


def format_uah(n):
    return f"{int(round(n)):,}".replace(",", " ") + " грн"
