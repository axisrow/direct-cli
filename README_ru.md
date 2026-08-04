# Direct CLI

[English](README.md) | [Русский](README_ru.md)

---

Интерфейс командной строки для Яндекс.Директ API.

### Установка

```bash
pip install direct-cli
```

### Мастер кампаний — только через браузер

У «Мастера кампаний» **нет никакого API** — он существует только в
веб-интерфейсе, и его нельзя путать с `UNIFIED_CAMPAIGN` (это отдельный тип
кампании в v5 API, уже поддержанный через `campaigns add/get --type
unified_campaign`). Команды `direct masters list` / `direct masters get
<id>` читают его, расшифровывая ваши существующие куки Chrome для
`yandex.ru` и передавая их в браузер, управляемый Playwright — отдельный
вход не нужен. Читаются только эти куки, остальной профиль Chrome не
затрагивается. На macOS ключ шифрования кук лежит в вашей связке ключей
(Keychain), поэтому при первом запуске macOS покажет системный запрос
доступа — нужно нажать «Разрешить». Linux поддерживается, если Chrome
использует базовое (не keyring) хранилище паролей; Windows пока не
поддерживается. Требует опциональный extra `browser`:

```bash
pip install "direct-cli[browser]"
playwright install chromium
direct masters list
direct masters list --status archived
direct masters get 72349978
direct masters suspend 72349978
direct masters resume 72349978
direct masters archive 72349978
direct masters update 72349978 --weekly-budget 95000
direct masters update 72349978 --promotion-goal max-clicks --no-directs-helps
direct masters update 72349978 --name "Мастер ИЖ Источник Жизни (тёплый)"
direct masters update 72349978 --headline "2=Новый заголовок" --text "1=Новый текст"
direct masters update 72349978 --image "2=/path/to/banner.png"
direct masters adimages get 72349978
direct masters adimages add 72349978 --image-file /path/to/a.png --image-file /path/to/b.png
direct masters adimages delete 72349978 --position 2
direct masters adimages delete 72349978 --all
direct masters adimages set 72349978 --image-file /path/to/a.png --image-file /path/to/b.png
direct masters add https://example.com/ --headline "Заголовок 1" --headline "Заголовок 2" --text "Текст объявления" --region Москва --weekly-budget 50000 --draft
direct masters add https://example.com/ --headline "Заголовок 1" --text "Текст объявления" --region-id 213 --weekly-budget 50000 --draft
direct masters copy 72349978
direct masters copy 72349978 --launch
```

`masters list` фильтрует по статусу через `--status`
(`not-archived`/`active`/`stopped`/`archived`/`all`, по умолчанию
`not-archived`). Команда всегда читает свой собственный кабинет, в котором
авторизован браузер — доступа к обслуживаемым клиентам (`--login`/агентство)
нет.

`masters update` редактирует настройки одного «Мастера кампаний». Пока
поддерживаются простые скалярные поля (Этап A поэтапного плана — см.
докстринг модуля `direct_cli/browser/masters.py`), название кампании,
точечная замена отдельных вариантов заголовков/текстов (Этап B) и точечная
замена отдельных изображений (Этап D):
`--weekly-budget` (недельный бюджет, целое число), `--promotion-goal`
(`max-conversions`/`max-clicks` — цель продвижения),
`--directs-helps`/`--no-directs-helps` (автоприменение рекомендаций «Директ
помогает»), `--name` (Название кампании), `--headline`/`--text`
(повторяемые, формат `"N=текст"`, N — номер слота варианта на странице
редактирования, 1-based: 1-5 для заголовков, 1-3 для текстов) и `--image`
(повторяемый, формат `"N=/путь/к/файлу.png"`, N — 1-based позиция в
*текущем* наборе изображений кампании). Нужно указать
хотя бы один флаг. Страница настроек — единая форма с одной кнопкой
сохранения: если указать не все флаги, остальные поля останутся с текущим
значением — это не частичный запрос к отдельному API-эндпоинту на каждое
поле. В отличие от остальных полей, `--name` редактируется через отдельную
модалку в шапке, а не обычное поле формы — но сохраняется всё той же общей
кнопкой, а не собственной кнопкой «Применить» модалки.

`--headline`/`--text` **заменяют один существующий вариант за раз**, а не
весь набор целиком — это сознательное отступление от обычной конвенции CLI
для list-полей (например, `campaigns update --negative-keywords` заменяет
весь массив одним вызовом). У Мастера кампаний нет API, наборы вариантов
могут быть большими, и заставлять перепечатывать все варианты ради
исправления одной опечатки противоречило бы смыслу частичного обновления —
полное обоснование см. в
`direct_cli/browser/masters.py::_set_repeating_value`. Запись в пустой слот
запрещена (`UsageError`) — команда только редактирует уже существующие
варианты, а не добавляет новые; удаление варианта и редактирование весов
вариантов пока не реализованы.

`--image "N=/путь/к/файлу.png"` заменяет изображение, которое сейчас стоит на
позиции N набора кампании, локальным файлом PNG/JPEG/GIF — через модалку
менеджера изображений на странице редактирования. **Известное ограничение —
набор переупорядочивается.** У Яндекса вообще нет примитива «заменить
изображение в позиции», есть только «удалить из набора» и «добавить в набор»,
поэтому точечная замена собирается из этих двух операций — а загруженное
изображение всегда встаёт в КОНЕЦ набора (подтверждено живьём), а не на
освободившуюся позицию. Замена позиции 2 в наборе `[A, B, C, D]` даёт
`[A, C, D, NEW]`, а не `[A, NEW, C, D]`. Семантика флага — «заменить
изображение, которое сейчас на позиции N» (какое именно убрать), а не
«поставить новое на позицию N». На показы это не влияет: Яндекс всё равно
ротирует изображения по эффективности независимо от их порядка в наборе.
В отличие от заголовков и текстов, фиксированного числа слотов здесь нет:
верхняя граница N — это фактическое число изображений у кампании (в пределах
жёсткого лимита Яндекса в 5 штук), прочитанное со страницы, а кампания вообще
без изображений — законное состояние, на котором `--image` падает отдельной
внятной ошибкой, а не generic «out of range». Несуществующий путь и
неподдерживаемое расширение отлетают ещё до открытия браузера. `--image`
заменяет только одно уже существующее изображение за раз — для добавления
сверх текущего набора, удаления без замены или полной замены всего набора
разом используйте `masters adimages` ниже. Поскольку и удаление, и загрузка
происходят внутри одной открытой модалки, любая ошибка до Save оставляет
сохранённый набор изображений кампании нетронутым.

`masters adimages get/add/delete/set` — полноценный CRUD-аналог `--image`
для всего набора изображений кампании, повторяющий словарь `direct adimages
get/add/delete` (API-группа изображений объявлений). В отличие от `--image`,
пустой набор изображений здесь — совершенно нормальное состояние с обеих
сторон: кампания может начинаться без единого изображения (`adimages add`
работает и с пустым набором), и все изображения можно удалить (`adimages
delete --all`), точно как изображения объявлений через API. `adimages get`
— только чтение, никогда не сохраняет. `adimages add --image-file PATH`
(можно повторять) добавляет файлы, отказывая, если текущее число изображений
плюс новые превысит лимит Яндекса в 5 штук. `adimages delete` удаляет
изображения по `--position` (1-based, как показывает `adimages get`),
`--content-id` или `--all`; `--all` на уже пустом наборе — идемпотентный
no-op, а вот конкретная позиция или content ID, которых не существует, —
всегда ошибка. `adimages set --image-file PATH` (можно повторять) заменяет
ВЕСЬ набор целиком — все текущие изображения удаляются, а все переданные
файлы загружаются внутри одной модалки; без единого `--image-file` команда
удалила бы все изображения, поэтому требуется явный `--allow-empty` для
подтверждения (или используйте `adimages delete --all`). Все три
мутирующие подкоманды принимают `--launch` (та же семантика публикации
черновика, что и у `masters update`) и, как и `--image`, НЕ идемпотентны для
`add`/`set` — повторный вызов после частичного сбоя может загрузить
дубликаты.

Остальные поля (быстрые ссылки, аудитория, счётчики Метрики/цели, адаптация
бюджета, видео) тоже пока не реализованы.

У черновика («DRAFT») страница редактирования вообще не имеет кнопки
«Сохранить кампанию» — `masters update` на черновике по умолчанию сохраняет
через «Сохранить как черновик» (статус DRAFT сохраняется); чтобы вместо
этого опубликовать кампанию при сохранении, передайте `--launch`
(«Запустить кампанию»). На не-черновиковой кампании флаг не имеет эффекта.

Если видите «Found no Yandex cookies», откройте https://direct.yandex.ru в
Chrome и войдите в аккаунт. Если используете не дефолтный профиль Chrome —
передайте `--chrome-profile "Profile 1"`.

Поскольку у этих данных нет API-контракта, парсер деградирует посекционно
(предупреждение, а не жёсткий отказ), если Яндекс изменит вёрстку страницы.

`suspend`/`resume` кликают по кнопке остановки/возобновления на странице
обзора кампании и проверяют, что статус реально изменился, прежде чем
сообщить об успехе — сам факт клика успехом не считается. Обе команды
идемпотентны (кампания уже в нужном статусе — предупреждение, а не ошибка).
У этих команд **нет `--sandbox`** — у «Мастера кампаний» нет API вообще,
поэтому нет изолированной тестовой копии; любая мутация идёт в боевой
аккаунт.

`archive` — это ближайший аналог «удаления» для «Мастера кампаний»: живая
разведка (issue #633) подтвердила, что отдельного действия «удалить» в
интерфейсе Яндекса для него **нет** — ни в меню строки на странице списка
кампаний, ни в меню страницы обзора конкретного МК, только
«Архивировать». `masters archive` кликает по этому пункту меню и
проверяет через список кампаний, что кампания реально стала архивной,
прежде чем сообщить об успехе. Команда идемпотентна (уже архивная кампания
— предупреждение, а не ошибка), но **необратима из этого CLI** — команды
`masters unarchive` нет. Тот же отказ от `--sandbox`, что и у
suspend/resume выше.

`add` создаёт новый Мастер кампаний типа «Конверсии и трафик», проходя тот же
wizard создания, что и человек в браузере. **Команда НЕ идемпотентна** —
повторный запуск с теми же аргументами создаст ВТОРУЮ кампанию, а не обновит
первую: у Мастера кампаний нет API-уровня для дедупликации, в отличие от
`campaigns add`. `--headline`/`--text` обязательны (повторяйте флаг для
нескольких значений): хотя wizard Яндекса умеет сам сгенерировать
заголовки/тексты, сканируя посадочную страницу, `add` не станет молча
публиковать AI-сгенерированный текст, который вы не проверили — передавайте
явно тот текст, который хотите опубликовать. Нужен хотя бы один из
`--region`/`--region-id` (повторяйте для нескольких регионов, значения
объединяются): `--region` принимает точную формулировку Яндекса как
свободный текст, а `--region-id` (issue #652) — числовой `RegionId`,
который резолвится в каноническое имя через словарь `GeoRegions` (`direct
dictionaries get-geo-regions`) — используйте `--region-id`, чтобы не
угадывать точный текст виджета. В отличие от остальных команд `masters`,
резолвинг `--region-id` требует действительных учётных данных Yandex Direct
API (та же цепочка приоритетов, что и у любой другой команды). По умолчанию
кампания запускается сразу; передайте `--draft`, чтобы сохранить её как
черновик
(«Сохранить как черновик») без запуска. У этой команды тоже **нет
`--sandbox`** — сначала проверьте с `--draft` и посмотрите результат в
веб-интерфейсе, прежде чем запускать по-настоящему.

`copy` клонирует существующий Мастер кампаний через меню «⋮» на странице
обзора → «Клонировать» — то же действие, что и у человека в веб-интерфейсе.
Яндекс сам предзаполняет новую кампанию заголовками, текстами, изображениями,
бюджетом и **регионом показов в исходном виде** — это полностью обходит
проблемы матчинга региона по тексту у `add --region`/`--region-id` (issues
#652/#656/#657), потому что регион нигде заново не набирается и не матчится.
Копия не переименовывается и не редактируется сверх того, что делает сам
Яндекс (он добавляет суффикс «— N» к названию) — команда намеренно 1:1
повторяет действие клонирования из веб-интерфейса; для дальнейших правок
используйте `masters update`. **Команда НЕ идемпотентна**, как и `add`:
повторный запуск создаст ВТОРУЮ копию, а не обновит первую. По умолчанию
копия сохраняется как черновик (`--draft`); передайте `--launch`, чтобы
запустить её сразу в продакшене. Тот же отказ от `--sandbox`, что и у `add`.

**Браузерная сессия (опционально, но рекомендуется):** по умолчанию `direct
masters` расшифровывает куки Chrome заново при каждом вызове — на macOS это
означает запрос доступа к Keychain каждый раз. Выполните `direct playwright
login` один раз, чтобы расшифровать и сохранить сессию
(`~/.direct-cli/playwright/session.json`, права `0600`) — последующие вызовы
`direct masters` используют её автоматически, без повторного обращения к
Keychain. Если что-то в цепочке сломано (playwright не установлен, не тот
профиль Chrome, сессия протухла) — `direct playwright doctor` покажет всю
цепочку проверок, ничего не логинясь и не записывая на диск.

**Альтернатива без Keychain:** `direct masters login` открывает видимое окно
браузера на собственном персистентном Chromium-профиле CLI
(`~/.direct-cli/chrome-profile/`) — войдите вручную через Яндекс Паспорт,
команда завершится, как только сессия подтвердится. Она вообще не трогает
ваш реальный профиль Chrome и не обращается к Keychain, поэтому одинаково
работает на macOS/Linux/Windows; цена — однократный ручной вход вместо
прозрачного копирования кук. Если этот профиль существует, `direct masters`
автоматически предпочитает его сохранённой сессии `playwright login`.
Команда интерактивная (ждёт до `--timeout` секунд, по умолчанию 300, пока вы
не войдёте), поэтому не может выполняться без присмотра. Выполните `direct
masters logout`, чтобы удалить профиль и отозвать сессию на диске (если
профиля нет — предупреждение, а не ошибка).

### Настройка

Создайте файл `.env` в рабочей директории:

```env
YANDEX_DIRECT_TOKEN=ваш_токен
YANDEX_DIRECT_LOGIN=ваш_логин_на_яндексе
```

Или передавайте credentials напрямую в команду:

```bash
direct --token ВАШ_ТОКЕН --login ВАШ_ЛОГИН campaigns get
```

Используйте профильные credentials из `.env`:

```env
YANDEX_DIRECT_TOKEN_AGENCY1=token-1
YANDEX_DIRECT_LOGIN_AGENCY1=client-login-1
YANDEX_DIRECT_TOKEN_AGENCY2=token-2
YANDEX_DIRECT_LOGIN_AGENCY2=client-login-2
```

OAuth и profile-команды:

```bash
direct auth login
direct auth login --profile agency1
direct auth login --profile agency1 --format json
direct auth login --code abc123 --profile agency1
printf '%s\n' abc123 | direct auth login --code - --profile agency1
direct auth list
direct auth use --profile agency1
direct auth status --profile agency1
direct --profile agency1 campaigns get
```

Примечания:
- OAuth profiles сохраняют refresh token и автоматически обновляют access token.
- В non-interactive shell сначала выполните `direct auth login --profile NAME`, затем завершите через `direct auth login --code - --profile NAME` и передайте browser code через stdin.
- `direct auth login --code CODE --profile NAME` сохраняется для совместимости, но автоматизация должна использовать `--code -`, чтобы не раскрывать код в process arguments.
- Если первый non-interactive шаг включает `--client-secret`, secret запоминается для последующего completion step.
- Если profile уже хранит confidential OAuth client, `direct auth login --code CODE --profile NAME` использует сохраненные `client_id` и `client_secret`.
- `direct auth login --oauth-token TOKEN` импортирует access token вручную и не включает auto-refresh.
- После успешного интерактивного входа Direct CLI спрашивает, сохранить ли
  access token и login в `.env` текущей рабочей папки; non-interactive вход этот
  вопрос не задаёт.

Порядок выбора credentials:

| Приоритет | Источник | Пример |
|-----------|----------|--------|
| 1 | Явные CLI-опции | `direct --token TOKEN --login LOGIN campaigns get` |
| 2 | Явно выбранный profile | `direct --profile agency1 campaigns get` |
| 3 | Базовые env vars или `.env` из папки запуска | `YANDEX_DIRECT_TOKEN`, `YANDEX_DIRECT_LOGIN` |
| 4 | Активный profile | `direct auth use --profile agency1` |
| 5 | 1Password references | `--op-token-ref`, `YANDEX_DIRECT_OP_TOKEN_REF` |
| 6 | Bitwarden references | `--bw-token-ref`, `YANDEX_DIRECT_BW_TOKEN_REF` |

Direct CLI автоматически читает только `.env` из текущей рабочей папки, то есть
из папки, где запущена команда `direct`. Он не ищет `.env` от папки
установленного пакета или исходного кода. Без явного `--profile` базовые
`YANDEX_DIRECT_TOKEN` / `YANDEX_DIRECT_LOGIN` из окружения или cwd `.env`
побеждают активный OAuth profile. С явным `--profile` Direct CLI использует
только OAuth/profile-env credentials этого профиля и не подставляет base
`YANDEX_DIRECT_LOGIN`; это защищает от смешивания аккаунтов. `direct auth status`
без `--profile` показывает реально выбранный источник credentials, а с
`--profile` показывает этот профиль.

> **Тесты используют безопасный порядок credentials.** Live-API тесты (например `tests/test_v4_live_contracts.py`) сначала читают `YANDEX_DIRECT_TOKEN` / `YANDEX_DIRECT_LOGIN` из окружения, затем падают на активный профиль `direct auth`, и скипают тест если ни того ни другого нет. Это защищает от случайного обращения к production API на машине разработчика с активным profile. Контракт зафиксирован в `CLAUDE.md`.

Установка остаётся через `pip install direct-cli`, а запуск команд теперь идет
через `direct`. Вызов deprecated entrypoint `direct-cli` завершается ошибкой с
подсказкой `use direct instead of direct-cli`.

### Глобальные опции

| Опция | Описание |
|-------|----------|
| `--token` | OAuth-токен доступа к API |
| `--login` | Direct client login |
| `--profile` | Имя credential profile |
| `--sandbox` | Использовать тестовое API (песочница) |

### Использование

Канонический transport-контракт выглядит так:

```bash
direct <group> <command> [flags]
```

Group naming rules:
- только lowercase ASCII
- без `_`
- многословные группы склеиваются, например `negativekeywordsharedsets`

Command naming rules:
- только lowercase
- kebab-case для многословных действий, например `check-campaigns`
- в документации и примерах каноническими считаются `get`,
  `check-dictionaries` и `has-search-volume`

Публичный naming contract задаёт исполняемый файл `direct`. Имя пакета
`direct-cli` и deprecated shim не определяют канонические CLI-имена.
`tapi-yandex-direct` может влиять на внутренний transport layer, но не
определяет канонические CLI-имена.

Текущая политика — canonical-only. Исторические aliases по умолчанию не
сохраняются в runtime CLI. Если совместимость когда-нибудь понадобится, alias
должен быть добавлен как явное exception-правило с конкретным legacy syntax из
`tapi-yandex-direct`, который действительно нужно поддержать.

Удалённые исторические имена:

| Историческое имя           | Каноническое имя             |
|----------------------------|------------------------------|
| `dynamictargets`           | `dynamicads`                 |
| `smarttargets`             | `smartadtargets`             |
| `negativekeywords`         | `negativekeywordsharedsets`  |
| `list`                     | `get`                        |
| `checkcamp`                | `check-campaigns`            |
| `checkdict`                | `check-dictionaries`         |

`direct` — это канонический transport entrypoint над API Яндекс Директа,
устанавливаемый пакетом `direct-cli`. Канонические имена CLI-групп следуют
нормализованным Python-именам из `tapi-yandex-direct`, а имена подкоманд —
это kebab-case проекции API-методов.

Базовые соответствия:

- API `dynamictextadtargets` -> Python `dynamicads` -> CLI `direct dynamicads`
- API `retargetinglists` -> Python `retargeting` -> CLI `direct retargeting`
- API `checkCampaigns` -> CLI `direct changes check-campaigns`
- API `checkDictionaries` -> CLI `direct changes check-dictionaries`
- API `hasSearchVolume` -> CLI `direct keywordsresearch has-search-volume`

### CLI Convention

The current CLI convention is defined as follows.

#### CLI Contract

The canonical command shape is:

```bash
direct <group> <command> [flags]
```

Naming rules:

- `group`:
  - lowercase ASCII only
  - no underscores
  - multiword groups are concatenated
  - examples: `dynamicads`, `smartadtargets`, `negativekeywordsharedsets`

- `command`:
  - lowercase only
  - multiword commands use kebab-case
  - examples: `get`, `set-bids`, `check-campaigns`, `has-search-volume`

Публичный naming contract задаёт исполняемый файл `direct`. Имя пакета
`direct-cli` и deprecated shim не определяют канонические CLI-имена.
`tapi-yandex-direct` может влиять на внутренний transport layer, но не
определяет канонические CLI-имена.

Текущая политика — canonical-only. Исторические aliases по умолчанию не
сохраняются в runtime CLI. Если совместимость когда-нибудь понадобится, alias
должен быть добавлен как явное explicit exception-правило с конкретным legacy
syntax, который действительно нужно поддержать.

#### Input Rules

- All user-facing input must be passed only through typed CLI flags.
- `--json` is not part of the public CLI contract.
- User-facing parameters must not be passed through `--json`.
- The CLI must not accept `SelectionCriteria`, nested payloads, update payloads, bidding rules, or any other user-facing command input through `--json`.
- Typed flags and JSON blobs must not be mixed as part of one public command contract.
- If the API requires a complex object, the CLI must expose explicit flags or subcommands instead of forwarding raw JSON.

#### Command Formatting Rules

- Every canonical CLI command must be written strictly on a single line.
- Multi-line command formatting is not allowed.
- Shell line continuation using `\` is forbidden in canonical documentation, help text, tests, and examples.

Allowed:

```bash
direct dictionaries get-geo-regions --region-ids 225,187 --fields GeoRegionId,GeoRegionName
```

Not allowed: splitting a canonical `direct ...` command over multiple shell
lines with `\`.

#### Flag Design Rules

- List inputs use comma-separated CLI syntax where appropriate.
- Money and bid values are passed only in micro-rubles, exactly as Yandex Direct API long fields define them. The CLI does not accept decimal currency amounts or convert currency units; values below 100,000 trigger a validation hint suggesting the correct scale.
- Selector fields remain explicit flags, for example:
  - `--id`
  - `--campaign-id`
  - `--adgroup-id`
- Nested API structures must be projected into typed flags instead of blob JSON.
- Help text must not advertise JSON as an alternative input path.

#### Datetime Rules

- Changes timestamps must include an explicit timezone: `YYYY-MM-DDTHH:MM:SSZ`
  or an offset such as `YYYY-MM-DDTHH:MM:SS+03:00`.
- Other datetime parameters use their method-specific documented format.
- Datetime values must be passed as a single shell token.
- Canonical `changes` examples should use the `Z` suffix; explicit offsets are
  accepted and normalized to UTC.
- Canonical examples must not use quoted space-separated datetime values.

Use:

```bash
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
```

Do not use: a `changes` timestamp without a timezone suffix, or a quoted
timestamp that contains a space between the date and time.

#### Documentation Contract

- `README` must use only canonical syntax.
- `README` must use only single-line command examples.
- Canonical examples must not contain `--json`.
- Help output and tests must enforce the same contract.

#### Examples

Valid canonical examples:

```bash
direct campaigns get --ids 1,2,3
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
direct keywordsresearch has-search-volume --keywords "buy laptop,buy desktop"
direct dynamicads set-bids --id 789 --bid 12500000
direct dictionaries get-geo-regions --region-ids 225 --fields GeoRegionId,GeoRegionName
```

Invalid examples include command lines that pass raw JSON flags, use shell
line continuations, omit the timezone suffix from `changes` datetimes, or quote
space-separated datetime values.

#### Кампании

```bash
# Получить кампании
direct campaigns get
direct campaigns get --status ACTIVE
direct campaigns get --ids 1,2,3 --format table
direct campaigns get --fetch-all --format csv --output campaigns.csv

# Создать (--dry-run покажет запрос без отправки)
direct campaigns add --name "Моя кампания" --start-date 2024-02-01 --type TEXT_CAMPAIGN --budget 1000000000 --setting ADD_METRICA_TAG=YES --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --dry-run
direct campaigns add --name "Динамическая кампания" --start-date 2024-02-01 --type DYNAMIC_TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --dry-run
direct campaigns add --name "Смарт-кампания" --start-date 2024-02-01 --type SMART_CAMPAIGN --network-strategy AVERAGE_CPC_PER_FILTER --filter-average-cpc 1000000 --counter-id 123 --dry-run

# CPA-стратегия (одна цель): --goal-id обязателен, --average-cpa/--bid-ceiling — micro-rubles
direct campaigns add --name "CPA-кампания" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy AVERAGE_CPA --network-strategy SERVING_OFF --goal-id 1234567 --average-cpa 500000000 --bid-ceiling 1000000000 --counter-ids 111,222 --dry-run

# Мульти-целевой CPA через PriorityGoals (пары goal_id:value, WSDL PriorityGoalsItem)
direct campaigns add --name "Мульти-целевой CPA" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy AVERAGE_CPA_MULTIPLE_GOALS --network-strategy SERVING_OFF --priority-goals 1234567:80,9876543:20 --bid-ceiling 1000000000 --dry-run

# Дополнительные настройки TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign/MobileAppCampaign/CpmBannerCampaign
direct campaigns add --name "Текстовые настройки" --start-date 2026-06-01 --type TEXT_CAMPAIGN --counter-ids 111,222 --relevant-keywords-budget-percent 40 --relevant-keywords-mode OPTIMAL --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns update --id 12345 --type TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --priority-goals 1234567:80:YES --tracking-params "utm_source=direct" --dry-run
direct campaigns add --name "Пакетная текстовая" --start-date 2026-06-01 --type TEXT_CAMPAIGN --package-strategy-id 700 --package-platform-search-result YES --package-platform-product-gallery YES --package-platform-network NO --dry-run
direct campaigns add --name "Единые настройки" --start-date 2026-06-01 --type UNIFIED_CAMPAIGN --setting ADD_METRICA_TAG=YES --counter-ids 111,222 --tracking-params "utm_source=direct" --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns add --name "Единая пакетная" --start-date 2026-06-01 --type UNIFIED_CAMPAIGN --package-strategy-id 700 --package-platform-search-result YES --package-platform-product-gallery YES --package-platform-maps NO --package-platform-search-organization-list YES --package-platform-network YES --dry-run
direct campaigns add --name "Динамические настройки" --start-date 2026-06-01 --type DYNAMIC_TEXT_CAMPAIGN --setting ADD_METRICA_TAG=YES --dynamic-placement-search-results YES --dynamic-placement-product-gallery NO --counter-ids 111,222 --tracking-params "utm_source=direct" --attribution-model AUTO --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns update --id 12345 --type DYNAMIC_TEXT_CAMPAIGN --setting ADD_METRICA_TAG=NO --dynamic-placement-search-results NO --priority-goals 1234567:80:YES --tracking-params "utm_source=direct" --dry-run
direct campaigns add --name "Динамическая пакетная" --start-date 2026-06-01 --type DYNAMIC_TEXT_CAMPAIGN --package-strategy-id 700 --dry-run
direct campaigns add --name "Смарт-настройки" --start-date 2026-06-01 --type SMART_CAMPAIGN --counter-id 123 --filter-average-cpc 1000000 --setting ADD_TO_FAVORITES=YES --tracking-params "utm_source=direct" --attribution-model AUTO --dry-run
direct campaigns add --name "Смарт-пакетная" --start-date 2026-06-01 --type SMART_CAMPAIGN --counter-id 123 --package-strategy-id 700 --package-platform-search YES --package-platform-network NO --dry-run
direct campaigns add --name "Мобильные настройки" --start-date 2026-06-01 --type MOBILE_APP_CAMPAIGN --setting ADD_TO_FAVORITES=YES --negative-keyword-shared-set-ids 10,11 --dry-run
direct campaigns add --name "CPM-настройки" --start-date 2026-06-01 --type CPM_BANNER_CAMPAIGN --setting ADD_METRICA_TAG=YES --counter-ids 111,222 --frequency-cap-impressions 5 --frequency-cap-period-days 7 --video-target VIEWS --dry-run
direct campaigns add --name "CPM-стратегия" --start-date 2026-06-01 --type CPM_BANNER_CAMPAIGN --network-strategy WB_MAXIMUM_IMPRESSIONS --average-cpm 120 --strategy-spend-limit 1000 --dry-run
direct campaigns update --id 12345 --type CPM_BANNER_CAMPAIGN --frequency-cap-impressions 5 --frequency-cap-period-all --dry-run

# Notification (Sms/Email) и TimeTargeting через явные CLI-флаги
direct campaigns add --name "Уведомления+Расписание" --start-date 2026-06-01 --type TEXT_CAMPAIGN --search-strategy HIGHEST_POSITION --network-strategy SERVING_OFF --notification-email ops@example.com --notification-send-warnings YES --time-targeting-schedule 1A0123456789ABCDEFGHIJKL --consider-working-weekends YES --dry-run

# TrackingParams — UTM/трекинг в подтипе кампании (TextCampaign/UnifiedCampaign/DynamicTextCampaign/SmartCampaign.TrackingParams)
direct campaigns add --name "UTM" --start-date 2026-06-01 --type TEXT_CAMPAIGN --tracking-params "utm_source=direct&utm_campaign={campaign_id}" --dry-run

# Обновление и управление статусом
direct campaigns update --id 12345 --name "Новое название" --status SUSPENDED --budget 100000000 --start-date 2024-02-10 --end-date 2024-03-01
direct campaigns update --id 12345 --type TEXT_CAMPAIGN --tracking-params "utm_source=direct&utm_medium=cpc" --dry-run
direct campaigns suspend --id 12345
direct campaigns resume --id 12345
direct campaigns archive --id 12345
direct campaigns unarchive --id 12345
direct campaigns delete --id 12345
```

#### Группы объявлений

```bash
direct adgroups get --campaign-ids 1,2,3 --limit 50
direct adgroups add --name "Группа 1" --campaign-id 12345 --region-ids 1,225 --negative-keywords "ремонт,б/у" --tracking-params "utm_source=direct" --dry-run
direct adgroups add --name "ТГО-группа с фидом" --campaign-id 12345 --region-ids 1,225 --feed-id 170 --feed-category-ids 10,11 --dry-run
direct adgroups add --name "Динамическая группа" --campaign-id 12345 --type DYNAMIC_TEXT_AD_GROUP --region-ids 1,225 --domain-url example.com --autotargeting-category EXACT=YES --dry-run
direct adgroups add --name "Динамическая группа с фидом" --campaign-id 12345 --type DYNAMIC_TEXT_FEED_AD_GROUP --region-ids 1,225 --feed-id 170 --autotargeting-category EXACT=YES --dry-run
direct adgroups add --name "CPM группа с ключевыми фразами" --campaign-id 12345 --type CPM_BANNER_KEYWORDS_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "CPM группа с профилем пользователя" --campaign-id 12345 --type CPM_BANNER_USER_PROFILE_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "CPM видео группа" --campaign-id 12345 --type CPM_VIDEO_AD_GROUP --region-ids 1,225 --dry-run
direct adgroups add --name "Смарт-группа" --campaign-id 12345 --type SMART_AD_GROUP --region-ids 1,225 --feed-id 170 --ad-title-source FEED_NAME --ad-body-source FEED_NAME --dry-run
direct adgroups add --name "ЕПК-группа" --campaign-id 12345 --type UNIFIED_AD_GROUP --region-ids 1,225 --offer-retargeting YES --dry-run
direct adgroups add --name "Группа мобильного приложения" --campaign-id 12345 --type MOBILE_APP_AD_GROUP --region-ids 1,225 --store-url https://apps.apple.com/app/id123456789 --target-device-types DEVICE_TYPE_MOBILE,DEVICE_TYPE_TABLET --target-carrier WI_FI_AND_CELLULAR --target-operating-system-version 14.0 --dry-run
direct adgroups update --id 67890 --negative-keyword-shared-set-ids 10,11 --tracking-params "utm_source=direct"
direct adgroups update --id 67890 --feed-id 170 --feed-category-ids 10,11
direct adgroups update --id 67890 --domain-url example.com --autotargeting-settings-exact YES --autotargeting-settings-without-brands YES --dry-run
direct adgroups update --id 67890 --dynamic-feed --autotargeting-category EXACT=YES --dry-run
direct adgroups update --id 67890 --target-device-types DEVICE_TYPE_TABLET --target-carrier WI_FI_ONLY --target-operating-system-version 13.0
direct adgroups update --id 67890 --ad-title-source FEED_NAME --ad-body-source FEED_DESCRIPTION
direct adgroups update --id 67890 --offer-retargeting NO
direct adgroups delete --id 67890
```

#### Объявления

```bash
direct ads get --campaign-ids 1,2,3
direct ads get --adgroup-ids 45678 --format table
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст" --href "https://example.com" --title2 "Второй заголовок" --display-url-path "deals" --mobile YES --vcard-id 111 --sitelink-set-id 222 --turbo-page-id 333 --ad-extensions "444,555" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD --title "Заголовок" --text "Текст объявления" --href "https://example.com" --final-url "https://final.example.com" --video-extension-creative-id 777 --price-extension-price 123450000 --price-extension-price-qualifier FROM --price-extension-price-currency RUB --business-id 777 --prefer-vcard-over-business NO --erir-ad-description "Объект текстового объявления" --dry-run
direct ads add --adgroup-id 12345 --type RESPONSIVE_AD --texts "Текст один,Текст два" --titles "Заголовок один,Заголовок два" --image-hashes hash1,hash2 --video-extension-ids 111,222 --href "https://example.com" --price-extension-price 123450000 --price-extension-price-qualifier FROM --price-extension-price-currency RUB --business-id 777 --erir-ad-description "Объект адаптивного объявления" --dry-run
direct ads add --adgroup-id 12345 --type SHOPPING_AD --feed-id 170 --default-texts "Текст по умолчанию" --sitelink-set-id 222 --ad-extensions "333,444" --business-id 777 --feed-filter-condition "CATEGORY:EQUALS_ANY:shoes|boots" --title-sources NAME,BRAND --text-sources DESCRIPTION --dry-run
direct ads add --adgroup-id 12345 --type LISTING_AD --feed-id 171 --default-texts "Текст листинга по умолчанию" --feed-filter-condition "CATEGORY:EQUALS_ANY:appliances" --title-sources TITLE --text-sources DESCRIPTION --dry-run
direct ads add --adgroup-id 12345 --type TEXT_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --turbo-page-id 456 --erir-ad-description "Объект объявления из конструктора" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_AD_BUILDER_AD --creative-id 123 --tracking-url "https://track.example.com" --erir-ad-description "Мобильное объявление из конструктора" --dry-run
direct ads add --adgroup-id 12345 --type CPM_BANNER_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --tracking-pixels "https://pixel.example.com/a,https://pixel.example.com/b" --dry-run
direct ads add --adgroup-id 12345 --type TEXT_IMAGE_AD --image-hash abcdefghijklmnopqrst --href "https://example.com" --turbo-page-id 555 --final-url "https://final.example.com" --erir-ad-description "Объект графического объявления" --dry-run
direct ads add --adgroup-id 12345 --type DYNAMIC_TEXT_AD --text "Динамический текст" --image-hash abcdefghijklmnopqrst --vcard-id 111 --sitelink-set-id 222 --ad-extensions "333,444" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_AD --title "Установите приложение" --text "Текст приложения" --action INSTALL --tracking-url "https://track.example.com" --mobile-app-feature PRICE=YES --video-extension-creative-id 777 --erir-ad-description "Объект мобильного объявления" --dry-run
direct ads add --adgroup-id 12345 --type MOBILE_APP_IMAGE_AD --image-hash abcdefghijklmnopqrst --tracking-url "https://track.example.com" --erir-ad-description "Мобильное графическое объявление" --dry-run
direct ads add --adgroup-id 12345 --type SMART_AD_BUILDER_AD --logo-extension-hash logoabcdefghijklmnop --dry-run
direct ads update --id 99999 --type TEXT_AD --title "Новый заголовок" --text "Новый текст" --href "https://example.com"
direct ads update --id 99999 --type TEXT_AD --image-hash abcdefghijklmnopqrst
direct ads update --id 99999 --type TEXT_AD --clear-image-hash  # удалить изображение (AdImageHash: null; только TEXT_AD / DYNAMIC_TEXT_AD / MOBILE_APP_AD)
direct ads update --id 99999 --type TEXT_AD --title2 "Новый второй заголовок" --vcard-id 222
direct ads update --id 99999 --type TEXT_AD --callouts-add "111,222" --callouts-remove "333"
direct ads update --id 99999 --type TEXT_AD --callouts-set "444,555"
direct ads update --id 99999 --type TEXT_AD --video-extension-creative-id 777 --price-extension-price 123450000 --price-extension-price-qualifier FROM --price-extension-price-currency RUB
direct ads update --id 99999 --type TEXT_AD --final-url "https://final.example.com" --age-label AGE_18 --business-id 777 --prefer-vcard-over-business NO --erir-ad-description "Объект текстового объявления"
direct ads update --id 99999 --type DYNAMIC_TEXT_AD --text "Обновленный динамический текст" --callouts-add "111,222"
direct ads update --id 99999 --type MOBILE_APP_AD --mobile-app-feature PRICE=YES --mobile-app-feature CUSTOMER_RATING=NO --video-extension-creative-id 777 --erir-ad-description "Объект мобильного объявления"
direct ads update --id 99999 --type RESPONSIVE_AD --texts "Текст один,Текст два" --titles "Заголовок один,Заголовок два" --image-hashes hash1,hash2 --video-extension-ids 111,222 --href "https://example.com" --price-extension-price 123450000 --price-extension-price-qualifier FROM --price-extension-price-currency RUB
direct ads update --id 99999 --type TEXT_IMAGE_AD --final-url "https://final.example.com" --erir-ad-description "Объект графического объявления"
direct ads update --id 99999 --type SHOPPING_AD --sitelink-set-id 222 --callouts-set "444,555" --business-id 777 --feed-filter-condition "CATEGORY:EQUALS_ANY:shoes|boots" --title-sources NAME,BRAND --text-sources DESCRIPTION --default-texts "Текст по умолчанию"
direct ads update --id 99999 --type MOBILE_APP_IMAGE_AD --image-hash abcdefghijklmnopqrst --tracking-url "https://track.example.com" --erir-ad-description "Мобильное графическое объявление"
direct ads update --id 99999 --type TEXT_AD_BUILDER_AD --creative-id 123 --creative-erir-ad-description "Объект креатива" --href "https://example.com" --turbo-page-id 456
direct ads update --id 99999 --type SMART_AD_BUILDER_AD --logo-extension-hash logoabcdefghijklmnop --erir-ad-description "Смарт-объявление из конструктора"
direct ads update --id 99999 --type CPM_BANNER_AD_BUILDER_AD --creative-id 123 --href "https://example.com" --tracking-pixels "https://pixel.example.com/a,https://pixel.example.com/b"
direct ads delete --id 99999
```

Доступные типизированные флаги TEXT_AD для `ads add` / `ads update`:
`--title`, `--text`, `--href`, `--image-hash`, `--clear-image-hash`
(только update — устанавливает `AdImageHash: null`; только TEXT_AD /
DYNAMIC_TEXT_AD / MOBILE_APP_AD, так как у TEXT_IMAGE_AD / MOBILE_APP_IMAGE_AD
поле `AdImageHash` не nillable), `--title2`, `--display-url-path`,
`--vcard-id`, `--sitelink-set-id`, `--turbo-page-id`, `--final-url`,
`--video-extension-creative-id`, `--price-extension-*`, `--business-id`,
`--prefer-vcard-over-business` и `--erir-ad-description`. Для `ads add`
`TextAd.PriceExtension` требует `--price-extension-price`,
`--price-extension-price-qualifier` и `--price-extension-price-currency`, если
передан любой price-extension флаг. В `ads update` дополнительно доступны
`--callouts-add`, `--callouts-remove` и
`--callouts-set` для управления полем `TextAdUpdateBase.CalloutSetting`
(`ext:AdExtensionSetting`) у существующего объявления — `--callouts-set`
заменяет весь список выносок и взаимоисключим с инкрементальной парой
`--callouts-add` / `--callouts-remove`. Значения price-extension передаются в micro-rubles напрямую, в том же
long-формате, который ожидает API Яндекс Директа. В `ads update` также поддерживается `--age-label`.
`--mobile` (по умолчанию `NO`) и
`--ad-extensions` доступны только в `ads add` — WSDL `TextAdUpdate` не
содержит `Mobile`, а в `ads update` расширения управляются через флаги
`--callouts-*` выше. Для TEXT_IMAGE_AD дополнительно доступен
`--turbo-page-id`, `--final-url` и `--erir-ad-description`. Для
DYNAMIC_TEXT_AD в `ads add` обязателен `--text`; доступны `--image-hash`,
`--vcard-id`, `--sitelink-set-id` и `--ad-extensions`. В `ads update`
доступны `--text`, `--image-hash`, `--vcard-id`, `--sitelink-set-id` и
`--callouts-*`.
Для RESPONSIVE_AD в `ads add` обязательны `--texts` и `--titles` как списки
через запятую, а также `--href`, `--business-id` или оба флага. Дополнительные
флаги создания: `--image-hashes`, `--video-extension-ids`, `--age-label`,
`--display-url-path`, `--sitelink-set-id`, `--ad-extensions`,
`--price-extension-*` и `--erir-ad-description`.
Для SHOPPING_AD и LISTING_AD в `ads add` обязательны `--feed-id` и одно
значение `--default-texts`. Дополнительные флаги создания:
`--sitelink-set-id`, `--ad-extensions`, `--business-id`, повторяемый
`--feed-filter-condition` (`OPERAND:OPERATOR:ARG1|ARG2`), `--title-sources` и
`--text-sources`.
Для non-SMART AdBuilder subtype в `ads add` обязателен `--creative-id`.
TEXT_AD_BUILDER_AD, CPC_VIDEO_AD_BUILDER_AD, CPM_BANNER_AD_BUILDER_AD и
CPM_VIDEO_AD_BUILDER_AD требуют `--href`, `--turbo-page-id` или оба флага.
Mobile app builder subtype используют `--tracking-url`. CPM builder subtype
также поддерживают `--tracking-pixels`; non-SMART AdBuilder subtype в
`ads add` поддерживают `--erir-ad-description`.
Для MOBILE_APP_AD в `ads add` обязательны `--title`, `--text` и `--action`;
дополнительно доступны `--mobile-app-feature FEATURE=YES|NO`,
`--video-extension-creative-id` и `--erir-ad-description`. Для
MOBILE_APP_IMAGE_AD в `ads add` обязателен `--image-hash`; в add/update
доступны `--tracking-url` и `--erir-ad-description`.
Для RESPONSIVE_AD в `ads update` доступны `--texts`, `--titles`,
`--image-hashes`, `--video-extension-ids`, `--href`, `--age-label`,
`--display-url-path`, `--sitelink-set-id`, `--callouts-*`,
`--price-extension-*`, `--business-id` и `--erir-ad-description`.
Для SHOPPING_AD и LISTING_AD в `ads update` доступны `--sitelink-set-id`,
`--callouts-*`, `--business-id`, повторяемый `--feed-filter-condition`
(`OPERAND:OPERATOR:ARG1|ARG2`), `--title-sources`, `--text-sources` и
`--default-texts`.
Для MOBILE_APP_IMAGE_AD в `ads update` доступны `--image-hash`,
`--tracking-url` и `--erir-ad-description`.
Для SMART_AD_BUILDER_AD в `ads add` доступен `--logo-extension-hash`.
Для AdBuilder subtype в `ads update` доступны `--creative-id`,
`--creative-erir-ad-description`, `--erir-ad-description` и subtype-specific
`--final-url`, `--href`, `--turbo-page-id`, `--tracking-url`,
`--tracking-pixels`. Для SMART_AD_BUILDER_AD в `ads update` доступны
`--logo-extension-hash` и `--erir-ad-description`.

#### Ключевые слова

```bash
direct keywords get --campaign-ids 1,2,3
direct keywords add --adgroup-id 12345 --keyword "купить ноутбук" --bid 10500000 --context-bid 5250000 --user-param-1 segment-a --user-param-2 segment-b --dry-run
direct keywords add --adgroup-id 12345 --keyword "---autotargeting" --autotargeting-search-bid-is-auto YES --priority HIGH --autotargeting-category EXACT=YES --autotargeting-category BROADER=NO --autotargeting-brand-option WITHOUT_BRANDS=YES --dry-run
direct keywords add --adgroup-id 12345 --keyword "---autotargeting" --autotargeting-settings-exact YES --autotargeting-settings-narrow NO --autotargeting-settings-without-brands YES --dry-run
direct keywords update --id 88888 --keyword "updated keyword text"
direct keywords update --id 88888 --autotargeting-category EXACT=YES --autotargeting-category BROADER=NO --autotargeting-brand-option WITHOUT_BRANDS=YES
direct keywords update --id 88888 --autotargeting-settings-broader YES --autotargeting-settings-with-competitors-brand NO
direct keywords delete --id 88888
```

**Пакетная загрузка ключевых слов** (CLI автоматически режет на куски по API-лимиту 10/запрос):

```bash
# Из JSONL-файла (по одному объекту ключевого слова на строку)
direct keywords add --adgroup-id 12345 --from-file keywords.jsonl

# Inline JSON-массив
direct keywords add --adgroup-id 12345 --keywords-json '[{"Keyword":"купить ноутбук"},{"Keyword":"купить ПК"}]'
```

Пример `keywords.jsonl`:

```jsonl
{"Keyword":"купить ноутбук","UserParam1":"src=ad1"}
{"Keyword":"купить ПК","UserParam2":"src=ad2"}
{"Keyword":"buy laptop","AdGroupId":99999}
```

- Ключи строки — WSDL CamelCase: `Keyword`, `AdGroupId`, `Bid`, `ContextBid`, `UserParam1`, `UserParam2`.
- `Bid` и `ContextBid` — документированные поля `Keywords.add`, но они зависят от стратегии: `Bid` только для ручных стратегий, `ContextBid` только для ручных стратегий с независимым управлением ставками в сетях. Для автоматических стратегий Яндекс игнорирует эти значения и возвращает предупреждение `10160`, поэтому не передавайте их в JSONL для auto-strategy / РСЯ-сценариев.
- Поля автотаргетинга намеренно не принимаются в batch-режиме; используйте single-item typed flags: `--autotargeting-search-bid-is-auto`, `--priority`, `--autotargeting-category`, `--autotargeting-brand-option` или `--autotargeting-settings-*`.
- `--adgroup-id` задаёт значение по умолчанию; в строке можно переопределить через `AdGroupId`.
- В каждой строке должны разрешаться `Keyword` и `AdGroupId`; неизвестные поля отклоняются с указанием номера строки.
- API-лимит: 10 элементов на запрос `keywords.add` — см. [документацию Yandex Direct](https://yandex.ru/dev/direct/doc/dg/objects/keyword.html). CLI отправит нужное число чанков и склеит `AddResults`.
- API-лимит: 200 ключевых слов на одну группу объявлений. CLI печатает предупреждение, если в каком-то `AdGroupId` во входе их больше; API отклонит излишек item-level ошибками.
- Item-level ошибки от API не прерывают batch; объединённый вывод содержит и успешные Id, и ошибки.
- При сетевой ошибке в середине batch уже созданные Id выводятся в stderr (`Partial success before failure`), чтобы при retry не возникли дубли.
- `--dry-run` показывает payload первого чанка плюс `{chunks, totalItems, chunkSize}`.

#### Отчёты

```bash
# Сформировать отчёт (сохраняется в файл)
direct reports get --type CAMPAIGN_PERFORMANCE_REPORT --from 2024-01-01 --to 2024-01-31 --name "Отчёт за январь" --fields "Date,CampaignId,Clicks,Cost" --format csv --output report.csv
direct reports get --type CUSTOM_REPORT --from 2024-01-01 --to 2024-01-31 --name "Отчёт по целям" --fields "Date,CampaignId,GoalsRoi" --goals 12345,67890 --attribution-models AUTO --format csv --output goals-report.csv

# Список доступных типов отчётов
direct reports list-types
```

Доступные типы: `CAMPAIGN_PERFORMANCE_REPORT`, `ADGROUP_PERFORMANCE_REPORT`, `AD_PERFORMANCE_REPORT`, `CRITERIA_PERFORMANCE_REPORT`, `CUSTOM_REPORT`, `REACH_AND_FREQUENCY_CAMPAIGN_REPORT`, `SEARCH_QUERY_PERFORMANCE_REPORT`

#### Другие ресурсы

```bash
# Справочники и изменения
direct dictionaries get --names Currencies,GeoRegions
direct dictionaries get-geo-regions --name Москва --region-ids 225,187 --exact-names Москва,Санкт-Петербург --fields GeoRegionId,GeoRegionName

# Информация о клиенте
direct clients get --fields ClientId,Login,Currency

# Изменения
direct changes check --campaign-ids 1,2,3 --timestamp 2026-04-14T00:00:00Z --fields CampaignIds,AdGroupIds,AdIds,CampaignsStat
direct changes check-campaigns --timestamp 2026-04-14T00:00:00Z
direct changes check-dictionaries

# Исследование ключевых слов и ретаргетинг
direct keywordsresearch has-search-volume --keywords "купить ноутбук,купить компьютер"
direct retargeting add --name "Список A" --description "Теплая аудитория" --type AUDIENCE --rule "ALL:12345:30|67890:7" --dry-run
direct retargeting update --id 55 --name "Переименованный список" --description "Обновленное примечание" --rule "ANY:12345:30" --dry-run

# Ставки и модификаторы
direct bids get --campaign-ids 123 --fields CampaignId,AdGroupId,KeywordId,Bid
direct bids set --keyword-id 123 --bid 15000000
direct bids set --campaign-id 123 --context-bid 9000000 --autotargeting-search-bid-is-auto YES --priority HIGH
direct bids set-auto --keyword-id 123 --max-bid 20000000 --position PREMIUMBLOCK --scope SEARCH --dry-run
direct keywordbids set --adgroup-id 321 --search-bid 8000000 --network-bid 3000000 --autotargeting-search-bid-is-auto NO --priority NORMAL
direct keywordbids set-auto --keyword-id 321 --target-traffic-volume 100 --increase-percent 10 --bid-ceiling 12500000 --dry-run
direct bidmodifiers get --campaign-ids 123 --fields Id,CampaignId,AdGroupId,Level,Type
direct bidmodifiers add --campaign-id 123 --type DEMOGRAPHICS_ADJUSTMENT --value 150 --gender GENDER_MALE --age AGE_25_34 --dry-run
direct bidmodifiers add --campaign-id 123 --type MOBILE_ADJUSTMENT --value 120 --operating-system-type IOS --dry-run
direct bidmodifiers set --id 99 --value 130 --dry-run

# Канонические многословные группы
direct negativekeywordsharedsets update --id 123 --keywords "foo,bar"
# audiencetargets get всегда требует фильтр — API отклоняет пустой
# SelectionCriteria, поэтому обхода всего аккаунта нет. Чтобы собрать аккаунт,
# сначала выполните `campaigns get`, затем запрашивайте audiencetargets get батчами campaign id.
direct audiencetargets get --campaign-ids 123 --fields Id,AdGroupId,RetargetingListId,State,ContextBid
direct audiencetargets add --adgroup-id 100 --retargeting-list-id 200 --bid 12000000 --priority HIGH --dry-run
direct audiencetargets set-bids --id 101 --context-bid 7000000 --priority LOW --dry-run
direct dynamicads add --adgroup-id 33 --name "Webpage A" --condition "URL:CONTAINS_ANY:test|shop" --condition "PAGE_CONTENT:CONTAINS:baz" --bid 3000000 --context-bid 2000000 --priority HIGH --dry-run
direct smartadtargets add --adgroup-id 55 --name "Audience A" --audience ALL_SEGMENTS --condition "CATEGORY_ID:EQUALS:42" --average-cpc 3000000 --average-cpa 4000000 --priority HIGH --available-items-only YES --dry-run
direct smartadtargets update --id 456 --priority HIGH
direct smartadtargets set-bids --id 456 --average-cpc 10500000 --average-cpa 15000000 --priority HIGH
direct dynamicads set-bids --id 789 --bid 12500000 --context-bid 9000000 --priority HIGH

# Общие стратегии ставок
direct strategies get --limit 5
direct strategies add --name "Общая стратегия" --type WbMaximumClicks --weekly-spend-limit 1000000000 --bid-ceiling 30000000 --dry-run
direct strategies add --name "Периодный бюджет" --type WbMaximumClicks --custom-period-spend-limit 1000000000 --custom-period-start-date 2026-06-01 --custom-period-end-date 2026-06-30 --custom-period-auto-continue YES --dry-run
direct strategies add --name "Минимальный бюджет CPA" --type AverageCpa --average-cpa 4000000 --goal-id 123 --minimum-exploration-budget 200000000 --dry-run
direct strategies add --name "CRR по целям" --type AverageCrr --average-crr 10 --goal-id 123 --priority-goal 123:2000000:YES --dry-run
direct strategies update --id 42 --type WbMaximumClicks --weekly-spend-limit 35000000 --dry-run
direct strategies update --id 42 --type WbMaximumClicks --custom-period-spend-limit 35000000 --custom-period-start-date 2026-07-01 --custom-period-end-date 2026-07-31 --custom-period-auto-continue NO --dry-run
direct strategies update --id 42 --type MaxProfit --minimum-exploration-budget 0 --dry-run
direct strategies update --id 42 --priority-goal 123:2000000:YES --dry-run
direct strategies archive --id 42 --dry-run

# Динамические таргеты по фиду
direct dynamicfeedadtargets get --adgroup-ids 123 --limit 5
direct dynamicfeedadtargets add --adgroup-id 33 --name "Срез фида А" --condition "CATEGORY:EQUALS:shoes" --bid 5000000 --dry-run
direct dynamicfeedadtargets set-bids --id 789 --bid 6500000 --context-bid 4000000 --dry-run

# Расширения, ассеты, фиды и клиенты
direct sitelinks add --sitelink "Docs|https://example.com/docs|API docs|12345" --sitelink "Help|https://example.com/help|Desk" --dry-run
direct vcards add --campaign-id 555 --country "Россия" --city "Москва" --company-name "Acme" --work-time 1#5#9#0#18#0 --phone-country-code +7 --phone-city-code 495 --phone-number 1234567 --instant-messenger-client telegram --instant-messenger-login acme_support --point-on-map-x 37.6173 --point-on-map-y 55.7558 --point-on-map-x1 37.60 --point-on-map-y1 55.74 --point-on-map-x2 37.63 --point-on-map-y2 55.77 --dry-run
direct adextensions add --callout-text "Free shipping" --dry-run
direct adimages add --name banner.png --image-data BASE64DATA --type ICON --dry-run
direct creatives add --video-id video-id --dry-run
direct feeds add --name "Фид A" --url "https://example.com/feed.xml" --business-type RETAIL --remove-utm-tags YES --feed-login feedbot --dry-run
direct feeds add --name "Фид-файл" --file-feed-path ./feed.xml --business-type RETAIL --dry-run
direct feeds update --id 18 --name "Фид A v2" --url "https://example.com/feed-v2.xml" --remove-utm-tags NO --clear-feed-login --clear-feed-password --dry-run
direct feeds update --id 18 --file-feed-path ./feed-v2.xml --file-feed-filename feed-v2.xml --dry-run
direct clients update --client-info "Приоритетный клиент" --phone +70000000000 --notification-email user@example.com --notification-lang EN --email-subscription RECEIVE_RECOMMENDATIONS=YES --setting DISPLAY_STORE_RATING=NO --dry-run
direct clients update --erir-organization-name "Рекламодатель ООО" --erir-organization-kpp 770101001 --erir-organization-epay-number epay123 --erir-organization-reg-number 1027700132195 --erir-organization-oksm-number 643 --erir-organization-okved-code 62.01 --dry-run
direct clients update --erir-contract-number C-2026-01 --erir-contract-date 2026-01-15 --erir-contract-type CONTRACT --erir-contract-action-type COMMERCIAL --erir-contract-subject-type REPRESENTATION --erir-contract-is-agency-payment NO --erir-contract-price-amount 120000.5 --erir-contract-price-including-vat YES --dry-run
direct clients update --erir-contragent-name "Контрагент ООО" --erir-contragent-kpp 770201001 --erir-contragent-phone +70000000001 --erir-contragent-epay-number epay456 --erir-contragent-reg-number 1027700132196 --erir-contragent-oksm-number 643 --erir-contragent-tin-type LEGAL --erir-contragent-tin 1234567890 --dry-run
direct --login CLIENT_LOGIN clients update --phone +70000000000 --notification-email user@example.com --dry-run
direct agencyclients add-passport-organization --name "Org" --currency RUB --notification-email ops@example.com --notification-lang EN --no-send-account-news --send-warnings --dry-run
direct agencyclients add-passport-organization-member --passport-organization-login org-login --role CHIEF --invite-email user@example.com --dry-run
direct agencyclients update --client-id 42 --phone +70000000000 --notification-email user@example.com --grant EDIT_CAMPAIGNS=YES --grant IMPORT_XLS=NO --dry-run
```

`direct agencyclients add` runtime-deprecated в Yandex Direct и блокируется CLI. Используйте `direct agencyclients add-passport-organization`.

### Известная неподдерживаемая API-операция

`dynamicads update` unsupported by API. Сервис Яндекс Директа
`dynamictextadtargets` экспортирует `add`, `get`, `delete`, `suspend`,
`resume` и `setBids`, но не экспортирует `update`. Не добавляйте и не
используйте `direct dynamicads update`, пока Яндекс не предоставит реальный
API-метод.

### Форматы вывода

Все команды `get` поддерживают `--format`:

| Формат | Описание |
|--------|----------|
| `json` | JSON (по умолчанию) |
| `table` | Таблица |
| `csv` | CSV |
| `tsv` | TSV |

```bash
direct campaigns get --format table
direct campaigns get --format csv --output campaigns.csv
```

### Пагинация

```bash
direct campaigns get --limit 10    # первые 10 результатов
direct campaigns get --fetch-all   # все страницы
```

### ⚠️ Опасные команды

Следующие команды вносят **необратимые изменения** — используйте осторожно:

| Команда | Эффект |
|---------|--------|
| `campaigns delete --id` | Безвозвратно удаляет кампанию и весь её контент |
| `adgroups delete --id` | Безвозвратно удаляет группу объявлений |
| `ads delete --id` | Безвозвратно удаляет объявление |
| `keywords delete --id` | Безвозвратно удаляет ключевое слово |
| `audiencetargets delete --id` | Безвозвратно удаляет условие подбора аудитории |

Команды, влияющие на показ рекламы: `suspend`, `resume`, `archive`, `unarchive` (доступны для `campaigns`, `ads`), `suspend`, `resume` (также для `keywords`).

Команды, влияющие на ставки и расходы: `bids set`, `keywordbids set`, `bidmodifiers set`.

Используйте `--dry-run` в командах `add` / `update`, чтобы увидеть тело запроса до отправки:

```bash
direct campaigns add --name "Тест" --start-date 2024-01-01 --dry-run
```

### Ошибки API

Яндекс Директ может вернуть успешный HTTP-ответ, внутри которого есть
item-level `Errors` для конкретного объекта. Direct CLI считает такой ответ
ошибкой операции: команда завершается с ненулевым кодом и печатает код ошибки,
сообщение и детали.

Код `8800` с `Object not found` обычно означает, что объект недоступен в
текущем `Client-Login` или аккаунте. Перед повтором проверьте выбранный
`--login`, `YANDEX_DIRECT_LOGIN` или auth profile.

### Тестирование

В `tests/` четыре уровня тестов:

| Уровень | Маркер | Сеть | Нужен токен |
|---|---|---|---|
| Юнит / CLI / dry-run | *(без маркера)* | Нет | Нет |
| Read-only интеграция | `-m integration` | Да (prod API, только чтение) | Да |
| Write интеграция | `-m integration_write` | Нет (replay VCR-кассет) | Нет |
| Live draft write интеграция (v5) | `-m integration_live_write` | Да при записи, иначе VCR replay | Да + `YANDEX_DIRECT_LIVE_WRITE=1` |
| v4 live read | `-m v4_live_read` | Да (prod v4 JSON API, только чтение) | Да |
| v4 live запись отчётов на уровне аккаунта (opt-in) | `-k _opt_in_write` в `tests/test_v4_live_contracts.py` | Да (prod v4) | Да + `YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1` |

```bash
pip install -e ".[dev]"
pytest                              # быстрый уровень — без токена
pytest -m integration -v            # read-only интеграция (нужен токен)
pytest -m integration_write -v      # replay write-кассет (токен не нужен)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v  # replay live draft-кассеты (v5)
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite  # перезапись live draft-кассеты
YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1 pytest tests/test_v4_live_contracts.py -k _opt_in_write -v  # жизненный цикл v4 wordstat/forecast
```

Уровень v4 account-level write (`YANDEX_DIRECT_V4_LIVE_REPORT_WRITE=1`) создаёт настоящие Wordstat-отчёты и прогнозы в боевом аккаунте и удаляет их в том же запуске. **Кассет нет** — эти тесты идут только в живой API. Созданные ID пишутся в `~/.direct-cli/test-orphans.json`: если запуск оборвался между create и delete, при следующем вызове осиротевшие ID будут удалены автоматически (см. `tests/_orphan_store.py`).

#### Smoke-скрипты команд

Каждая CLI-подкоманда классифицирована в `direct_cli/smoke_matrix.py`.

| Категория | Скрипт | Когда запускать |
|---|---|---|
| SAFE | `scripts/test_safe_commands.sh` | Production smoke-проверки только на чтение; нужны `YANDEX_DIRECT_TOKEN` и `YANDEX_DIRECT_LOGIN` |
| WRITE_SANDBOX | `scripts/test_sandbox_write.sh` | Live sandbox write-проверки; нужны `YANDEX_DIRECT_TOKEN` и `YANDEX_DIRECT_LOGIN`; отчёт печатает `PASS`, `FAIL`, `SANDBOX_LIMITATION` или `NOT_COVERED` для каждой команды |
| DANGEROUS | `scripts/test_dangerous_commands.sh` | Только ручной checklist; специально завершается с кодом 1 |

Текущая поверхность команд:

| Метрика | Количество |
|---|---:|
| WSDL-backed API services | 29 |
| API services с учётом Reports | 30 |
| WSDL operations | 112 |
| CLI groups с `auth` | 40 |
| CLI subcommands с `auth` | 144 |
| API CLI subcommands без `auth` | 140 |

#### Live sandbox write smoke

`WRITE_SANDBOX` smoke — это live-проверка против **sandbox-окружения**
Яндекс Директа. Она не воспроизводит сохранённый HTTP-трафик и не создаёт
новые записи. Запускайте её только когда намеренно хотите обратиться к
`api-sandbox.direct.yandex.ru`:

```bash
set -a && source .env && set +a
scripts/test_sandbox_write.sh
```

Runner выполняет команды matrix через `direct --sandbox ...`, создаёт
временные sandbox prerequisites там, где это безопасно, и удаляет их
best-effort. Отчёт содержит одну строку на каждую команду `WRITE_SANDBOX`:

- `PASS`: команда прошла против live sandbox API.
- `SANDBOX_LIMITATION`: запрос дошёл до API и получил известное ограничение
  sandbox, например коды `8800`, `1000`, `3500` или `5004`.
- `FAIL`: неожиданный CLI/API error.
- `NOT_COVERED`: runner пока не умеет безопасно построить prerequisites.

Один и тот же OAuth-токен работает и для продакшена, и для sandbox; отдельный
sandbox-токен не нужен.

Для `v4account` sandbox smoke команда `enable-shared-account` использует
`YANDEX_DIRECT_V4ACCOUNT_CLIENT_LOGIN` или fallback на `YANDEX_DIRECT_LOGIN`.
Для `account-management` нужна переменная
`YANDEX_DIRECT_V4ACCOUNT_ACCOUNT_ID`; без неё runner покажет `NOT_COVERED`.

`clients.update` включается только явно, потому что меняет client-level
metadata аккаунта. Укажите `YANDEX_DIRECT_CLIENTS_UPDATE_LOGIN` с disposable
sandbox `Client-Login`; runner передаст его через `--login` и изменит только
`ClientInfo` на уникальный smoke marker. Без этой переменной runner покажет
`NOT_COVERED` для `clients.update`.

#### Перезапись write-кассет

Уровень `integration_write` в pytest всё ещё воспроизводит сохранённый
write-трафик для регрессионного покрытия. Если вы меняете эти тесты или их
payload и намеренно хотите обновить fixtures, перезаписывайте их отдельно:

```bash
set -a && source .env && set +a        # загрузить YANDEX_DIRECT_TOKEN / LOGIN
pytest -m integration_write -v --record-mode=rewrite
```

После перезаписи **обязательно проверьте YAML-ы на утечку секретов**:

```bash
grep -r "$YANDEX_DIRECT_TOKEN" tests/cassettes/   # должно быть пусто
grep -r "$YANDEX_DIRECT_LOGIN" tests/cassettes/   # должно быть пусто
```

VCR-конфиг в `tests/conftest.py` уже стрипает `Authorization`, `Client-Login`,
куки и любые response-заголовки с подстрокой `login`, но ручная проверка
перед коммитом обязательна.

#### Live write только на черновиках

Уровень `integration_live_write` запускается только вручную и отделен от
sandbox/VCR-тестов. В rewrite-режиме он ходит в production API Яндекс Директа,
но может только создавать одноразовые черновики и удалять ровно те ID, которые
были созданы в этом же тестовом прогоне. Текущее покрытие: guarded create ->
get -> delete для draft-кампании.

Replay закоммиченной кассеты:

```bash
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v
```

Перезапись после явного решения проверить live draft-поведение:

```bash
YANDEX_DIRECT_LIVE_WRITE=1 pytest -m integration_live_write -v --record-mode=rewrite
```

В этот уровень нельзя добавлять тесты, которые принимают внешние ID,
возобновляют/останавливают/архивируют существующие ресурсы, меняют ставки или
трогают кампании, которые могут показываться.

### Публикация на PyPI

Сборка, проверка и загрузка на PyPI:

```bash
pip install -e ".[dev]"
scripts/release_pypi.sh testpypi   # загрузить на TestPyPI
scripts/release_pypi.sh pypi       # загрузить на PyPI
scripts/release_pypi.sh all        # оба
```

Скрипт читает credentials из `.env`:

```dotenv
TWINE_USERNAME=__token__
TEST_PYPI_TOKEN=pypi-...
PYPI_TOKEN=pypi-...
```

#### Области действия токенов PyPI

API-токены PyPI могут быть **account-wide** (на весь аккаунт) или **project-scoped** (на конкретный проект):

- **Project-scoped** токены работают только для конкретного проекта. Токен от `telethon-cli` не может загрузить `direct-cli` — будет **403 Forbidden**.
- **Account-wide** токены позволяют загружать в любой проект аккаунта.
- Для **первой публикации** нового проекта **необходим** account-wide токен (project-scoped нельзя создать, пока проект не зарегистрирован на PyPI).
- После первой успешной загрузки создайте project-scoped токен на https://pypi.org/manage/account/token/ и замените account-wide токен в `.env`.

Перед каждым релизом обновите `version` в `pyproject.toml` — PyPI отклоняет дубли версий.

### Лицензия

MIT
