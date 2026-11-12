/* Forest House — адмінка: заявки по будинках, зайнятість усіх трьох, ціни (знижки за тривалість, свята, чан і баня). */
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
  function letter(id) { return obj(id).short.charAt(0); }
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
        return '<button type="button" data-seg="' + id + '" class="seg--' + o.tone + (String(current) === String(id) ? ' is-on' : '') + '">' + esc(o.short) + '</button>';
      }).join('');
  }
  $('#bkObject').addEventListener('click', function (e) {
    var b = e.target.closest('[data-seg]'); if (!b) return;
    bkObject = b.getAttribute('data-seg'); seg(this, bkObject, 'Усі'); renderList();
  });
  $('#calObject').addEventListener('click', function (e) {
    var b = e.target.closest('[data-seg]'); if (!b) return;
    calObject = b.getAttribute('data-seg'); seg(this, calObject, 'Усі три'); renderCalendar(); renderLegend();
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
    var tonight = IDS.filter(function (id) { return (data.busy[String(id)] || []).indexOf(data.today) !== -1; }).length;
    $('#stats').innerHTML =
      '<div class="stat stat--accent"><span>Нові заявки</span><b>' + nNew + '</b></div>' +
      '<div class="stat"><span>Майбутні заїзди</span><b>' + upcoming + '</b></div>' +
      '<div class="stat"><span>Зайнято сьогодні</span><b>' + tonight + ' / ' + IDS.length + '</b></div>' +
      '<div class="stat"><span>Підтверджено на суму</span><b>' + money(income) + '</b></div>';
    seg($('#bkObject'), bkObject, 'Усі');
    seg($('#calObject'), calObject, 'Усі три');
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
      var q = b.price || {}, o = obj(b.objectId) || { tone: 'green', short: '?' };
      var meta = ['Гостей: ' + b.guests];
      if (b.extras && b.extras.length) meta.push('♨ ' + b.extras.join(', '));
      if (q.tier) meta.push('знижка від ' + q.tier + ' діб');
      var actions = '';
      if (b.status === 'new') actions += '<button class="mini mini--dark" data-act="confirmed" data-id="' + b.id + '">Підтвердити</button>';
      if (b.status !== 'cancelled') actions += '<button class="mini" data-act="cancelled" data-id="' + b.id + '">Скасувати</button>';
      else actions += '<button class="mini" data-act="new" data-id="' + b.id + '">Відновити</button>';
      actions += '<a class="mini" href="' + tel(b.phone) + '">Подзвонити</a>';
      return '<article class="bk is-' + b.status + '">' +
        '<div class="bk__top"><div><span class="unit unit--' + o.tone + '">' + esc(b.objectName) + '</span>' +
        '<div class="bk__name">' + esc(b.name) + '</div><a class="bk__phone" href="' + tel(b.phone) + '">' + esc(b.phone) + '</a></div>' +
        '<div class="bk__right"><span class="st st--' + b.status + '">' + STATUS[b.status] + '</span>' +
        (b.onRequest ? '<span class="bk__price bk__price--req">за домовленістю</span>'
          : '<span class="bk__price">' + money(b.total) + '</span><span class="bk__prepay">передоплата ' + money(b.prepayment) + '</span>') + '</div></div>' +
        '<div class="bk__when">' + human(b.checkIn, true) + ' → ' + human(b.checkOut, true) + ' · ' + b.nights + ' діб</div>' +
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
  function owners() {
    var map = {};
    data.bookings.filter(function (b) { return b.status !== 'cancelled'; }).forEach(function (b) {
      V.nightsBetween(b.checkIn, b.checkOut).forEach(function (d) { map[d + ':' + b.objectId] = b; });
    });
    return map;
  }
  function blockedSet() {
    var s = {};
    Object.keys(data.blocked).forEach(function (o) { data.blocked[o].forEach(function (d) { s[d + ':' + o] = true; }); });
    return s;
  }
  function shownIds() { return calObject === 'all' ? IDS : [+calObject]; }

  function renderLegend() {
    var h = calObject === 'all'
      ? '<span><i class="lg lg-free"></i>усі вільні</span><span><i class="lg lg-part"></i>частково зайнято</span><span><i class="lg lg-busy"></i>усі зайняті</span>'
      : '<span><i class="lg lg-free"></i>вільно</span><span><i class="lg lg-busy"></i>зайнято</span>';
    h += '<span><i class="pill pill--booked">' + (calObject === 'all' ? 'А' : '•') + '</i>бронювання</span>' +
      '<span><i class="pill pill--blocked">' + (calObject === 'all' ? 'А' : '•') + '</i>закрито вручну</span>';
    if (calObject === 'all') h += '<span class="legend-keys">' + IDS.map(function (id) { return '<b>' + letter(id) + '</b> — ' + esc(obj(id).name); }).join(' · ') + '</span>';
    $('#calLegend').innerHTML = h;
  }

  function renderCalendar() {
    var own = owners(), blk = blockedSet(), ids = shownIds();
    var y = view.y, m = view.m;
    var offset = (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7, days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    var h = '<div class="acal__head"><button class="cal-nav" data-nav="-1" aria-label="Попередній місяць">‹</button><b>' + MONTHS[m] + ' ' + y +
      '</b><button class="cal-nav" data-nav="1" aria-label="Наступний місяць">›</button></div><div class="acal__grid">';
    DAY_SHORT.forEach(function (w) { h += '<div class="cal-wd">' + w + '</div>'; });
    for (var i = 0; i < offset; i++) h += '<span></span>';
    for (var d = 1; d <= days; d++) {
      var iso = V.toISO(new Date(Date.UTC(y, m, d))), busyN = 0, pills = '';
      ids.forEach(function (id) {
        var k = iso + ':' + id, cls = own[k] ? 'pill--booked' : blk[k] ? 'pill--blocked' : 'pill--free';
        if (own[k] || blk[k]) busyN++;
        pills += '<i class="pill ' + cls + '" title="' + esc(obj(id).name) + '">' + (ids.length > 1 ? letter(id) : '•') + '</i>';
      });
      var state = busyN === 0 ? 'free' : busyN === ids.length ? 'busy' : 'part';
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
    var own = owners(), blk = blockedSet();
    $('#dayTitle').textContent = 'Ніч ' + human(day, true) + ' → ' + human(V.addDays(day, 1));
    var h = '';
    IDS.forEach(function (id) {
      var k = day + ':' + id, b = own[k], o = obj(id);
      var dp = P.dayPrice(id, day);
      h += '<div class="dayrow"><span class="unit unit--' + o.tone + '">' + esc(o.name) + '</span><span class="dayrow__price">' + (dp == null ? 'за домовленістю' : money(dp)) + '</span>';
      if (b) h += '<span class="dayrow__who">' + esc(b.name) + ' · ' + human(b.checkIn) + '–' + human(b.checkOut) + ' <span class="st st--' + b.status + '">' + STATUS[b.status] + '</span></span>';
      else if (blk[k]) h += '<span class="blk">закрито вручну</span><button class="mini" data-block="0" data-o="' + id + '">Відкрити</button>';
      else h += '<span class="ok">вільно</span><button class="mini" data-block="1" data-o="' + id + '">Закрити</button>';
      h += '</div>';
    });
    h += '<div class="dayactions"><button class="mini mini--dark" data-block="1" data-o="all">Закрити всі вільні</button><button class="mini" data-block="0" data-o="all">Відкрити всі</button></div>' +
      '<p class="muted small">Ночі з бронюванням тут не змінюються — скасуйте заявку у списку.</p>';
    $('#dayBody').innerHTML = h;
  }
  $('#dayBody').addEventListener('click', function (e) {
    var b = e.target.closest('[data-block]');
    if (!b) return;
    var own = owners();
    var ids = b.getAttribute('data-o') === 'all' ? IDS.slice() : [+b.getAttribute('data-o')];
    ids = ids.filter(function (id) { return !own[day + ':' + id]; });
    if (!ids.length) { toast('Ця ніч зайнята бронюванням'); return; }
    var block = b.getAttribute('data-block') === '1';
    API.blockNights([day], ids, block).then(function () {
      toast(human(day) + (block ? ' — закрито' : ' — відкрито'));
      return reload();
    }).catch(function (ex) { toast(ex.message); });
  });

  /* ---------- ціни ---------- */
  function tierRow(t) {
    return '<div class="tier-row"><span>від</span><input name="tn" type="number" min="2" max="60" step="1" value="' + (t ? t.nights : '') + '" required aria-label="Від скількох діб">' +
      '<span>діб —</span><input name="tp" type="number" min="1" step="1" value="' + (t ? t.price : '') + '" required aria-label="Ціна за добу, грн"><span>грн / доба</span>' +
      '<button type="button" class="mini" data-tier-del aria-label="Прибрати знижку">✕</button></div>';
  }
  function objSelect(value) {
    return '<select name="objectId" class="sel"><option value="all"' + (value == null ? ' selected' : '') + '>Усі будинки</option>' +
      IDS.map(function (id) { return '<option value="' + id + '"' + (value === id ? ' selected' : '') + '>' + esc(obj(id).name) + '</option>'; }).join('') + '</select>';
  }
  function periodRow(p) {
    var onReq = !p || p.price == null;
    return '<form class="period-row" ' + (p ? 'data-period="' + p.id + '"' : 'data-period-new') + '>' +
      '<label class="field"><span>Назва</span><input name="name" value="' + esc(p ? p.name : '') + '" placeholder="Новорічні свята"></label>' +
      '<label class="field"><span>Будинок</span>' + objSelect(p ? p.objectId : null) + '</label>' +
      '<label class="field"><span>Перша доба</span><input name="start" type="date" value="' + (p ? p.start : '') + '" required></label>' +
      '<label class="field"><span>Остання доба</span><input name="end" type="date" value="' + (p ? p.end : '') + '" required></label>' +
      '<label class="field period-price"><span>Ціна, грн / доба</span><input name="price" type="number" min="1" step="1" value="' + (p && p.price ? p.price : '') + '"' + (onReq ? ' disabled' : '') + '></label>' +
      '<label class="check period-req"><input type="checkbox" name="onRequest"' + (onReq ? ' checked' : '') + '><span>Ціна за домовленістю</span></label>' +
      '<div class="season-btns"><button class="mini' + (p ? ' mini--dark' : '') + '">' + (p ? 'Зберегти' : 'Додати період') + '</button>' +
      (p ? '<button class="mini" type="button" data-del="' + p.id + '">Видалити</button>' : '') + '</div></form>';
  }
  function renderPrices() {
    if (editing()) return; // не перебиваємо редагування
    $('#priceObjs').innerHTML = IDS.map(function (id) {
      var o = obj(id);
      return '<section class="abox pobj pobj--' + o.tone + '">' +
        '<div class="abox__head"><h2>' + esc(o.name) + '</h2><span class="muted small">' + esc(o.guestsText) + ' · від ' + money(P.minPrice(id)) + ' / доба</span></div>' +
        '<form class="pobj__base" data-prices="' + id + '">' +
        '<label class="field"><span>Ціна за добу, грн</span><input name="price" type="number" min="1" step="1" value="' + o.price + '" required></label>' +
        '<div class="pobj__tiers"><span class="pobj__label">Знижка за тривалість</span><div class="tiers">' + o.tiers.map(tierRow).join('') + '</div>' +
        '<button type="button" class="linkbtn" data-tier-add>+ додати знижку</button></div>' +
        '<button class="mini mini--dark">Зберегти ціни</button></form></section>';
    }).join('');
    $('#extrasBox').innerHTML = '<div class="abox__head"><h2>Чан і баня</h2><span class="muted small">ціна за вечір, додається до суми бронювання</span></div>' +
      '<div class="extras-admin">' + data.extras.map(function (e) {
        return '<form class="extra-row" data-extra="' + e.key + '"><b>' + esc(e.name) + '</b>' +
          '<label class="field"><span>Ціна за вечір, грн</span><input name="price" type="number" min="1" step="1" value="' + e.price + '" required></label>' +
          '<button class="mini mini--dark">Зберегти</button></form>';
      }).join('') + '</div>';
    $('#periodsBox').innerHTML = '<div class="abox__head"><h2>Святкові періоди</h2></div>' +
      '<p class="muted small">На ці доби діє вказана ціна замість звичайної, або — з галочкою «Ціна за домовленістю» — сайт замість суми показує «Уточніть ціну у власника». Заявку гість усе одно може надіслати.</p>' +
      '<div class="seasons-table">' + data.periods.map(periodRow).join('') + periodRow(null) + '</div>';
    var C = data.config;
    $('#fixedRules').innerHTML = '<h3 class="asub">Загальні правила (файл site_content.py)</h3><ul>' +
      '<li>Передоплата ' + C.prepaymentPercent + '%, мінімум ' + C.minNights + ' доб.</li>' +
      '<li>Заселення о ' + C.checkIn + ', виселення до ' + C.checkOut + '.</li>' +
      '<li>Кількість гостей і описи будинків — у site_content.py (OBJECTS).</li></ul>';
  }

  var box = $('#priceObjs');
  box.addEventListener('click', function (e) {
    if (e.target.closest('[data-tier-add]')) {
      var f = e.target.closest('form'), wrap = $('.tiers', f);
      wrap.insertAdjacentHTML('beforeend', tierRow(null));
      $('.tier-row:last-child input', wrap).focus();
    }
    var del = e.target.closest('[data-tier-del]');
    if (del) del.closest('.tier-row').remove();
  });
  box.addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target, id = +f.getAttribute('data-prices');
    var tiers = $$('.tier-row', f).map(function (r) { return { nights: +$('[name=tn]', r).value, price: +$('[name=tp]', r).value }; });
    API.saveObjectPrices({ id: id, price: f.price.value, tiers: tiers })
      .then(function () { toast('Ціни «' + obj(id).name + '» збережено'); if (document.activeElement) document.activeElement.blur(); return reload(); })
      .catch(function (ex) { toast(ex.message); });
  });
  $('#extrasBox').addEventListener('submit', function (e) {
    e.preventDefault();
    var f = e.target;
    API.saveExtraPrice(f.getAttribute('data-extra'), f.price.value)
      .then(function () { toast('Ціну збережено'); if (document.activeElement) document.activeElement.blur(); return reload(); })
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
    API.savePeriod(body).then(function () { toast(body.id ? 'Період збережено' : 'Період додано'); if (document.activeElement) document.activeElement.blur(); return reload(); })
      .catch(function (ex) { toast(ex.message); });
  });
  pbox.addEventListener('click', function (e) {
    var b = e.target.closest('[data-del]');
    if (!b || !confirm('Видалити період? На ці дати діятиме звичайна ціна.')) return;
    API.deletePeriod(+b.getAttribute('data-del')).then(function () { toast('Період видалено'); b.blur(); return reload(); })
      .catch(function (ex) { toast(ex.message); });
  });

  reload();
})();
