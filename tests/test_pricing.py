"""Формула ціни (pricing.py) — без бази й без сайту.

Ціна = ночі × (ціна сезону або базова) + доплата за гостей понад базу + додаткові послуги.
"""

from datetime import date, timedelta

import pricing as P

BIG = {"id": 1, "price": 8500, "tiers": [], "baseGuests": 4, "extraGuestPrice": 500}
SMALL = {"id": 2, "price": 6000, "tiers": [], "baseGuests": 2, "extraGuestPrice": 500}
CHAN = {"key": "chan", "name": "Чан", "price": 2500, "unit": "evening", "guestPrices": []}
JACUZZI = {"key": "jacuzzi", "name": "Чан-джакузі", "price": 3000, "unit": "evening",
           "guestPrices": [{"upTo": 2, "price": 2500}, {"upTo": 4, "price": 3000}]}
NEW_YEAR = {"objectId": None, "name": "Новий рік", "start": "2026-12-30", "end": "2027-01-02", "price": 12000}


def quote(obj=BIG, check_in="2026-11-10", nights=2, guests=2, periods=(), extras=(), keys=(), prepay=30):
    out = (date.fromisoformat(check_in) + timedelta(days=nights)).isoformat()
    return P.quote(obj, list(periods), list(extras), check_in, out, guests, keys, prepay)


def test_base_price_is_nights_times_price():
    assert quote(nights=1)["total"] == 8500
    assert quote(nights=3)["total"] == 3 * 8500
    assert quote(SMALL, nights=2)["total"] == 12000


def test_no_surcharge_up_to_base_guests():
    assert quote(guests=1)["total"] == quote(guests=4)["total"] == 17000
    assert quote(guests=4)["extraGuests"] is None


def test_surcharge_for_each_guest_above_base_per_night():
    assert quote(guests=5, nights=1)["total"] == 8500 + 500
    q = quote(guests=6, nights=2)                       # 2 зайві гості × 500 × 2 ночі
    assert q["total"] == 17000 + 2000
    assert q["extraGuests"] == {"count": 2, "price": 500, "nights": 2, "sum": 2000}
    assert quote(SMALL, guests=3, nights=3)["total"] == 3 * 6000 + 3 * 500


def test_season_night_uses_season_price():
    q = quote(check_in="2026-12-30", nights=2, periods=[NEW_YEAR])
    assert q["total"] == 24000
    assert q["lines"] == [{"price": 12000, "kind": "period", "label": "Новий рік", "count": 2, "sum": 24000}]


def test_booking_can_cross_season_boundary():
    # 28, 29 — звичайні ночі; 30, 31 — сезон
    q = quote(check_in="2026-12-28", nights=4, periods=[NEW_YEAR])
    assert q["total"] == 2 * 8500 + 2 * 12000
    assert [(line["count"], line["price"]) for line in q["lines"]] == [(2, 8500), (2, 12000)]
    # виїзд зі свята: 01, 02 — сезон; 03 — уже звичайна ніч
    assert quote(check_in="2027-01-01", nights=3, periods=[NEW_YEAR])["total"] == 2 * 12000 + 8500


def test_season_boundaries_are_inclusive_nights():
    assert quote(check_in="2026-12-29", nights=1, periods=[NEW_YEAR])["total"] == 8500    # ніч перед сезоном
    assert quote(check_in="2026-12-30", nights=1, periods=[NEW_YEAR])["total"] == 12000   # перша ніч сезону
    assert quote(check_in="2027-01-02", nights=1, periods=[NEW_YEAR])["total"] == 12000   # остання ніч сезону
    assert quote(check_in="2027-01-03", nights=1, periods=[NEW_YEAR])["total"] == 8500


def test_object_season_beats_general_season():
    own = {"objectId": 2, "name": "Свято", "start": "2026-12-30", "end": "2027-01-02", "price": 9000}
    assert quote(SMALL, check_in="2026-12-30", nights=1, periods=[NEW_YEAR, own])["total"] == 9000
    assert quote(BIG, check_in="2026-12-30", nights=1, periods=[NEW_YEAR, own])["total"] == 12000


def test_surcharge_also_applies_on_season_nights():
    q = quote(check_in="2026-12-29", nights=2, guests=6, periods=[NEW_YEAR])
    assert q["total"] == 8500 + 12000 + 2 * 500 * 2


def test_extras_added_to_total():
    assert quote(extras=[CHAN], keys=["chan"])["total"] == 17000 + 2500
    assert quote(extras=[CHAN], keys=[])["total"] == 17000
    assert quote(extras=[CHAN], keys=["unknown"])["total"] == 17000


def test_extra_price_depends_on_guests():
    """Чан-джакузі: 2500 для 2 гостей, 3000 для 3–4."""
    def price(guests):
        return quote(SMALL, guests=guests, nights=1, extras=[JACUZZI], keys=["jacuzzi"])["extras"][0]["sum"]
    assert [price(g) for g in (1, 2, 3, 4)] == [2500, 2500, 3000, 3000]
    assert price(6) == 3000      # більше, ніж в останньому порозі — діє останній


def test_extra_units():
    def extra(unit, guests=3, nights=2):
        e = {"key": "x", "name": "X", "price": 100, "unit": unit, "guestPrices": []}
        return quote(guests=guests, nights=nights, extras=[e], keys=["x"])["extrasTotal"]
    assert extra("evening") == 100          # за вечір — один раз
    assert extra("once") == 100             # за бронювання
    assert extra("night") == 200            # × ночі
    assert extra("person") == 300           # × гості
    assert extra("person_night") == 600     # × гості × ночі


def test_full_formula():
    """ночі × ціна (сезон/база) + доплата за гостей + послуги, потім передоплата."""
    q = quote(check_in="2026-12-29", nights=3, guests=5, periods=[NEW_YEAR], extras=[CHAN, JACUZZI],
              keys=["chan", "jacuzzi"], prepay=50)
    assert q["accommodation"] == 8500 + 2 * 12000
    assert q["extraGuests"]["sum"] == 1 * 500 * 3
    assert q["extrasTotal"] == 2500 + 3000
    assert q["total"] == 32500 + 1500 + 5500
    assert q["prepayment"] == 19750 and q["prepaymentPercent"] == 50


def test_prepayment_percent():
    assert quote(prepay=30)["prepayment"] == 5100
    assert quote(prepay=50)["prepayment"] == 8500
    assert quote(prepay=0)["prepayment"] == 0


def test_price_on_request_season():
    on_request = [{"objectId": None, "name": "Свята", "start": "2026-12-30", "end": "2027-01-07", "price": None}]
    q = quote(check_in="2026-12-28", nights=4, periods=on_request)
    assert q["onRequest"] and q["total"] is None and q["prepayment"] is None
    assert q["missingNights"] == ["2026-12-30", "2026-12-31"]


def test_long_stay_discount():
    aframe = {"id": 3, "price": 4000, "tiers": [{"nights": 2, "price": 3500}, {"nights": 5, "price": 3000}],
              "baseGuests": 2, "extraGuestPrice": 0}
    assert [quote(aframe, nights=n)["total"] for n in (1, 2, 4, 5, 7)] == [4000, 7000, 14000, 15000, 21000]
    assert P.min_price(aframe) == 3000


def test_is_free_counts_units():
    taken = {"2026-11-10": 1, "2026-11-11": 2}
    assert P.is_free({}, 1, "2026-11-10", "2026-11-12")
    assert not P.is_free(taken, 1, "2026-11-10", "2026-11-11")       # одна одиниця — зайнято
    assert P.is_free(taken, 2, "2026-11-10", "2026-11-11")           # дві одиниці — одна ще вільна
    assert not P.is_free(taken, 2, "2026-11-10", "2026-11-12")       # 11-го зайняті обидві
    assert P.is_free(taken, 3, "2026-11-10", "2026-11-12")
    assert not P.is_free({}, 2, "2026-11-10", "2026-11-10")          # нуль ночей — не бронювання


def test_format():
    assert P.format_uah(20000) == "20 000 грн"
    assert P.nights_between("2026-11-10", "2026-11-12") == ["2026-11-10", "2026-11-11"]
