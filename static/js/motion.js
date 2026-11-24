/* Рух дизайн-системи (лише теми design.PALETTES, <html data-ds>): поява блоків при прокрутці й легкий паралакс
   фото банера. Стримано й дешево: лише opacity/transform, IntersectionObserver, один requestAnimationFrame.
   • «Зменшити рух» у системі — нічого не вмикається (і CSS теж вимикає анімації).
   • Телефон / сенсорний екран — без паралаксу, коротша поява (design.css).
   • Блоки, видимі одразу при завантаженні, не ховаються — без «мигання»; без JS усе просто видно.
   Без вбудованих скриптів і зовнішніх бібліотек — працює під суворим CSP (style.setProperty — це CSSOM). */
(function () {
  "use strict";
  var root = document.documentElement;
  if (!root.hasAttribute("data-ds") || !("IntersectionObserver" in window)) return;
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
  if (reduce.matches) return;

  // Групи блоків, що з'являються; у межах однієї групи — по черзі (--i).
  var GROUPS = [
    ".section-head", ".perks > .perk", ".objects > .obj-card", ".services > .service", ".price-cards > .price-card",
    ".reviews > .review", ".faq > .faq-item", ".gallery > .gallery-item", ".territory > li", ".nearby > .near",
    ".rules > .rule", ".contact-list > *", ".map-col", ".desc-grid > *", ".booking-grid > *", ".obj-pick", ".faq-grid > .section-head"
  ];
  var vh = window.innerHeight;
  var targets = [];
  GROUPS.forEach(function (sel) {
    var seen = new Map();
    document.querySelectorAll(sel).forEach(function (el) {
      if (el.hasAttribute("data-reveal") || el.closest(".hero")) return;
      var r = el.getBoundingClientRect();
      if (r.top < vh * 0.92 && r.bottom > 0) return;            // уже на екрані — не ховаємо
      var parent = el.parentElement, i = seen.get(parent) || 0;
      seen.set(parent, i + 1);
      el.setAttribute("data-reveal", "");
      el.style.setProperty("--i", String(Math.min(i, 5)));
      targets.push(el);
    });
  });
  root.classList.add("ds-motion");

  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      var el = e.target;
      io.unobserve(el);
      el.classList.add("is-in");
      // після появи прибираємо затримку, щоб наведення працювало без запізнення
      setTimeout(function () { el.removeAttribute("data-reveal"); el.style.removeProperty("--i"); }, 1500);
    });
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  targets.forEach(function (el) { io.observe(el); });

  // Паралакс фото банера — лише великий екран із мишею
  var hero = document.querySelector(".hero--ds");
  var fine = window.matchMedia("(min-width: 761px) and (hover: hover) and (pointer: fine)");
  if (hero && fine.matches) {
    var ticking = false;
    var update = function () {
      ticking = false;
      var y = window.scrollY, h = hero.offsetHeight;
      if (y > h) return;
      hero.style.setProperty("--parallax", (y * 0.22).toFixed(1) + "px");
    };
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
    }, { passive: true });
  }
})();
