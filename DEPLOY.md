# Деплой

Основний варіант — наш VPS через **yalott-server** (`new-site`, `set-domain`, `secure-site`).
Запасний — PythonAnywhere.

У коді немає захардкоджених шляхів: усе, що залежить від сервера, задається змінними оточення
(файл `.env` у папці проєкту). Повний список — у `.env.example`.

Перед деплоєм на своєму комп'ютері:

```bash
python manage.py check
```

і закомітьте `config/site.yaml` та `static/media/`. Файл `.env` у git не потрапляє — на сервері його
створюєте окремо.

**Безпека вмикається сама** для кожного сайту, ручних кроків у коді немає (докладно — розділ
«Безпека» нижче): ліміт підбору пароля адмінки, справжні IP за Caddy, CSRF, сесія 12 год, Content-Security-Policy,
права на базу. Від вас — лише `secure-site` і `security-check` на сервері.

---

## VPS через yalott-server

Усі команди виконуються **на сервері** через SSH, від користувача з `sudo`. Нижче `НАЗВА` — коротка
назва сайту латиницею (як у `sudo status`), `ДОМЕН` — домен клієнта.
Сайт лежить у `/home/yalott/sites/НАЗВА`, працює від користувача `yalott`.

### 1. Новий сайт

Спершу на GitHub: **Use this template** → репозиторій клієнта (напр. `6vkvybwyht-design/ramshill-site`).

```bash
sudo new-site НАЗВА 6vkvybwyht-design/РЕПОЗИТОРІЙ
```

Скрипт сам:

- клонує код, ставить залежності, запускає gunicorn за Caddy на `127.0.0.1`;
- створює `.env` з `.env.example`, **генерує `SECRET_KEY`** і ставить `SESSION_COOKIE_SECURE=1`;
- ставить права `.env` — 600, а сервіс — `UMask=0077`, тож база й тека `instance` створюються з правами 600/700;
- відкриває сайт за тестовою адресою `https://НАЗВА.<IP-з-дефісами>.sslip.io`.

Коли скрипт відкриє `.env` у редакторі, заповніть:

| Змінна | Значення |
|---|---|
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | логін і пароль адмінки (пароль від 8 символів) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | бот сайту від @BotFather і chat id власника (не бот сервера!) |
| `DEMO_DATA` | `1` — поки показуєте клієнту, `0` — для робочого сайту |
| `BEHIND_PROXY` | `1` (вже стоїть) |

Не заповнили `ADMIN_PASSWORD`? На робочому сайті буде створено випадковий пароль — він є в журналі:
`sudo site-logs НАЗВА`. Відомого всім пароля `demo2026` на робочому сайті немає.

### 2. Перевірка сайту на сервері

```bash
sudo -u yalott bash -c 'cd /home/yalott/sites/НАЗВА && .venv/bin/python manage.py check'
```

### 3. Домен

Коли A-запис домену вказує на IP сервера:

```bash
sudo set-domain НАЗВА ДОМЕН
```

### 4. Захист сайту (обов'язково)

Домени клієнтів зазвичай **не** за Cloudflare, тому з `--no-cloudflare`. Спершу подивіться, що зміниться:

```bash
sudo secure-site НАЗВА --no-cloudflare --dry-run
```

```bash
sudo secure-site НАЗВА --no-cloudflare
```

`secure-site` додає HSTS, прибирає заголовок `Server` і підключає файл заголовків
`security/НАЗВА.caddy` або базовий `default.caddy`. Content-Security-Policy сайт віддає **сам**
(`security.py`), тому окремий файл заголовків для шаблону не потрібен.

Потім — звіт про захист сервера (нічого не змінює):

```bash
sudo security-check
```

У звіті для цього сайту мають бути ✔: `.env` (600), база `instance/*.db` (600), тека `instance` (700).
Якщо ні — виправте командою з підказки або:

```bash
sudo chmod 700 /home/yalott/sites/НАЗВА/instance && sudo chmod 600 /home/yalott/sites/НАЗВА/instance/*.db /home/yalott/sites/НАЗВА/.env
```

### 5. Чекліст після запуску

Заголовки безпеки (має бути `content-security-policy` з `script-src 'self'`, `strict-transport-security`,
`x-frame-options`, `x-content-type-options`):

```bash
curl -sI https://ДОМЕН/ | grep -iE 'content-security-policy|strict-transport|x-frame-options|x-content-type'
```

Адмінка не індексується:

```bash
curl -sI https://ДОМЕН/admin/login | grep -i x-robots-tag
```

У браузері:

1. Головна й сторінка кожного котеджу відкриваються, календар і карта працюють
   (в інструментах розробника, вкладка Console, немає повідомлень «Refused to … Content Security Policy»).
2. Вхід в адмінку працює; на сторінці входу **немає** підказки «Демо-доступ».
3. Адмінка → **«Надіслати тестове сповіщення»** — повідомлення прийшло в Telegram власника.
4. Тестова заявка з сайту → сповіщення прийшло; скасуйте її в адмінці.
5. Захист від підбору пароля: 5 разів неправильний пароль → «Забагато невдалих спроб».
   З вашої IP вхід відкриється через 15 хв (або увійдіть з іншої мережі, напр. з телефона через мобільний інтернет).
6. Перед запуском для гостей: `DEMO_DATA=0` у `.env`, прибрати демо-дані й перезапустити:

```bash
sudo -u yalott bash -c 'cd /home/yalott/sites/НАЗВА && .venv/bin/python manage.py seed --clear-demo'
```

```bash
sudo deploy НАЗВА
```

### Демо-версія для показу клієнту

Демо — той самий сайт, але з `demo.enabled: true` у конфігу (див. README, розділ «Демо-версія для продажу»).
Домен демо (`demo.domain`) — тестова адреса сайту, яку показав `new-site`: `НАЗВА.<IP-з-дефісами>.sslip.io`.

```bash
sudo -u yalott bash -c 'cd /home/yalott/sites/НАЗВА && .venv/bin/python manage.py demo-link'
```

Перевірка після запуску демо:

```bash
curl -sI https://НАЗВА.<IP-з-дефісами>.sslip.io/ | grep -iE '^HTTP|x-robots-tag'
```

Має бути `403` і `x-robots-tag: noindex, nofollow, noarchive, nosnippet, noimageindex`: без посилання сайт закритий.
Відкрийте посилання з `demo-link` — має відкритися сайт із плашкою «Демо · Yalott Studio» і водяними знаками на фото.

Клієнт оплатив: `demo.enabled: false` у конфігу, закомітьте, `sudo deploy НАЗВА`, потім `sudo set-domain` і
`sudo secure-site` — далі як для звичайного сайту.

### Оновлення сайту

```bash
sudo deploy НАЗВА
```

`deploy` робить бекап бази, `git pull`, ставить залежності й перезапускає сайт. Після зміни `.env` —
теж `sudo deploy НАЗВА`. Ціни, змінені власником в адмінці, оновлення не чіпає.

### Зміна пароля адмінки

```bash
sudo -u yalott bash -c 'cd /home/yalott/sites/НАЗВА && .venv/bin/python manage.py set-password admin'
```

Після зміни пароля всі старі входи в адмінку (на всіх пристроях) стають недійсними.

---

## PythonAnywhere (запасний варіант)

Нижче `USER` — ваш логін на PythonAnywhere, `REPO` — адреса репозиторію клієнта.
Проєкт кладемо в папку `~/site`.

### 1. Код

Вкладка **Consoles → Bash**:

```bash
git clone REPO ~/site
```

Для приватного репозиторію використайте адресу з токеном доступу або deploy-ключ.

```bash
cd ~/site
```

```bash
python3.12 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

### 2. Секрети

```bash
cp .env.example .env
```

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Відкрийте `.env` (вкладка **Files** або `nano .env`) і заповніть:

| Змінна | Значення |
|---|---|
| `SECRET_KEY` | рядок з команди вище. **Обов'язково** — без нього сайт не запуститься |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | логін і пароль адмінки (пароль від 8 символів) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | бот від @BotFather і chat id власника |
| `DEMO_DATA` | `1` — поки показуєте клієнту, `0` — для робочого сайту |
| `SESSION_COOKIE_SECURE` | порожньо або `1` (cookie входу лише через HTTPS) |
| `BEHIND_PROXY` | `1` — PythonAnywhere працює через свій вебсервер; без цього ліміти рахуватимуть його IP |

### 3. База й перевірка

```bash
.venv/bin/python manage.py seed
```

База містить персональні дані гостей, тому сайт сам ставить права: тека `instance` — 700, файл бази — 600
(під час кожного запуску). Перевірити або виправити вручну:

```bash
chmod 700 ~/site/instance && chmod 600 ~/site/instance/*.db ~/site/.env
```

```bash
.venv/bin/python manage.py check
```

### 4. Вебзастосунок

Вкладка **Web → Add a new web app → Manual configuration → Python 3.12**. Далі на тій самій вкладці:

- **Source code:** `/home/USER/site`
- **Working directory:** `/home/USER/site`
- **Virtualenv:** `/home/USER/site/.venv`
- **Static files:** URL `/static/` → Directory `/home/USER/site/static`
- **Force HTTPS:** увімкнути

WSGI-файл — скопіюйте готовий (у Bash-консолі):

```bash
cp ~/site/pythonanywhere_wsgi.py /var/www/$(whoami)_pythonanywhere_com_wsgi.py
```

Якщо проєкт лежить не в `~/site`, змініть у скопійованому файлі один рядок `PROJECT_DIR`.

Натисніть **Reload**. Сайт: `https://USER.pythonanywhere.com`, адмінка: `/admin`.

### 5. Перевірка після запуску

1. Відкрийте головну й сторінку кожного об'єкта.
2. Увійдіть в адмінку, натисніть **«Надіслати тестове сповіщення»** — у Telegram має прийти повідомлення.
3. Зробіть тестову заявку з сайту — сповіщення прийде власнику; скасуйте її в адмінці.
4. Перед запуском для гостей: `DEMO_DATA=0` у `.env` і

```bash
.venv/bin/python manage.py seed --clear-demo
```

### Оновлення сайту

```bash
cd ~/site && git pull
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python manage.py seed
```

Потім **Web → Reload**. `seed` тут лише доливає нове з конфігу (новий об'єкт чи сезон) —
ціни, змінені власником в адмінці, не чіпає.

### Резервна копія

Усі бронювання — в одному файлі `~/site/instance/site.db`. Завантажте його через вкладку **Files**
або скопіюйте:

```bash
cp ~/site/instance/site.db ~/backup-$(date +%F).db
```

### Власний домен

Платний тариф PythonAnywhere: **Web → Add a new web app** з вашим доменом, далі ті самі налаштування,
а в DNS — CNAME-запис, який покаже PythonAnywhere. WSGI-файл матиме іншу назву
(`/var/www/www_example_com_wsgi.py`) — скопіюйте `pythonanywhere_wsgi.py` у нього.

### Особливості безкоштовного тарифу

- Вихідні з'єднання дозволені лише до «білого списку» сайтів; `api.telegram.org` у ньому є.
- Фонові потоки у вебзастосунках не працюють, тому сповіщення надсилається одразу в запиті
  (сайт сам це визначає за змінною `PYTHONANYWHERE_DOMAIN`).
- Раз на кілька місяців треба натиснути **Run until 3 months from today** на вкладці Web.

---

---

## Безпека: що вмикається само

Нічого не потрібно налаштовувати — це працює на кожному сайті з шаблону:

| Що | Як |
|---|---|
| Підбір пароля адмінки | 5 невдалих спроб з однієї IP або 10 на один логін за 15 хв → пауза 15 хв. Лічильник у базі (спільний для всіх воркерів gunicorn), без `sleep`, який гальмував би сайт |
| Справжні IP за Caddy | ProxyFix бере IP з останнього запису `X-Forwarded-For`, який дописав Caddy; підроблений заголовок не обходить ліміти. `BEHIND_PROXY=1` |
| CSRF | токен на всіх формах і запитах: вхід, вихід, бронювання, адмінка |
| Сесія адмінки | 12 год; зміна пароля виганяє всі старі сесії; cookie `Secure`, `HttpOnly`, `SameSite=Lax` |
| Content-Security-Policy | лише власні скрипти й стилі, без вбудованих `<script>`, `onclick=`, `<style>`; шрифти Google Fonts, рамка — лише Google Maps |
| `SECRET_KEY` | лише з `.env`; без нього (чи з прикладом на кшталт `change-me`) сайт не запускається |
| Права на базу | тека `instance` — 700, база — 600; виправляються самі під час кожного запуску |
| Заявки на бронювання | 10 за 10 хв з однієї IP; усі поля перевіряються на сервері, керівні символи прибираються; запит понад 256 КБ відхиляється |
| Посилання iCal (v2) | лише `https://` на адреси в інтернеті (не на сам сервер чи локальну мережу), з перевіркою переадресацій |

Додаєте на сайт зовнішній сервіс (аналітика, відео, віджет)? Його адресу треба дописати в
`content_security_policy()` у `security.py`, інакше браузер його заблокує.

## Якщо щось не так

| Симптом | Причина й рішення |
|---|---|
| Сайт не стартує, у журналі «Не задано SECRET_KEY» | у `.env` порожній `SECRET_KEY` — згенеруйте: `python3 -c "import secrets; print(secrets.token_hex(32))"`, впишіть і `sudo deploy НАЗВА` |
| Сайт не стартує, у журналі «Конфіг … містить помилки» | `python manage.py validate` покаже, що виправити |
| «База … створена старою версією сайту» | у `DATABASE_PATH` лежить база від старого сайту — вкажіть інший файл |
| Не можу увійти в адмінку на своєму комп'ютері (http://localhost) | поставте `SESSION_COOKIE_SECURE=0` у локальному `.env` (лише на своєму комп'ютері!) |
| «Забагато невдалих спроб» у власника | зачекайте 15 хв або увійдіть з іншої мережі; при потребі змініть пароль командою `set-password` |
| Не знаю пароль адмінки | `sudo site-logs НАЗВА` (випадковий пароль, якщо `ADMIN_PASSWORD` не задали) або `set-password` |
| У браузері не працює новий зовнішній віджет | його блокує Content-Security-Policy — допишіть адресу в `security.py` |
| Не приходять сповіщення | адмінка → «Надіслати тестове сповіщення» покаже точну помилку Telegram |
| Змінили ціну в конфігу, а на сайті стара | так і задумано: ціни після першого запуску живуть у базі. Змініть в адмінці або `seed --reset` |
| Замість фото заглушки | немає файлів у `static/media/objects/<id>/` — запустіть `python manage.py photos` і закомітьте результат |
| Після оновлення старі стилі | перезапустіть застосунок — версія стилів у посиланнях оновиться |
