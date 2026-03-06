# tg_json_to_md

Простой конвертер Telegram JSON export → Markdown, который **убирает “блоат”** и оставляет только читаемый текст.

## Что делает

- Берёт `messages` из Telegram export (`result.json` и т.п.)
- Пишет один абзац на сообщение:
  - `**[YYYY-MM-DD] Sender:** текст`
- **Сохраняет только ссылки** из Telegram (`text_link`) как Markdown: `[текст](url)`
- Остальные форматирования (bold/italic и т.д.) **уплощает в обычный текст**
- **Media-only сообщения пропускает** (фото/видео без текста не попадут в `.md`)

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
- `--date-format`:
  - `short` — `YYYY-MM-DD`
  - `full` — исходный timestamp из JSON (`2026-01-01T10:00:54`)

Пример с полной датой:

```bash
python json_to_md.py result.json -o telegram_cleaned.md --date-format full
```

## Примечания

- Скрипт рассчитан на типичный формат Telegram Desktop export (`messages[].text` как строка или список частей).
- Если в вашем экспорте есть другие типы/поля — можно быстро расширить `extract_text()` в `json_to_md.py`.

