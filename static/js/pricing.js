/*
 * Розрахунок ціни в браузері — точна копія pricing.py:
 *   разом = Σ по ночах (ціна сезону, вихідних або базова) + ночі × гості понад базу × доплата + послуги;
 *   мінімальний термін бронювання — як pricing.min_stay (звичайний, на вихідні, особливі періоди).
 * Сервер однаково перераховує суму сам, тож це лише попередній розрахунок для гостя.
 */
(function () {
  'use strict';

  function toDate(iso) { var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function toISO(d) { return d.toISOString().slice(0, 10); }
  function addDays(iso, n) { var d = toDate(iso); d.setUTCDate(d.getUTCDate() + n); return toISO(d); }
  function nightsBetween(a, b) { var out = []; for (var d = a; d < b; d = addDays(d, 1)) out.push(d); return out; }
  /** Ніч п'ятниці чи суботи (ніч = дата, з якої вона починається). */
  function isWeekend(iso) { var w = toDate(iso).getUTCDay(); return w === 5 || w === 6; }
  function nightsWord(n) {
    n = Math.abs(n);
    if (n % 10 === 1 && n % 100 !== 11) return 'ніч';
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return 'ночі';
    return 'ночей';
  }
  function ddmm(iso) { return iso.slice(8, 10) + '.' + iso.slice(5, 7); }

  /**
   * objects = {"1": {id, price, tiers: [{nights, price}], baseGuests, maxGuests, extraGuestPrice, minNights, units, ...}, ...}
   * periods = [{objectId|null, name, start, end, price|null}]
   * extras  = [{key, name, price, unit, guestPrices: [{upTo, price}]}]
   * minStayRules = [{objectId|null, name, start, end, minNights}] — періоди з особливим мінімумом ночей
   */
  function make(config, objects, periods, extras, minStayRules) {
    var C = config;
    minStayRules = minStayRules || [];
    periods = periods || [];
    extras = extras || [];
    function obj(id) { return objects[String(id)]; }

    function rateFor(id, n) {
      var o = obj(id), price = o.price, tier = null;
      o.tiers.slice().sort(function (a, b) { return a.nights - b.nights; }).forEach(function (t) {
        if (n >= t.nights) { price = t.price; tier = t.nights; }
      });
      return { price: price, tier: tier };
    }
    function minPrice(id) {
      var o = obj(id);
      return Math.min.apply(null, [o.price].concat(o.tiers.map(function (t) { return t.price; }), o.weekendPrice ? [o.weekendPrice] : []));
    }
    /**
     * Мінімум ночей для бронювання checkIn → checkOut і чому він такий (копія pricing.min_stay):
     * найбільший зі звичайного, на вихідні (якщо є ніч пт / сб) і періодів з особливим мінімумом.
     */
    function minStay(id, checkIn, checkOut) {
      var o = obj(id), nights = nightsBetween(checkIn, checkOut);
      var best = { required: o.minNights || 1, kind: 'base', rule: null, night: null };
      var weekend = o.weekendMinNights || 0;
      if (weekend > best.required && nights.some(isWeekend)) best = { required: weekend, kind: 'weekend', rule: null, night: null };
      minStayRules.forEach(function (r) {
        if ((r.objectId !== null && r.objectId !== +id) || r.minNights <= best.required) return;
        for (var i = 0; i < nights.length; i++) {
          if (r.start <= nights[i] && nights[i] <= r.end) { best = { required: r.minNights, kind: 'rule', rule: r, night: nights[i] }; return; }
        }
      });
      return best;
    }
    function minNightsFor(id, checkIn, checkOut) { return minStay(id, checkIn, checkOut).required; }
    function stayOk(id, checkIn, checkOut) { return checkOut > checkIn && nightsBetween(checkIn, checkOut).length >= minNightsFor(id, checkIn, checkOut); }
    /** Найраніший дозволений виїзд після checkIn (не пізніше limit) або null. Дозволені дати можуть іти з пропусками:
     *  29.12 → 31.12 можна, → 01.01 ні (новорічна ніч, мінімум 5), → 03.01 знову можна. */
    function earliestCheckout(id, checkIn, limit) {
      for (var d = addDays(checkIn, 1), i = 0; i < 400 && (!limit || d <= limit); d = addDays(d, 1), i++) {
        if (stayOk(id, checkIn, d)) return d;
      }
      return null;
    }
    /** Найменша можлива кількість ночей від заїзду checkIn (для підказок у календарі). */
    function minNightsFrom(id, checkIn) {
      var out = earliestCheckout(id, checkIn, null);
      return out ? nightsBetween(checkIn, out).length : obj(id).minNights || 1;
    }
    function rulePhrase(r) { return r.name ? 'на ' + r.name : 'з ' + ddmm(r.start) + ' до ' + ddmm(addDays(r.end, 1)); }
    /** Текст біля форми (копія pricing.min_stay_note); '' — обмежень немає. */
    function minStayNote(id, today) {
      var o = obj(id), base = o.minNights || 1, parts = [], weekend = o.weekendMinNights || 0;
      if (weekend > base) parts.push('на вихідні — ' + weekend + ' ' + nightsWord(weekend));
      minStayRules.filter(function (r) { return (r.objectId === null || r.objectId === +id) && r.end >= today && r.minNights > base; })
        .sort(function (a, b) { return a.start < b.start ? -1 : a.start > b.start ? 1 : a.end < b.end ? -1 : a.end > b.end ? 1 : 0; })
        .forEach(function (r) { parts.push(rulePhrase(r) + ' — ' + r.minNights + ' ' + nightsWord(r.minNights)); });
      if (base <= 1 && !parts.length) return '';
      return ['Мінімальний термін бронювання — ' + base + ' ' + nightsWord(base)].concat(parts).join(', ') + '.';
    }
    /** Пояснення гостю (копія pricing.min_stay_message). */
    function minStayMessage(stay, nights) {
      var need = stay.required, head;
      if (stay.kind === 'rule') {
        var ph = rulePhrase(stay.rule);
        head = ph.charAt(0).toUpperCase() + ph.slice(1) + ' мінімальний термін бронювання — ' + need + ' ' + nightsWord(need) +
          ': ваші дати включають ніч ' + ddmm(stay.night) + '→' + ddmm(addDays(stay.night, 1)) + '.';
      } else if (stay.kind === 'weekend') {
        head = "Якщо серед ночей є п'ятниця чи субота, мінімальний термін бронювання — " + need + ' ' + nightsWord(need) + '.';
      } else head = 'Мінімальний термін бронювання — ' + need + ' ' + nightsWord(need) + '.';
      var more = need - nights;
      return head + ' Ви обрали ' + nights + ' ' + nightsWord(nights) + ' — додайте ще ' + more + ' ' + nightsWord(more) + ' або оберіть інші дати.';
    }
    function periodFor(id, iso) {
      var general = null;
      for (var i = 0; i < periods.length; i++) {
        var p = periods[i];
        if (p.start <= iso && iso <= p.end) {
          if (p.objectId === +id) return p;
          if (p.objectId === null && !general) general = p;
        }
      }
      return general;
    }
    /** Ціна доби для календаря: ціна періоду, null — «за домовленістю», інакше базова. */
    function dayPrice(id, iso) {
      var p = periodFor(id, iso);
      if (p) return p.price;
      var o = obj(id);
      return o.weekendPrice && isWeekend(iso) ? o.weekendPrice : o.price;
    }

    /** Ціна послуги для такої кількості гостей: перший поріг guestPrices, у який вони вміщаються. */
    function extraUnitPrice(e, guests) {
      var tiers = (e.guestPrices || []).slice().sort(function (a, b) { return a.upTo - b.upTo; });
      for (var i = 0; i < tiers.length; i++) if (guests <= tiers[i].upTo) return tiers[i].price;
      return tiers.length ? tiers[tiers.length - 1].price : e.price;
    }
    function extraQuantity(unit, nights, guests) {
      return unit === 'night' ? nights : unit === 'person' ? guests : unit === 'person_night' ? nights * guests : 1;
    }

    function quote(id, checkIn, checkOut, guests, extraKeys) {
      var o = obj(id), nights = nightsBetween(checkIn, checkOut), n = nights.length, r = rateFor(id, n);
      guests = Math.max(1, guests | 0);
      var groups = {}, order = [], missing = [], accommodation = 0;
      nights.forEach(function (iso) {
        var p = periodFor(id, iso), price, kind, label;
        if (p && p.price == null) { missing.push(iso); return; }
        if (p) { price = p.price; kind = 'period'; label = p.name || 'особливий період'; }
        else if (o.weekendPrice && isWeekend(iso)) { price = o.weekendPrice; kind = 'weekend'; label = 'пт і сб'; }
        else { price = r.price; kind = r.tier ? 'tier' : 'base'; label = r.tier ? 'від ' + r.tier + ' ночей' : ''; }
        var key = price + '|' + kind + '|' + label;
        if (!groups[key]) { groups[key] = { price: price, kind: kind, label: label, count: 0 }; order.push(key); }
        groups[key].count++;
        accommodation += price;
      });
      var lines = order.map(function (k) { var g = groups[k]; return { price: g.price, kind: g.kind, label: g.label, count: g.count, sum: g.price * g.count }; });

      var extraGuests = Math.max(0, guests - (o.baseGuests || guests)), fee = o.extraGuestPrice || 0;
      var pricedNights = n - missing.length, guestsSum = extraGuests * fee * pricedNights;
      var guestsLine = guestsSum ? { count: extraGuests, price: fee, nights: pricedNights, sum: guestsSum } : null;

      var extraLines = extras.filter(function (e) { return (extraKeys || []).indexOf(e.key) !== -1; })
        .map(function (e) {
          var price = extraUnitPrice(e, guests), qty = extraQuantity(e.unit, n, guests);
          return { key: e.key, name: e.name, unit: e.unit || 'evening', price: price, qty: qty, sum: price * qty };
        });
      var extrasTotal = extraLines.reduce(function (s, e) { return s + e.sum; }, 0);
      var onRequest = missing.length > 0;
      var total = onRequest ? null : accommodation + guestsSum + extrasTotal;
      return {
        objectId: o.id, nights: n, guests: guests, basePrice: o.price,
        rate: r.price, tier: r.tier, lines: lines, accommodation: onRequest ? null : accommodation,
        extraGuests: guestsLine, extras: extraLines, extrasTotal: extrasTotal, total: total,
        prepayment: onRequest ? null : Math.round(total * C.prepaymentPercent / 100),
        prepaymentPercent: C.prepaymentPercent, onRequest: onRequest, missingNights: missing
      };
    }

    /** Найпізніша дата виїзду для заїзду checkIn: перша зайнята доба після заїзду (або кінець вікна). */
    function checkoutLimit(busySet, checkIn, last) {
      if (busySet[checkIn]) return null;
      for (var d = addDays(checkIn, 1); d < last; d = addDays(d, 1)) if (busySet[d]) return d;
      return last;
    }

    return { CONFIG: C, objects: objects, extras: extras, obj: obj, quote: quote, rateFor: rateFor,
      minPrice: minPrice, minNightsFor: minNightsFor, minNightsFrom: minNightsFrom,
      minStay: minStay, stayOk: stayOk, earliestCheckout: earliestCheckout, minStayNote: minStayNote, minStayMessage: minStayMessage, periodFor: periodFor, dayPrice: dayPrice, checkoutLimit: checkoutLimit,
      extraUnitPrice: extraUnitPrice, extraQuantity: extraQuantity };
  }

  function formatUAH(n) { return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' грн'; }
  function shortPrice(n) { return n < 1000 ? String(n) : (n / 1000).toLocaleString('uk-UA', { maximumFractionDigits: 1 }) + 'к'; }

  window.FHPricing = {
    make: make, isWeekend: isWeekend, toDate: toDate, toISO: toISO, addDays: addDays, nightsBetween: nightsBetween,
    formatUAH: formatUAH, shortPrice: shortPrice, nightsWord: nightsWord
  };
})();
