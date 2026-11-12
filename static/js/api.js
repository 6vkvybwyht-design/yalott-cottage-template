/*
 * Клієнт API сайту (Flask).
 * Публічні запити: зайнятість і ціни об'єктів, бронювання.
 * Адмінка: працює через сесію входу (/admin/login) і CSRF-токен.
 */
(function () {
  'use strict';
  var meta = document.querySelector('meta[name="csrf-token"]');
  var CSRF = meta ? meta.getAttribute('content') : '';

  function request(method, url, body) {
    var headers = { 'X-CSRF-Token': CSRF };
    if (body) headers['Content-Type'] = 'application/json';
    return fetch(url, {
      method: method, headers: headers, credentials: 'same-origin', cache: 'no-store',
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (res.status === 401 && data.login) { location.href = '/admin/login'; }
        if (!res.ok) throw new Error(data.error || 'Помилка ' + res.status);
        return data;
      });
    }, function () { throw new Error("Немає зв'язку із сервером. Перевірте інтернет."); });
  }

  window.FHApi = {
    availability: function () { return request('GET', '/api/availability'); },
    book: function (body) { return request('POST', '/api/bookings', body); },
    admin: {
      data: function () { return request('GET', '/admin/api/data'); },
      setStatus: function (id, status) { return request('POST', '/admin/api/status', { id: id, status: status }); },
      blockNights: function (dates, objects, blocked, count) {
        var body = { dates: dates, objects: objects, blocked: blocked };
        if (count != null) body.count = count;
        return request('POST', '/admin/api/block-nights', body);
      },
      saveObjectPrices: function (p) { return request('POST', '/admin/api/object-prices', p); },
      saveExtraPrice: function (key, price, guestPrices) {
        var body = { key: key, price: price };
        if (guestPrices) body.guestPrices = guestPrices;
        return request('POST', '/admin/api/extra-price', body);
      },
      savePeriod: function (p) { return request('POST', '/admin/api/period', p); },
      deletePeriod: function (id) { return request('POST', '/admin/api/period-delete', { id: id }); },
      telegramTest: function () { return request('POST', '/admin/api/telegram-test'); }
    }
  };
})();
