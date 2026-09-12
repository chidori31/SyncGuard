# SyncGuard

**Контроль бизнес-результата интеграций.** HTTP 200 ещё не означает, что закрытая сделка стала заказом в учётной системе.

Рабочий локальный MVP **v0.3**: контроль связи **Bitrix24 ↔ 1С**, HTTP-коннекторы REST/OData, детерминированный Python rule engine, PostgreSQL, FastAPI и React dashboard. В поставку входят HTTP-симуляторы API с синтетическими данными. Groq/Qwen используется отдельным инструментом разработки.

## Запуск

Нужен Docker Desktop с Linux containers и Docker Compose v2. Из этой папки:

```sh
docker compose up --build
```

Или в фоне:

```sh
docker compose up -d --build --wait
```

- Dashboard: http://localhost:3000
- Backend Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health
- PostgreSQL: `127.0.0.1:55432`, database/user `syncguard`.
- HTTP-симуляторы: http://localhost:8100/docs

Откройте dashboard, выберите сценарий и нажмите **«Запустить демо-проверку»**. По умолчанию интерфейс проверяет HTTP-симуляторы. Для запуска через API:

```sh
curl -X POST http://localhost:8000/api/demo/run -H 'Content-Type: application/json' -d '{"scenario":"baseline","transport":"http"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/demo/run -ContentType 'application/json' -Body '{"scenario":"baseline","transport":"http"}'
```

Каждый запуск проверяет три сделки и сохраняет наблюдения. Начальное время WON фиксируется при первом запуске. Повторная проверка добавляет evidence, но не создаёт дубли инцидентов.

| Сделка | Bitrix24 | 1С | Результат | Под риском |
|---|---|---|---|---:|
| #5821 | WON, 184 000 ₽ | Заказ отсутствует | CRITICAL / missing_target | 184 000 ₽ |
| #5822 | WON, 50 000 ₽ | Заказ 50 000 ₽, через 2 минуты | healthy_match | 0 ₽ |
| #5823 | WON, 100 000 ₽ | Заказ 90 000 ₽ | WARNING / wrong_amount | 10 000 ₽ |

Интеграция получает **BROKEN**, активных инцидентов **2**, суммарный риск **194 000 ₽**. Страница #5821 показывает отдельный риск **184 000 ₽**, пустой результат поиска заказа, срок правила и исходную сделку. «Взять в работу» переводит инцидент в ACKNOWLEDGED и сохраняет риск. Сценарий «Восстановление» закрывает инциденты после успешного сопоставления; вручную закрыть инцидент нельзя.

| Сценарий | Статус при самостоятельной проверке | Смысл |
|---|---|---|
| baseline | BROKEN | Отсутствующий заказ и разница суммы |
| healthy | HEALTHY | Восстановление всех трёх сделок |
| duplicate | BROKEN | Два разных заказа с одной ссылкой на сделку |
| wrong_amount | DELAYED | WARNING: разница 10 000 ₽ |
| delay | DELAYED | Заказ создан через 6 минут; текущий риск 0 |
| pending | DELAYED | С момента WON прошло 2 минуты; новый инцидент не создаётся |
| outage | UNKNOWN | 1С отвечает 503; прежние инциденты и риск сохраняются |

Повтор baseline после healthy открывает прежние записи инцидентов. Pending сохраняет уже открытый инцидент, поэтому итоговый статус может оставаться BROKEN. Панель стенда показывает результат по каждой сделке, число прочитанных страниц, HTTP-запросов, повторов и последние 10 запусков.

## Архитектура

```text
React / TypeScript / Vite
          ↓ same-origin /api через nginx
FastAPI → сервис транзакций → PostgreSQL
              ↓
HTTP / Memory connectors → NormalizedEntity → pure Rule Engine
                                      ↓
                      CheckRun + Observation + Incident + Evidence

tools/ai_helper.py → Groq (только development)
```

- Модульный монолит: API, orchestration, connectors и бизнес-правила разделены.
- Деньги — Decimal / NUMERIC(18,2); API отдаёт денежные значения строками.
- Даты — timezone-aware; дедлайн считается от изменения статуса WON.
- До дедлайна отсутствие заказа — pending, после — missing_target.
- Проверяются duplicate_target, wrong_amount (включая валюту), synchronization_delay, healthy_match.
- Ошибка коннектора или некорректное время — UNKNOWN, без ложного инцидента об отсутствии и без закрытия прежних проблем.
- Транзакционная advisory lock сериализует demo runs. Уникальный fingerprint защищает от дублирования на уровне БД.
- Повторное нарушение открывает существующий инцидент с новой записью timeline. Evidence прошлых проверок сохраняется.
- Есть 11 таблиц: Organization, User, Connector, Integration, BusinessRule, ExternalEntity, Observation, Incident, IncidentEvidence, Alert и CheckRun. User — заготовка домена, а не реализованная авторизация; Alert — локальная запись без отправки уведомлений.

Подробнее: [ARCHITECTURE.md](ARCHITECTURE.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [VERIFICATION.md](VERIFICATION.md).

## API

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | Готовность PostgreSQL; 503 при недоступности |
| GET | `/api/dashboard` | Сводные показатели |
| GET | `/api/integrations` | Интеграции |
| GET | `/api/integrations/{id}` | Одна интеграция |
| GET | `/api/incidents` | Фильтр status, limit 1–200, offset |
| GET | `/api/incidents/{id}` | Инцидент, правило, последние 50 evidence и timeline |
| PATCH | `/api/incidents/{id}` | `{"status":"ACKNOWLEDGED"}` |
| GET | `/api/rules` | Действующие demo rules |
| POST | `/api/demo/run` | Создание демо и повторная проверка |
| GET | `/api/demo/scenarios` | Каталог сценариев |
| GET | `/api/integrations/{id}/checks` | История запусков и наблюдения; limit 1–50 |

POST принимает `scenario` и `transport` (`http`/`memory`). Запрос без тела сохраняет совместимость с v0.1 и использует baseline в памяти. URL внешних систем и credentials через demo API не принимаются.

## Тесты

Python 3.12+ и доступная PostgreSQL из Compose:

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
docker compose up -d postgres
```

PowerShell:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://syncguard:syncguard_local_demo@127.0.0.1:55432/syncguard?connect_timeout=5'
python -m pytest -q
python -m ruff check .
```

Linux/macOS:

```sh
TEST_DATABASE_URL='postgresql+psycopg://syncguard:syncguard_local_demo@127.0.0.1:55432/syncguard?connect_timeout=5' python -m pytest -q
```

Без TEST_DATABASE_URL database tests будут **пропущены**. Полная проверка требует этой переменной. Тесты создают и удаляют только собственные случайные схемы `test_syncguard_*` и `test_migration_*`; demo-таблицы не очищаются. Миграции проверяются upgrade → проверка соответствия моделям → downgrade → повторный upgrade.

Сквозная проверка запущенного Compose через настоящие HTTP-соединения:

```sh
python tools/verify_stack.py
```

Она выполняет 11 запусков сценариев, изменяет состояние только локального demo и возвращает его к baseline. В GitHub Actions подготовлены проверки pytest/PostgreSQL/frontend и Compose HTTP acceptance; после их успеха собирается исходный ZIP с контрольной суммой. Фактические результаты локального прогона — в [VERIFICATION.md](VERIFICATION.md).

Покрываются нормализация, все outcomes, точные границы времени, Decimal, валюты, дедупликация, параллельный первый запуск, rollback, recovery/reopen, UNKNOWN, REST, tenant foreign keys и ограничения БД, sanitizer и ошибки Groq.

Frontend (Node 22.18+):

```sh
cd frontend
npm ci
npm test
npm run build
```

## Локальная разработка

```sh
docker compose up -d postgres
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
# В другом терминале:
python -m uvicorn app.simulator:app --app-dir backend --host 127.0.0.1 --port 8100
# Ещё в одном терминале:
cd frontend
npm ci
npm run dev
```

Vite проксирует `/api` на порт 8000. Не запускайте локальный backend одновременно с Docker backend на одном порту. Схемой управляет Alembic; приложение не вызывает create_all при старте.

`backend/constraints.txt` фиксирует проверенные версии Python-пакетов и применяется при установке runtime/dev requirements. Зависимости, специфичные для другой ОС, могут разрешаться отдельно. Frontend использует package-lock.json.

## Настройки и делегирование Qwen

`.env.example` содержит параметры локального демо. При необходимости скопируйте его в `.env`; `.env` исключён из Git. Compose использует отдельные POSTGRES_* переменные, локальный backend — DATABASE_URL. Если меняете пароль существующего PostgreSQL volume, изменение переменной само по себе не меняет пароль уже созданной роли.

Ключ Groq **не нужен для запуска SyncGuard** и не передаётся в контейнер backend. Введите ключ только в environment текущего терминала. Например, PowerShell 7:

```powershell
$env:GROQ_API_KEY = Read-Host 'Groq API key' -MaskInput
python tools/ai_helper.py implement "Write a standalone SHA-256 utility with tests" --max-tokens 16384
python tools/ai_helper.py architect "Review a synthetic deterministic integration architecture"
python tools/ai_helper.py review "Review this synthetic design decision"
python tools/ai_helper.py debug "Analyze this synthetic failure"
python tools/ai_helper.py tests "Suggest deadline boundary tests"
python tools/ai_helper.py security "Review localhost demo security assumptions"
```

Модель: `qwen/qwen3.8-27b`; можно переопределить `GROQ_MODEL`. Режимы architect/debug/security используют high, review/tests — medium, implement — low. Можно задать `--effort medium --max-tokens 16384`: при проверке крупных файлов high расходовал весь лимит на reasoning без текста ответа. По умолчанию бюджет 12 288 токенов, timeout 120 секунд на запрос, до двух повторов SDK. Код выхода 2 — конфигурация/ввод, 1 — ошибка провайдера, пустой или усечённый ответ, 0 — ответ. Ошибки не выводят тело ответа или credentials.

CLI принимает только явно переданный текст (либо stdin через `-`), не собирает файлы и не читает `.env`. Санитайзер скрывает распознаваемые ключи, токены, пароли, JWT, Authorization, credential URLs и private keys, но не может распознать произвольную конфиденциальную бизнес-информацию. Используйте только синтетический контекст; не передавайте реальные клиентские данные, дампы и закрытые логи.

Правила независимого review — в AGENTS.md, реальные ответы и решения — в [docs/reviews/DECISIONS.md](docs/reviews/DECISIONS.md). В v0.3 Qwen также написал три модуля сборки релиза и тесты; принятые части и исправленные ошибки перечислены в [docs/delegation/README.md](docs/delegation/README.md).

## Границы MVP

Это локальное демонстрационное приложение с одним seed tenant: без авторизации и планировщика. HTTP-адаптеры реализованы, но проверены на контрактных симуляторах; доступа к реальным установкам 1С и Bitrix24 не предоставлено. Для конкретной 1С требуется согласовать публикацию OData, поля, реальные даты создания, часовой пояс и идентификаторы связей. Подробности — [docs/INTEGRATION_CONTRACTS.md](docs/INTEGRATION_CONTRACTS.md).

Проверки запускаются кнопкой/API и не создают заказы во внешних системах. API отдаёт риск отдельно по валютам (`risk_by_currency`), карточки демо показывают RUB; конвертации валют нет. Список UI показывает последние 100 инцидентов. Историческое опоздание остаётся нарушением SLA даже после появления заказа, риск такого инцидента равен нулю. Retention наблюдений и timeline пока не добавлен. Отсутствие сделки в новом снимке не доказывает восстановление: прежний инцидент сохраняется до однозначного результата.

Compose привязывает порты к loopback. Для SaaS/общедоступного сервера отдельно потребуются authentication, tenant access control, TLS, rate limits, хранение секретов и правила retention. Не публикуйте этот demo как готовый production SaaS.

Остановка без удаления данных:

```sh
docker compose down
```

Данные остаются в volume `syncguard_postgres_data`.

## GitHub

Проект подготовлен как самостоятельный Git-репозиторий с веткой `main`, CI, .gitignore, шаблоном PR и документацией. Перед отправкой проверьте `git status`, `git diff --cached` и `python tools/check_secrets.py`. `.env`, зависимости, кэши и ключ Groq в репозиторий не входят.

Для будущего push в выбранный вами пустой репозиторий:

```sh
git remote add origin <URL-вашего-репозитория>
git push -u origin main
```

Рабочая папка проекта уже содержит Git-историю. ZIP содержит только исходники: после его распаковки сначала выполните `git init -b main`, `git add .` и `git commit -m "Initial SyncGuard project"`. Отдельный файл SyncGuard.git.bundle сохраняет готовую историю; восстановить её можно командой `git clone -b main SyncGuard.git.bundle SyncGuard`.

GitHub Actions начнёт выполняться после push; успешный удалённый CI до публикации не заявляется.


### Сборка исходного релиза

Нужны Git и Python 3.12+, пакеты приложения не требуются. Сначала сохраните изменения коммитом, затем из корня проекта:

```sh
python tools/check_secrets.py --ref HEAD
python tools/build_release.py --output ../SyncGuard-source.zip
```

Сборщик берёт только содержимое выбранного коммита (`--ref`, по умолчанию HEAD). Незакоммиченные изменения и untracked-файлы не попадают в ZIP. Выходной путь должен быть вне репозитория, его каталог должен существовать; существующие ZIP и `.sha256` не перезаписываются. Архив содержит папку SyncGuard и RELEASE-MANIFEST.json с commit SHA и SHA-256 каждого исходного файла. Рядом записывается SHA-256 самого ZIP. Повторная сборка одного коммита тем же Python/zlib даёт одинаковые байты.

Сканер по умолчанию проверяет Git index, а с `--ref` — дерево коммита. Он проверяет распознаваемые Groq/GitHub/PEM-паттерны и запрещает environment-файлы (кроме `.env.example`), ссылки и неразрешённые конфликты. Это ограниченный контроль выбранного снимка, не аудит всей Git-истории и не универсальное обнаружение секретов. В архиве запрещены небезопасные и конфликтующие пути; лимит файла 10 MiB, всех файлов 50 MiB.

GitHub Actions после обеих успешных проверок сохраняет ZIP и checksum как artifact на 14 дней. Это артефакт CI; публичный GitHub Release автоматически не создаётся.
