# tg_json_to_md

Простой конвертер Telegram JSON export → Markdown, который **убирает “блоат”** и оставляет только читаемый текст.

## Что делает

- Берёт `messages` из Telegram export (`result.json` и т.п.)
- Для обычных чатов пишет один абзац на сообщение:
  - `**[YYYY-MM-DD] Sender:** текст`
- Для `private_supergroup`/`public_supergroup` делает отдельные `.md` по тредам:
  - сначала использует `thread_id` (если есть),
  - если `thread_id` нет, пытается определить тред по цепочке `reply_to_message_id` до `topic_created`,
  - если topics обнаружены, но корень не найден, относит сообщение в `...__general.md` (встроенная тема General),
  - неразобранные сообщения (когда topics не обнаружены) пишет в `...__unassigned.md`.
- **Сохраняет только ссылки** из Telegram (`text_link`) как Markdown: `[текст](url)`
- Остальные форматирования (bold/italic и т.д.) **уплощает в обычный текст**
- **Media-only сообщения пропускает** (фото/видео без текста не попадут в `.md`)
- Service-сообщения не экспортируются в Markdown как строки, но `topic_created` используется для группировки тредов.

## Требования

- Python 3.10+

## Запуск

Из папки `tg_json_to_md`:

```bash
python json_to_md.py result.json -o telegram_cleaned.md --date-format short
```

### Параметры

- `input` (опционально): путь к JSON (по умолчанию `result.json`)
- `-o/--output`: путь к выходному `.md` (по умолчанию `telegram_cleaned.md`)
  - для supergroup это базовое имя; скрипт создаст набор файлов вида:
    - `telegram_cleaned__topic-<id>-<slug>.md`
    - `telegram_cleaned__thread-<id>.md`
    - `telegram_cleaned__general.md`
    - `telegram_cleaned__unassigned.md`
- `--date-format`:
  - `short` — `YYYY-MM-DD`
  - `full` — исходный timestamp из JSON (`2026-01-01T10:00:54`)

Пример с полной датой:

```bash
python json_to_md.py result.json -o telegram_cleaned.md --date-format full
```

Пример для supergroup:

```bash
python json_to_md.py result.json -o sprint.md --date-format short
```

Ожидаемый результат (пример):

- `sprint__topic-6-topic-6.md`
- `sprint__topic-7-topic-7.md`
- `sprint__unassigned.md`

## Примечания

- Скрипт рассчитан на типичный формат Telegram Desktop export (`messages[].text` как строка или список частей).
- Если в вашем экспорте есть другие типы/поля — можно быстро расширить `extract_text()` в `json_to_md.py`.
- После выполнения скрипт печатает статистику: тип чата, число найденных topic roots, число assigned/unassigned сообщений, методы резолва тредов и количество сообщений по каждому выходному файлу.

