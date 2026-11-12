/* Адмінка: заявки по об'єктах, зайнятість (з урахуванням кількості одиниць), ціни, сезони, послуги. */
(function () {
  'use strict';
  var V = window.FHPricing, API = window.FHApi.admin;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var data = null, P = null, IDS = [], filter = 'active', bkObject = 'all', calObject = 'all', view = null, day = null;
  var MONTHS = ['Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень', 'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень'];
  var MONTHS_GEN = ['січня', 'лютого', 'березня', 'квітня', 'травня', 'червня', 'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня'];
  var WD = ['нд', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];
    var DAY_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'нд'];
  var STATUS = { 'new': 'нова', confirmed: 'підтверджено', cancelled: 'скасовано' };

  function human(iso, wd) { var d = V.toDate(iso); return d.getUTCDate() + ' ' + MONTHS_GEN[d.getUTCMonth()] + (wd ? ' (' + WD[d.getUTCDay()] + ')' : ''); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function tel(p) { return 'tel:' + String(p).replace(/[^\d+]/g, ''); }
  function obj(id) { return data.objects[String(id)]; }
  function letter(id) { return String(IDS.indexOf(+id) + 1); }
  function nightsWord(n) { return n % 10 === 1 && n % 100 !== 11 ? 'ніч' : (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) ? 'ночі' : 'ночей'; }
  var money = V.formatUAH;

  var toastTimer;
  function toast(msg) {
    var t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 3200);
  }

  function reload() {
    return API.data().then(function (d) {
      data = d;
      P = V.make(d.config, d.objects, d.periods, d.extras);
      IDS = Object.keys(d.objects).map(Number);
      if (!view) { var t = V.toDate(d.today); view = { y: t.getUTCFullYear(), m: t.getUTCMonth() }; }
      render();
    }).catch(function (ex) { toast(ex.message); });
  }
  setInterval(function () { if (data && !document.hidden && !editing()) reload(); }, 60000);
  function editing() { return document.activeElement && document.activeElement.closest('#priceObjs, #extrasBox, #periodsBox'); }
  $('#refresh').addEventListener('click', function () { reload().then(function () { toast('Оновлено'); }); });
  $('#tgTest').addEventListener('click', function () {
    var btn = this; btn.disabled = true;
    API.telegramTest().then(function () { toast('Тестове повідомлення надіслано в Telegram'); })
      .catch(function (ex) { toast(ex.message); }).then(function () { btn.disabled = false; });
  });

  $$('[data-tab-btn]').forEach(function (b) {
    b.addEventListener('click', function () {
      var name = b.getAttribute('data-tab-btn');
      $$('[data-tab-btn]').forEach(function (x) { x.classList.toggle('is-active', x === b); });
      $$('[data-panel]').forEach(function (p) { p.hidden = p.getAttribute('data-panel') !== name; });
    });
  });
  $('#filter').addEventListener('change', function () { filter = this.value; renderList(); });

  // Перемикач об'єктів: «Усі» + кожен об'єкт.
  function seg(el, current, allLabel) {
    el.innerHTML = '<button type="button" data-seg="all" class="' + (current === 'all' ? 'is-on' : '') + '">' + allLabel + '</button>' +
      IDS.map(function (id) {
        var o = obj(id);
        return '<button type="button" data-seg="' + id + '" class="seg--t' + o.tone + (String(current) === String(id) ? ' is-on' : '') + '">' + esc(o.short) + '</button>';
      }).join('');
  }
  $('#bkObject').addEventListener('click', function (e) {
    var b = e.target.closest('[data-seg]'); if (!b) return;
    bkObject = b.getAttribute('data-seg'); seg(this, bkObject, 'Усі'); renderList();
  });
  $('#calObject').addEventListener('click', function (e) {
    var b = e.target.closest('[data-seg]'); if (!b) return;
    calObject = b.getAttribute('data-seg'); seg(this, calObject, 'Усі'); renderCalendar(); renderLegend();
  });

  /* ---------- render ---------- */
  function render() {
    $('#tgRow').hidden = false;
    $('#tgState').textContent = data.telegram ? 'увімкнено' : 'не налаштовано';
    var bs = data.bookings;
    var nNew = bs.filter(function (b) { return b.status === 'new'; }).length;
    $('#cntNew').textContent = nNew || '';
    var upcoming = bs.filter(function (b) { return b.status === 'confirmed' && b.checkOut >= data.today; }).length;
    var income = bs.filter(function (b) { return b.status === 'confirmed' && b.total; }).reduce(function (s, b) { return s + b.total; }, 0);
    var unitsAll = 0, tonight = 0;
    IDS.forEach(function (id) {
      unitsAll += obj(id).units;
      tonight += Math.min(obj(id).units, (data.occupancy[String(id)] || {})[data.today] || 0);
    });
    $('#stats').innerHTML =
      '<div class="stat stat--accent"><span>Нові заявки</span><b>' + nNew + '</b></div>' +
      '<div class="stat"><span>Майбутні заїзди</span><b>' + upcoming + '</b></div>' +
      '<div class="stat"><span>Зайнято сьогодні</span><b>' + tonight + ' / ' + unitsAll + '</b></div>' +
      '<div class="stat"><span>Підтверджено на суму</span><b>' + money(income) + '</b></div>';
    seg($('#bkObject'), bkObject, 'Усі');
    seg($('#calObject'), calObject, 'Усі');
    renderList();
    renderCalendar();
    renderLegend();
    renderDay();
    renderPrices();
  }

  function renderList() {
    var items = data.bookings.filter(function (b) {
      if (bkObject !== 'all' && String(b.objectId) !== bkObject) return false;
      if (filter === 'all') return true;
      if (filter === 'active') return b.status !== 'cancelled';
      return b.status === filter;
    }).sort(function (a, b) {
      if ((a.status === 'new') !== (b.status === 'new')) return a.status === 'new' ? -1 : 1;
      return a.checkIn < b.checkIn ? -1 : 1;
    });
    var el = $('#list');
    if (!items.length) { el.innerHTML = '<div class="empty">Заявок немає</div>'; return; }
    el.innerHTML = items.map(function (b) {
      var q = b.price || {}, o = obj(b.objectId) || { tone: 1, short: '?' };
      var meta = ['Гостей: ' + b.guests];
      if (b.extras && b.extras.length) meta.push('♨ ' + b.extras.join(', '));
      if (q.tier) meta.push('знижка від ' + q.tier + ' ночей');
      if (b.source === 'demo') meta.push('демо');
      var actions = '';
      if (b.status === 'new') actions += '<button class="mini mini--dark" data-act="confirmed" data-id="' + b.id + '">Підтвердити</button>';
      if (b.status !== 'cancelled') actions += '<button class="mini" data-act="cancelled" data-id="' + b.id + '">Скасувати</button>';
      else actions += '<button class="mini" data-act="new" data-id="' + b.id + '">Відновити</button>';
      actions += '<a class="mini" href="' + tel(b.phone) + '">Подзвонити</a>';
      return '<article class="bk is-' + b.status + '">' +
        '<div class="bk__top"><div><span class="unit unit--t' + o.tone + '">' + esc(b.objectName) + '</span>' +
        '<div class="bk__name">' + esc(b.name) + '</div><a class="bk__phone" href="' + tel(b.phone) + '">' + esc(b.phone) + '</a></div>' +
        '<div class="bk__right"><span class="st st--' + b.status + '">' + STATUS[b.status] + '</span>' +
        (b.onRequest ? '<span class="bk__price bk__price--req">за домовленістю</span>'
          : '<span class="bk__price">' + money(b.total) + '</span>' + (b.prepayment ? '<span class="bk__prepay">передоплата ' + money(b.prepayment) + '</span>' : '')) + '</div></div>' +
        '<div class="bk__when">' + human(b.checkIn, true) + ' → ' + human(b.checkOut, true) + ' · ' + b.nights + ' ' + nightsWord(b.nights) + '</div>' +
        '<div class="bk__meta">' + esc(meta.join(' · ')) + ' · <span class="code">' + b.id + '</span></div>' +
        (b.comment ? '<div class="bk__comment">' + esc(b.comment) + '</div>' : '') +
        '<div class="bk__actions">' + actions + '</div></article>';
    }).join('');
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (!b) return;
    var status = b.getAttribute('data-act');
    if (status === 'cancelled' && !confirm('Скасувати це бронювання? Ночі знову стануть вільними.')) return;
    b.disabled = true;
    API.setStatus(b.getAttribute('data-id'), status).then(function () {
      toast(status === 'confirmed' ? 'Підтверджено. Не забудьте отримати передоплату.' : status === 'cancelled' ? 'Скасовано' : 'Відновлено');
      return reload();
    }).catch(function (ex) { toast(ex.message); b.disabled = false; });
  });

  /* ---------- календар ---------- */
  // Бронювання по ночах: {"2026-11-14:3": [бронь, бронь]} — в об'єкта з кількома одиницями їх може бути кілька.
  function owners() {
    var map = {};
    data.bookings.filter(function (b) { return b.status !== 'cancelled'; }).forEach(function (b) {
      V.nightsBetween(b.checkIn, b.checkOut).forEach(function (d) { (map[d + ':' + b.objectId] = map[d + ':' + b.objectId] || []).push(b); });
    });
    return map;
  }
  function closed(id, iso) { return (data.blocked[String(id)] || {})[iso] || 0; }
  /** Стан об'єкта на ніч: скільки одиниць у бронюваннях, скільки закрито, скільки всього. */
  function night(own, id, iso) {
    var units = obj(id).units, booked = (own[iso + ':' + id] || []).length, blk = closed(id, iso);
    var taken = Math.min(units, booked + blk);
    return { units: units, booked: booked, blocked: blk, taken: taken, free: units - taken,
      state: taken === 0 ? 'free' : taken >= units ? 'busy' : 'part' };
  }
  function shownIds() { return calObject === 'all' ? IDS : [+calObject]; }

  function renderLegend() {
    var h = '<span><i class="lg lg-free"></i>вільно</span><span><i class="lg lg-part"></i>частково зайнято</span><span><i class="lg lg-busy"></i>усе зайнято</span>' +
      '<span><i class="pill pill--booked">•</i>бронювання</span><span><i class="pill pill--blocked">•</i>закрито вручну</span>';
    if (calObject === 'all' && IDS.length > 1) h += '<span class="legend-keys">' + IDS.map(function (id) { return '<b>' + letter(id) + '</b> — ' + esc(obj(id).name); }).join(' · ') + '</span>';
    $('#calLegend').innerHTML = h;
  }

  function renderCalendar() {
    var own = owners(), ids = shownIds();
    var y = view.y, m = view.m;
    var offset = (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7, days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    var h = '<div class="acal__head"><button class="cal-nav" data-nav="-1" aria-label="Попередній місяць">‹</button><b>' + MONTHS[m] + ' ' + y +
      '</b><button class="cal-nav" data-nav="1" aria-label="Наступний місяць">›</button></div><div class="acal__grid">';
    DAY_SHORT.forEach(function (w) { h += '<div class="cal-wd">' + w + '</div>'; });
    for (var i = 0; i < offset; i++) h += '<span></span>';
    for (var d = 1; d <= days; d++) {
      var iso = V.toISO(new Date(Date.UTC(y, m, d))), busyN = 0, partN = 0, pills = '';
      ids.forEach(function (id) {
        var n = night(own, id, iso);
        var cls = n.state === 'free' ? 'pill--free' : n.booked ? 'pill--booked' : 'pill--blocked';
        if (n.state === 'busy') busyN++; else if (n.state === 'part') partN++;
        var label = n.units > 1 ? n.taken + '/' + n.units : (ids.length > 1 ? letter(id) : '•');
        pills += '<i class="pill ' + cls + (n.units > 1 ? ' pill--wide' : '') + (n.state === 'part' ? ' pill--part' : '') + '" title="' + esc(obj(id).name) + '">' + label + '</i>';
      });
      var state = busyN === ids.length ? 'busy' : (busyN || partN) ? 'part' : 'free';
      var dp = ids.length === 1 ? P.dayPrice(ids[0], iso) : undefined;
      var sub = dp === undefined ? '' : dp == null ? 'дог.' : V.shortPrice(dp);
      h += '<button class="aday ' + state + (iso === day ? ' is-focus' : '') + (iso < data.today ? ' is-past' : '') + '" data-day="' + iso + '">' +
        '<span class="aday__d">' + d + '</span><span class="aday__pills">' + pills + '</span>' + (sub ? '<span class="aday__p">' + sub + '</span>' : '') + '</button>';
    }
    $('#acal').innerHTML = h + '</div>';
  }
  $('#acal').addEventListener('click', function (e) {
    var nav = e.target.closest('[data-nav]');
    if (nav) {
      var dt = new Date(Date.UTC(view.y, view.m + (+nav.getAttribute('data-nav')), 1));
      view = { y: dt.getUTCFullYear(), m: dt.getUTCMonth() }; renderCalendar(); return;
    }
    var b = e.target.closest('[data-day]');
    if (b) { day = b.getAttribute('data-day'); renderCalendar(); renderDay(); }
  });

  function renderDay() {
    if (!day) return;
    var own = owners();
    $('#dayTitle').textContent = 'Ніч ' + human(day, true) + ' → ' + human(V.addDays(day, 1));
    var h = '';
    IDS.forEach(function (id) {
      var o = obj(id), n = night(own, id, day), dp = P.dayPrice(id, day);
      h += '<div class="dayrow"><span class="unit unit--t' + o.tone + '">' + esc(o.name) + '</span><span class="dayrow__price">' + (dp == null ? 'за домовленістю' : money(dp)) + '</span>';
      if (o.units > 1) h += '<span class="dayrow__units ' + n.state + '">зайнято ' + n.taken + ' з ' + o.units + '</span>';
      (own[day + ':' + id] || []).forEach(function (b) {
        h += '<span class="dayrow__who">' + esc(b.name) + ' · ' + human(b.checkIn) + '–' + human(b.checkOut) + ' <span class="st st--' + b.status + '">' + STATUS[b.status] + '</span></span>';
      });
      if (o.units > 1) {
        h += '<span class="dayrow__ctl"><span class="' + (n.blocked ? 'blk' : 'muted') + '">закрито вручну: ' + n.blocked + '</span>' +
          '<button class="mini" data-count="' + (n.blocked - 1) + '" data-o="' + id + '"' + (n.blocked ? '' : ' disabled') + ' aria-label="Відкрити одну одиницю">−</button>' +
          '<button class="mini" data-count="' + (n.blocked + 1) + '" data-o="' + id + '"' + (n.free ? '' : ' disabled') + ' aria-label="Закрити ще одну одиницю">+</button></span>';
      } else if (n.blocked) h += '<span class="blk">закрито вручну</span><button class="mini" data-block="0" data-o="' + id + '">Відкрити</button>';
      else if (!n.booked) h += '<span class="ok">вільно</span><button class="mini" data-block="1" data-o="' + id + '">Закрити</button>';
      h += '</div>';
    });
    h += '<div class="dayactions"><button class="mini mini--dark" data-block="1" data-o="all">Закрити все вільне</button><button class="mini" data-block="0" data-o="all">Відкрити все</button></div>' +
      '<p class="muted small">Ночі з бронюванням тут не змінюються — скасуйте заявку у списку.</p>';
    $('#dayBody').innerHTML = h;
  }
  $('#dayBody').addEventListener('click', function (e) {
    var b = e.target.closest('[data-block], [data-count]');
    if (!b || b.disabled) return;
    var ids = b.getAttribute('data-o') === 'all' ? IDS.slice() : [+b.getAttribute('data-o')];
    var count = b.hasAttribute('data-count') ? +b.getAttribute('data-count') : null;
    var block = count != null ? count > 0 : b.getAttribute('data-block') === '1';
    API.blockNights([day], ids, block, count).then(function () {
      toast(human(day) + (count != null ? ' — закрито одиниць: ' + count : block ? ' — закрито' : ' — відкрито'));
      return reload();
    }).catch(function (ex) { toast(ex.message); });
  });

  /* ---------- ціни ---------- */
  // Усі числові поля — type=number зі step=1: ціна може бути будь-яким цілим числом (4500, 20000, 12345).
  function num(name, label, value, min, extra) {
    return '<label class="field"><span>' + label + '</span><input name="' + name + '" type="number" inputmode="numeric" min="' + min + '" step="1" value="' + (value == null ? '' : value) + '"' + (extra || ' required') + '></label>';
  }
  function tierRow(t) {
    return '<div class="tier-row"><span>від</span><input name="tn" type="number" min="2" max="60" step="1" value="' + (t ? t.nights : '') + '" required aria-label="Від скількох ночей">' +
      '<span>ночей —</span><input name="tp" type="number" min="1" step="1" value="' + (t ? t.price : '') + '" required aria-label="Ціна за ніч, грн"><span>грн / ніч</span>' +
      '<button type="button" class="mini" data-tier-del aria-label="Прибрати знижку">✕</button></div>';
  }
  function guestTierRow(t) {
    return '<div class="tier-row"><span>до</span><input name="gu" type="number" min="1" max="50" step="1" value="' + (t ? t.upTo : '') + '" required aria-label="До скількох гостей">' +
      '<span>гостей —</span><input name="gp" type="number" min="1" step="1" value="' + (t ? t.price : '') + '" required aria-label="Ціна, грн"><span>грн</span>' +
      '<button type="button" class="mini" data-tier-del aria-label="Прибрати рядок">✕</button></div>';
  }
  function objSelect(value) {
    return '<select name="objectId" class="sel"><option value="all"' + (value == null ? ' selected' : '') + '>Усі об\'єкти</option>' +
      IDS.map(function (id) { return '<option value="' + id + '"' + (value === id ? ' selected' : '') + '>' + esc(obj(id).name) + '</option>'; }).join('') + '</select>';
  }
  function periodRow(p) {
    var onReq = p ? p.price == null : false;
    return '<form class="period-row" ' + (p ? 'data-period="' + p.id + '"' : 'data-period-new') + '>' +
      '<label class="field"><span>Назва</span><input name="name" value="' + esc(p ? p.name : '') + '" placeholder="Новорічні свята"></label>' +
      '<label class="field"><span>Об\'єкт</span>' + objSelect(p ? p.objectId : null) + '</label>' +
      '<label class="field"><span>Перша ніч</span><input name="start" type="date" value="' + (p ? p.start : '') + '" required></label>' +
      '<label class="field"><span>Остання ніч</span><input name="end" type="date" value="' + (p ? p.end : '') + '" required></label>' +
      '<label class="field period-price"><span>Ціна, грн / ніч</span><input name="price" type="number" inputmode="numeric" min="1" step="1" value="' + (p && p.price ? p.price : '') + '"' + (onReq ? ' disabled' : '') + '></label>' +
      '<label class="check period-req"><input type="checkbox" name="onRequest"' + (onReq ? ' checked' : '') + '><span>Ціна за домовленістю</span></label>' +
      '<div class="season-btns"><button class="mini' + (p ? ' mini--dark' : '') + '">' + (p ? 'Зберегти' : 'Додати сезон') + '</button>' +
      (p ? '<button class="mini" type="button" data-del="' + p.id + '">Видалити</button>' : '') + '</div></form>';
  }
  function renderPrices() {
    if (editing()) return; // не перебиваємо редагування
    $('#priceObjs').innerHTML = IDS.map(function (id) {
      var o = obj(id);
      return '<section class="abox pobj pobj--t' + o.tone + '">' +
        '<div class="abox__head"><h2>' + esc(o.name) + '</h2><span class="muted small">' + esc(o.guestsText) + ' · від ' + money(P.minPrice(id)) + ' / ніч</span></div>' +
        '<form class="pobj__base" data-prices="' + id + '"><div class="pobj__fields">' +
        num('price', 'Ціна за ніч, грн', o.price, 1) +
        num('extraGuestPrice', 'Доплата за гостя, грн / ніч', o.extraGuestPrice, 0) +
        num('baseGuests', 'Гостей у ціні', o.baseGuests, 1) +
        num('maxGuests', 'Максимум гостей', o.maxGuests, 1) +
        num('minNights', 'Мінімум ночей', o.minNights, 1) +
        num('units', 'Однакових одиниць', o.units, 1) + '</div>' +
        '<div class="pobj__tiers"><span class="pobj__label">Знижка за тривалість</span><div class="tiers">' + o.tiers.map(tierRow).join('') + '</div>' +
        '<button type="button" class="linkbtn" data-tier-add>+ додати знижку</button></div>' +
        '<button class="mini mini--dark">Зберегти</button></form></section>';
    }).join('');
    $('#extrasBox').hidden = !data.extras.length;
    $('#extrasBox').innerHTML = '<div class="abox__head"><h2>Додаткові послуги</h2><span class="muted small">сума додається до бронювання</span></div>' +
      '<div class="extras-admin">' + data.extras.map(function (e) {
        var tiers = e.guestPrices || [];
        return '<form class="extra-row" data-extra="' + e.key + '"><b>' + esc(e.name) + '<small>' + esc(e.unitLabel) + '</small></b>' +
          num('price', tiers.length ? 'Ціна, якщо гостей більше' : 'Ціна, грн', e.price, 1) +
          '<div class="pobj__tiers"><span class="pobj__label">Ціна за кількістю гостей</span><div class="tiers">' + tiers.map(guestTierRow).join('') + '</div>' +
          '<button type="button" class="linkbtn" data-gtier-add>+ додати рядок</button></div>' +
          '<button class="mini mini--dark">Зберегти</button></form>';
      }).join('') + '</div>';
    $('#periodsBox').innerHTML = '<div class="abox__head"><h2>Сезони</h2></div>' +
      '<p class="muted small">На ці ночі діє вказана ціна замість звичайної (доплата за гостей додається як завжди). З галочкою «Ціна за домовленістю» сайт замість суми показує «Уточніть ціну у власника» — заявку гість усе одно може надіслати.</p>' +
      '<div class="seasons-table">' + data.periods.map(periodRow).join('') + periodRow(null) + '</div>';
    var C = data.config;
    $('#fixedRules').innerHTML = '<h3 class="asub">Що змінюється не тут</h3><ul>' +
      '<li>Передоплата ' + C.prepaymentPercent + '%, час заїзду й виїзду, правила скасування — у файлі config/site.yaml.</li>' +
      '<li>Назви, описи, фото, контакти — теж у config/site.yaml. Зверніться до розробника сайту.</li></ul>';
  }

  var box = $('#priceObjs');
  function tierClicks(e) {
    var add = e.target.closest('[data-tier-add], [data-gtier-add]');
    if (add) {
      var wrap = $('.tiers', add.closest('form'));
      wrap.insertAdjacentHTML('beforeend', add.hasAttribute('data-gtier-add') ? guestTierRow(null) : tierRow(null));
      $('.tier-row:last-child input', wrap).focus();
    }
    var del = e.target.closest('[data-tier-del]');
    if (del) del.closest('.tier-row').remove();
  }
  box.addEventListener('click', tierClicks);
  $('#extrasBox').addEventListener('click', tierClicks);
  function done(msg) { toast(msg); if (document.activeElement) document.activeElement.blur(); return reload(); }
  box.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target, id = +f.getAttribute('data-prices');
    var tiers = $$('.tier-row', f).map(function (r) { return { nights: +$('[name=tn]', r).value, price: +$('[name=tp]', r).value }; });
    API.saveObjectPrices({ id: id, price: f.price.value, tiers: tiers, extraGuestPrice: f.extraGuestPrice.value,
      baseGuests: f.baseGuests.value, maxGuests: f.maxGuests.value, minNights: f.minNights.value, units: f.units.value })
      .then(function () { return done('«' + obj(id).name + '» — збережено'); })
      .catch(function (ex) { toast(ex.message); });
  });
  $('#extrasBox').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target;
    var tiers = $$('.tier-row', f).map(function (r) { return { upTo: +$('[name=gu]', r).value, price: +$('[name=gp]', r).value }; });
    tiers.sort(function (a, b) { return a.upTo - b.upTo; });
    API.saveExtraPrice(f.getAttribute('data-extra'), f.price.value, tiers)
      .then(function () { return done('Ціну збережено'); })
      .catch(function (ex) { toast(ex.message); });
  });
  var pbox = $('#periodsBox');
  pbox.addEventListener('change', function (e) {
    if (e.target.name !== 'onRequest') return;
    var price = e.target.closest('form').price;
    price.disabled = e.target.checked;
    if (!e.target.checked) price.focus();
  });
  pbox.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target, body = { name: f.name.value, objectId: f.objectId.value, start: f.start.value, end: f.end.value,
      onRequest: f.onRequest.checked, price: f.price.value };
    if (f.hasAttribute('data-period')) body.id = f.getAttribute('data-period');
    API.savePeriod(body).then(function () { return done(body.id ? 'Сезон збережено' : 'Сезон додано'); })
      .catch(function (ex) { toast(ex.message); });
  });
  pbox.addEventListener('click', function (e) {
    var b = e.target.closest('[data-del]');
    if (!b || !confirm('Видалити сезон? На ці дати діятиме звичайна ціна.')) return;
    API.deletePeriod(+b.getAttribute('data-del')).then(function () { toast('Сезон видалено'); b.blur(); return reload(); })
      .catch(function (ex) { toast(ex.message); });
  });

  reload();
})();
