/* Forest House — меню, галереї, календар обраного будинку, розрахунок суми (знижки, чан, баня), бронювання. */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var V = window.FHPricing;

  /* ---------- Шапка та меню ---------- */
  var header = $(".site-header"), nav = $("#nav"), toggle = $(".nav-toggle");
  function closeMenu() {
    nav.classList.remove("open"); header.classList.remove("menu-open"); toggle.setAttribute("aria-expanded", "false");
  }
  toggle.addEventListener("click", function () {
    var open = nav.classList.toggle("open");
    header.classList.toggle("menu-open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  $$("a", nav).forEach(function (a) { a.addEventListener("click", closeMenu); });

  /* ---------- Плавна поява блоків ---------- */
  if ("IntersectionObserver" in window) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("visible"); io.unobserve(e.target); } });
    }, { threshold: 0.1 });
    $$(".reveal").forEach(function (el) { io.observe(el); });
  } else {
    $$(".reveal").forEach(function (el) { el.classList.add("visible"); });
  }

  /* ---------- Мобільна кнопка «Забронювати» ---------- */
  var mobileCta = $(".mobile-cta"), bookingSection = $("#booking");
  function onScroll() {
    header.classList.toggle("scrolled", window.scrollY > 20);
    if (!mobileCta || !bookingSection) return;
    var r = bookingSection.getBoundingClientRect();
    mobileCta.classList.toggle("show", window.scrollY > window.innerHeight * 0.6 && !(r.top < window.innerHeight && r.bottom > 0));
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- Лайтбокс галереї ---------- */
  var lightbox = $("#lightbox"), lbItems = [], current = 0;
  function showPhoto(i) {
    current = (i + lbItems.length) % lbItems.length;
    var item = lbItems[current], img = $("img", lightbox);
    img.src = item.dataset.full; img.alt = item.dataset.caption;
    $("figcaption", lightbox).textContent = item.dataset.caption;
  }
  function closeLightbox() { lightbox.hidden = true; document.body.style.overflow = ""; }
  $$(".gallery-item[data-full]").forEach(function (item) {
    item.addEventListener("click", function () {
      lbItems = $$(".gallery-item[data-full]", item.parentNode);
      showPhoto(lbItems.indexOf(item));
      lightbox.hidden = false; document.body.style.overflow = "hidden";
    });
  });
  $(".lightbox-close", lightbox).addEventListener("click", closeLightbox);
  $(".lightbox-nav.prev", lightbox).addEventListener("click", function () { showPhoto(current - 1); });
  $(".lightbox-nav.next", lightbox).addEventListener("click", function () { showPhoto(current + 1); });
  lightbox.addEventListener("click", function (e) { if (e.target === lightbox) closeLightbox(); });
  document.addEventListener("keydown", function (e) {
    if (lightbox.hidden) return;
    if (e.key === "Escape") closeLightbox();
    if (e.key === "ArrowLeft") showPhoto(current - 1);
    if (e.key === "ArrowRight") showPhoto(current + 1);
  });
  var touchX = null;
  lightbox.addEventListener("touchstart", function (e) { touchX = e.touches[0].clientX; }, { passive: true });
  lightbox.addEventListener("touchend", function (e) {
    if (touchX === null) return;
    var dx = e.changedTouches[0].clientX - touchX;
    if (Math.abs(dx) > 50) showPhoto(current + (dx < 0 ? 1 : -1));
    touchX = null;
  });

  /* ---------- Модальне вікно ---------- */
  var modal = $("#success-modal");
  $$("[data-close]", modal).forEach(function (c) { c.addEventListener("click", function () { modal.hidden = true; }); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") modal.hidden = true; });

  /* ---------- Бронювання ---------- */
  var form = $("#booking-form");
  if (!form) return;

  var MONTHS = ["Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень", "Липень",
    "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень"];
  var MONTHS_GEN = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня",
    "серпня", "вересня", "жовтня", "листопада", "грудня"];
  var WD = ["пн", "вт", "ср", "чт", "пт", "сб", "нд"];

  var calEl = $("#calendar"), inIn = $("#check_in"), inOut = $("#check_out"), guestsEl = $("#guests");
  var rulesEl = $("#rules-ok"), monthsBox = $(".cal-months", calEl), titleEl = $(".cal-title", calEl);
  var hintEl = $("#cal-hint"), summary = $("#summary"), formError = $("#form-error"), calObject = $("#cal-object");

  var data = null, P = null, busy = {}, state = { checkIn: null, checkOut: null }, view = null;

  function money(n) { return V.formatUAH(n); }
  function human(iso) { var d = V.toDate(iso); return d.getUTCDate() + " " + MONTHS_GEN[d.getUTCMonth()]; }
  function plural(n, one, few, many) {
    if (n % 10 === 1 && n % 100 !== 11) return one;
    if (n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14)) return few;
    return many;
  }
  function nightsWord(n) { return plural(n, "доба", "доби", "діб"); }
  function extrasChecked() { return $$('input[name="extras"]:checked', form).map(function (i) { return i.value; }); }
  function isValidIso(v) { return /^\d{4}-\d{2}-\d{2}$/.test(v || ""); }

  function objectId() { var r = $('input[name="objectId"]:checked', form); return r ? +r.value : 0; }
  function obj() { return P.obj(objectId()); }
  function busySet() { return busy[objectId()] || {}; }
  function isBusy(iso) { return !!busySet()[iso]; }
  function canCheckIn(iso) { return iso >= data.today && iso < data.lastDate && !isBusy(iso); }
  function limitFor(iso) { return P.checkoutLimit(busySet(), iso, data.lastDate); }
  function minNights() { return P.CONFIG.minNights; }

  function fillGuests() {
    var o = obj(), cur = +guestsEl.value || 2, html = "";
    for (var n = 1; n <= o.maxGuests; n++) {
      html += '<option value="' + n + '">' + n + " " + plural(n, "гість", "гості", "гостей") + "</option>";
    }
    guestsEl.innerHTML = html;
    guestsEl.value = String(Math.min(cur, o.maxGuests));
    $("#guests-note").textContent = o.guestsText;
  }

  function monthsVisible() { return window.matchMedia("(max-width: 860px)").matches ? 1 : 2; }

  function render() {
    var html = "";
    for (var m = 0; m < 2; m++) {
      var first = new Date(Date.UTC(view.y, view.m + m, 1));
      html += renderMonth(first.getUTCFullYear(), first.getUTCMonth());
    }
    monthsBox.innerHTML = html;
    var last = new Date(Date.UTC(view.y, view.m + monthsVisible() - 1, 1));
    titleEl.textContent = monthsVisible() === 1 ? MONTHS[view.m] + " " + view.y
      : MONTHS[view.m] + " — " + MONTHS[last.getUTCMonth()] + " " + last.getUTCFullYear();
    var t = V.toDate(data.today), l = V.toDate(data.lastDate);
    $('[data-dir="-1"]', calEl).disabled = view.y * 12 + view.m <= t.getUTCFullYear() * 12 + t.getUTCMonth();
    $('[data-dir="1"]', calEl).disabled = last.getUTCFullYear() * 12 + last.getUTCMonth() >= l.getUTCFullYear() * 12 + l.getUTCMonth();
    calObject.textContent = "· " + obj().name;
  }

  function renderMonth(y, m) {
    var id = objectId();
    var html = '<div class="cal-month"><h4>' + MONTHS[m] + " " + y + '</h4><div class="cal-grid">';
    WD.forEach(function (w) { html += '<div class="cal-wd">' + w + "</div>"; });
    var offset = (new Date(Date.UTC(y, m, 1)).getUTCDay() + 6) % 7;
    var days = new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
    for (var i = 0; i < offset; i++) html += '<span class="cal-day empty"></span>';

    var picking = state.checkIn && !state.checkOut;
    var limit = picking ? limitFor(state.checkIn) : null;
    var minOut = picking ? V.addDays(state.checkIn, minNights()) : null;

    for (var d = 1; d <= days; d++) {
      var iso = V.toISO(new Date(Date.UTC(y, m, d)));
      var cls = ["cal-day"], disabled = false, b = isBusy(iso), price = P.dayPrice(id, iso);
      if (price == null) cls.push("on-request");
      if (iso === data.today) cls.push("today");

      if (iso < data.today) { cls.push("past"); disabled = true; }
      else if (iso >= data.lastDate && !(picking && iso === data.lastDate)) { cls.push("out-of-range"); disabled = true; }
      else {
        cls.push(b ? "busy" : "free");
        if (picking && iso > state.checkIn) {
          if (iso > limit) { cls.push("out-of-range"); disabled = true; }
          else if (iso < minOut) { cls.push("too-short"); disabled = true; }
          else cls.push("checkout-ok");
        } else if (b) { disabled = true; }
      }
      if (state.checkIn === iso) cls.push("start");
      if (state.checkOut === iso) cls.push("end");
      if (state.checkIn && state.checkOut && iso > state.checkIn && iso < state.checkOut) cls.push("in-range");

      var label = d + " " + MONTHS_GEN[m] + (b ? ", зайнято" : ", вільно") + ", " + (price == null ? "ціна за домовленістю" : price + " грн");
      html += '<button type="button" class="' + cls.join(" ") + '" data-iso="' + iso + '"' + (disabled ? " disabled" : "") +
        ' aria-label="' + label + '"><span class="d">' + d + '</span><span class="p">' + (price == null ? "дог." : V.shortPrice(price)) + "</span></button>";
    }
    return html + "</div></div>";
  }

  function pick(iso) {
    clearError();
    if (!state.checkIn || state.checkOut || iso <= state.checkIn) {
      if (canCheckIn(iso)) { state.checkIn = iso; state.checkOut = null; }
    } else {
      var limit = limitFor(state.checkIn);
      if (iso <= limit && iso >= V.addDays(state.checkIn, minNights())) state.checkOut = iso;
      else if (canCheckIn(iso)) { state.checkIn = iso; state.checkOut = null; }
    }
    sync();
  }

  function sync() {
    inIn.value = state.checkIn || "";
    inOut.value = state.checkOut || "";
    inIn.min = data.today; inIn.max = V.addDays(data.lastDate, -1);
    inOut.min = state.checkIn ? V.addDays(state.checkIn, minNights()) : V.addDays(data.today, minNights());
    inOut.max = data.lastDate;
    render();
    updateSummary();
  }

  function setHint(text, warn) { hintEl.textContent = text; hintEl.classList.toggle("warn", !!warn); }

  function currentQuote() {
    if (!state.checkIn || !state.checkOut) return null;
    return P.quote(objectId(), state.checkIn, state.checkOut, +guestsEl.value, extrasChecked());
  }

  function updateSummary() {
    var empty = $(".summary-empty", summary), body = $(".summary-body", summary), o = obj();
    if (!state.checkIn) setHint("Оберіть дату заїзду.");
    else if (!state.checkOut) {
      var lim = limitFor(state.checkIn);
      if (!lim || lim < V.addDays(state.checkIn, minNights())) {
        setHint("З " + human(state.checkIn) + " вільна лише одна ніч, а мінімум — " + minNights() + ". Оберіть іншу дату заїзду.", true);
      } else {
        setHint("Заїзд " + human(state.checkIn) + ". Тепер оберіть дату виїзду (мінімум " + minNights() + " " + nightsWord(minNights()) + ").");
      }
    }
    var q = currentQuote();
    if (!q) { empty.hidden = false; body.hidden = true; return; }
    empty.hidden = true; body.hidden = false;

    $(".summary-unit", summary).textContent = o.name + " · " + q.guests + " " + plural(q.guests, "гість", "гості", "гостей");
    var html = "";
    q.lines.forEach(function (l) {
      html += "<li><span>" + l.count + " " + nightsWord(l.count) + " × " + money(l.price) + (l.label ? ' <em class="' + (l.kind === "tier" ? "tag-good" : "") + '">' + l.label + "</em>" : "") +
        "</span><span>" + money(l.sum) + "</span></li>";
    });
    if (q.onRequest) html += '<li class="note"><span>' + q.missingNights.length + " " + nightsWord(q.missingNights.length) + " — святкова ціна за домовленістю</span><span>?</span></li>";
    if (q.tier) {
      var tierDays = q.lines.filter(function (l) { return l.kind === "tier"; }).reduce(function (s, l) { return s + l.count; }, 0);
      html += '<li class="good"><span>Знижка за тривалість (замість ' + money(q.basePrice) + " / доба)</span><span>−" + money((q.basePrice - q.rate) * tierDays) + "</span></li>";
    } else {
      var next = obj().tiers.filter(function (t) { return t.nights > q.nights; })[0];
      if (next) html += '<li class="note"><span>Від ' + next.nights + " " + nightsWord(next.nights) + " — " + money(next.price) + " / доба</span></li>";
    }
    q.extras.forEach(function (e) { html += "<li><span>" + e.name + " (вечір)</span><span>" + money(e.price) + "</span></li>"; });
    $(".summary-lines", summary).innerHTML = html;
    $(".summary-total strong", summary).textContent = q.onRequest ? "Уточніть ціну у власника" : money(q.total);
    $(".summary-prepay b", summary).textContent = q.onRequest ? "після узгодження ціни" : money(q.prepayment);
    summary.classList.toggle("is-request", q.onRequest);
    setHint(human(state.checkIn) + " → " + human(state.checkOut) + " · " + q.nights + " " + nightsWord(q.nights) +
      (q.onRequest ? " · святкові дати — ціну уточнить власник" : ""));
  }

  // Ручне введення дат у поля форми.
  function fromInputs() {
    clearError();
    var a = inIn.value, b = inOut.value;
    state.checkIn = null; state.checkOut = null;
    if (isValidIso(a) && canCheckIn(a)) {
      state.checkIn = a;
      var lim = limitFor(a);
      if (isValidIso(b) && b >= V.addDays(a, minNights()) && b <= lim) state.checkOut = b;
      else if (isValidIso(b) && b > a && b < V.addDays(a, minNights())) showError("Мінімальне бронювання — " + minNights() + " " + nightsWord(minNights()) + ".");
      else if (isValidIso(b) && b > a) showError("У вибраному періоді будинок уже зайнятий. Оберіть іншу дату виїзду.");
      jumpTo(a);
    } else if (isValidIso(a)) {
      showError(isBusy(a) ? "На цю дату «" + obj().name + "» зайнятий." : "Ця дата недоступна для заїзду.");
    }
    sync();
  }
  inIn.addEventListener("change", fromInputs);
  inOut.addEventListener("change", fromInputs);

  // Зміна об'єкта: свій календар, свої ціни, своя кількість гостей.
  function onObjectChange() {
    fillGuests();
    if (state.checkIn) {
      var ok = canCheckIn(state.checkIn) && (!state.checkOut || state.checkOut <= limitFor(state.checkIn));
      if (!ok) {
        state.checkIn = state.checkOut = null;
        showError("«" + obj().name + "» на обрані дати зайнятий — оберіть інші дати в календарі.");
      }
    }
    sync();
  }
  $$('input[name="objectId"]', form).forEach(function (r) { r.addEventListener("change", onObjectChange); });
  guestsEl.addEventListener("change", updateSummary);
  $$('input[name="extras"]', form).forEach(function (c) { c.addEventListener("change", updateSummary); });

  // Кнопки «Забронювати» на картках об'єктів обирають потрібний об'єкт у формі.
  $$("[data-book]").forEach(function (a) {
    a.addEventListener("click", function () {
      var r = $('input[name="objectId"][value="' + a.dataset.book + '"]', form);
      if (r && !r.checked) { r.checked = true; if (data) onObjectChange(); }
    });
  });

  function jumpTo(iso) {
    var d = V.toDate(iso), idx = d.getUTCFullYear() * 12 + d.getUTCMonth(), cur = view.y * 12 + view.m;
    if (idx < cur || idx >= cur + monthsVisible()) view = { y: d.getUTCFullYear(), m: d.getUTCMonth() };
  }

  function showError(msg) { formError.textContent = msg; formError.hidden = false; }
  function clearError() { formError.hidden = true; }

  monthsBox.addEventListener("click", function (e) {
    var btn = e.target.closest(".cal-day");
    if (btn && !btn.disabled && btn.dataset.iso) pick(btn.dataset.iso);
  });
  monthsBox.addEventListener("mouseover", function (e) {
    var btn = e.target.closest(".cal-day");
    $$(".cal-day.preview", monthsBox).forEach(function (c) { c.classList.remove("preview"); });
    if (!btn || btn.disabled || !state.checkIn || state.checkOut) return;
    var to = btn.dataset.iso;
    if (to <= state.checkIn) return;
    $$(".cal-day[data-iso]", monthsBox).forEach(function (c) {
      if (c.dataset.iso > state.checkIn && c.dataset.iso < to) c.classList.add("preview");
    });
  });
  $$(".cal-nav", calEl).forEach(function (b) {
    b.addEventListener("click", function () {
      var d = new Date(Date.UTC(view.y, view.m + Number(b.dataset.dir), 1));
      view = { y: d.getUTCFullYear(), m: d.getUTCMonth() };
      render();
    });
  });
  window.addEventListener("resize", function () { if (data) render(); });

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    clearError();
    var q = currentQuote(), msg = null;
    if (!state.checkIn || !state.checkOut) msg = "Оберіть дати заїзду та виїзду в календарі.";
    else if (q.nights < minNights()) msg = "Мінімальне бронювання — " + minNights() + " " + nightsWord(minNights()) + ".";
    else if (form.name.value.trim().length < 2) msg = "Вкажіть ваше ім'я.";
    else if (form.phone.value.replace(/\D/g, "").length < 9) msg = "Вкажіть коректний номер телефону.";
    else if (!rulesEl.checked) msg = "Підтвердьте, що ознайомилися з умовами бронювання.";
    if (msg) { showError(msg); formError.scrollIntoView({ behavior: "smooth", block: "center" }); return; }

    var submit = $('button[type="submit"]', form), label = submit.textContent, keep = objectId();
    submit.disabled = true; submit.textContent = "Надсилаємо…";
    window.FHApi.book({
      objectId: objectId(), checkIn: state.checkIn, checkOut: state.checkOut, guests: +guestsEl.value, extras: extrasChecked(),
      rules: rulesEl.checked, name: form.name.value.trim(), phone: form.phone.value.trim(),
      comment: form.comment.value.trim(), website: form.website.value
    }).then(function (res) {
      showSuccess(res.booking);
      form.reset();
      $('input[name="objectId"][value="' + keep + '"]', form).checked = true;
      fillGuests();
      state.checkIn = state.checkOut = null;
      return reload();
    }).catch(function (ex) {
      showError(ex.message);
      reload();
    }).then(function () { submit.disabled = false; submit.textContent = label; });
  });

  function showSuccess(b) {
    $("#success-code").textContent = "Код бронювання: " + b.id;
    $("#success-body").innerHTML = '<dl class="success-dl">' +
      '<div class="full"><dt>Будинок</dt><dd>' + b.objectName + "</dd></div>" +
      "<div><dt>Дати</dt><dd>" + human(b.checkIn) + " → " + human(b.checkOut) + "</dd></div>" +
      "<div><dt>Гостей</dt><dd>" + b.guests + "</dd></div>" +
      (b.extras.length ? "<div><dt>Додатково</dt><dd>" + b.extras.join(", ") + "</dd></div>" : "") +
      (b.onRequest
        ? '<div class="full accent"><dt>Вартість</dt><dd>Уточніть ціну у власника — ми зателефонуємо й назвемо суму.</dd></div></dl>'
        : "<div><dt>Разом</dt><dd>" + money(b.total) + "</dd></div>" +
          '<div class="accent"><dt>Передоплата ' + P.CONFIG.prepaymentPercent + "%</dt><dd>" + money(b.prepayment) + "</dd></div></dl>");
    modal.hidden = false;
    $(".btn", modal).focus();
  }

  function reload() {
    return window.FHApi.availability().then(function (json) {
      data = json;
      P = V.make(json.config, json.objects, json.periods, json.extras);
      busy = {};
      Object.keys(json.busy).forEach(function (id) {
        busy[+id] = {};
        json.busy[id].forEach(function (d) { busy[+id][d] = true; });
      });
      if (!view) {
        var t = V.toDate(data.today);
        view = { y: t.getUTCFullYear(), m: t.getUTCMonth() };
        var daysLeft = new Date(Date.UTC(view.y, view.m + 1, 0)).getUTCDate() - t.getUTCDate();
        if (monthsVisible() === 1 && daysLeft < 7) view = { y: view.y + (view.m === 11 ? 1 : 0), m: (view.m + 1) % 12 };
      }
      fillGuests();
      sync();
    }).catch(function () {
      monthsBox.innerHTML = '<div class="cal-loading">Не вдалося завантажити календар. Оновіть сторінку.</div>';
    });
  }
  reload();
})();
