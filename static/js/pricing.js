/*
 * Розрахунок ціни в браузері — точна копія pricing.py:
 *   разом = Σ по ночах (ціна сезону або базова) + ночі × гості понад базу × доплата + послуги.
 * Сервер однаково перераховує суму сам, тож це лише попередній розрахунок для гостя.
 */
(function () {
  'use strict';

  function toDate(iso) { var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function toISO(d) { return d.toISOString().slice(0, 10); }
  function addDays(iso, n) { var d = toDate(iso); d.setUTCDate(d.getUTCDate() + n); return toISO(d); }
  function nightsBetween(a, b) { var out = []; for (var d = a; d < b; d = addDays(d, 1)) out.push(d); return out; }

  /**
   * objects = {"1": {id, price, tiers: [{nights, price}], baseGuests, maxGuests, extraGuestPrice, minNights, units, ...}, ...}
   * periods = [{objectId|null, name, start, end, price|null}]
   * extras  = [{key, name, price, unit, guestPrices: [{upTo, price}]}]
   */
  function make(config, objects, periods, extras) {
    var C = config;
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
      return Math.min.apply(null, [o.price].concat(o.tiers.map(function (t) { return t.price; })));
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
      return obj(id).price;
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
      minPrice: minPrice, periodFor: periodFor, dayPrice: dayPrice, checkoutLimit: checkoutLimit,
      extraUnitPrice: extraUnitPrice, extraQuantity: extraQuantity };
  }

  function formatUAH(n) { return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + ' грн'; }
  function shortPrice(n) { return n < 1000 ? String(n) : (n / 1000).toLocaleString('uk-UA', { maximumFractionDigits: 1 }) + 'к'; }

  window.FHPricing = {
    make: make, toDate: toDate, toISO: toISO, addDays: addDays, nightsBetween: nightsBetween,
    formatUAH: formatUAH, shortPrice: shortPrice
  };
})();
