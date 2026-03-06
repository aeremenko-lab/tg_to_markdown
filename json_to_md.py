import argparse
import json
from pathlib import Path
from typing import Any, Optional


def extract_text(msg: dict[str, Any]) -> Optional[str]:
    text_content = msg.get("text")
    if not text_content:
        return None

    if isinstance(text_content, str):
        full_text = text_content
    elif isinstance(text_content, list):
        parts: list[str] = []
        for part in text_content:
            if isinstance(part, str):
                parts.append(part)
                continue

            if not isinstance(part, dict):
                continue

            if part.get("type") == "text_link" and part.get("text") and part.get("href"):
                parts.append(f"[{part['text']}]({part['href']})")
                continue

            if "text" in part and isinstance(part["text"], str):
                parts.append(part["text"])

        full_text = "".join(parts)
    else:
        return None

    full_text = full_text.strip()
    return full_text or None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Telegram JSON export to cleaned Markdown (preserve links only)."
    )
    parser.add_argument("input", nargs="?", default="result.json", help="Path to Telegram export JSON")
    parser.add_argument(
        "-o",
        "--output",
        default="telegram_cleaned.md",
        help="Output Markdown path",
    )
    parser.add_argument(
        "--date-format",
        choices=["short", "full"],
        default="short",
        help='Use "short" for YYYY-MM-DD, "full" for the original timestamp',
    )

    args = parser.parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    data = json.loads(input_path.read_text(encoding="utf-8"))

    export_messages = data.get("messages", [])
    total_in_export = len(export_messages) if isinstance(export_messages, list) else 0

    lines: list[str] = []
    total_type_message = 0
    skipped_no_text = 0
    min_date_raw: Optional[str] = None
    max_date_raw: Optional[str] = None

    for msg in export_messages if isinstance(export_messages, list) else []:
        if msg.get("type") != "message":
            continue

        total_type_message += 1
        text = extract_text(msg)
        if not text:
            skipped_no_text += 1
            continue

        date_raw = msg.get("date", "")
        date = date_raw[:10] if args.date_format == "short" else date_raw
        sender = msg.get("from") or msg.get("actor") or "Channel"

        lines.append(f"**[{date}] {sender}:** {text}")

        if date_raw:
            min_date_raw = date_raw if min_date_raw is None or date_raw < min_date_raw else min_date_raw
            max_date_raw = date_raw if max_date_raw is None or date_raw > max_date_raw else max_date_raw

    output_path.write_text("\n\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    if min_date_raw and max_date_raw:
        date_range = f"{min_date_raw[:10]} .. {max_date_raw[:10]}"
    else:
        date_range = "N/A"

    print(
        "Done.\n\n",
        f"messages in export file = {total_in_export}\n",
        f"  ...with type==message = {total_type_message}\n",
        f"written to .md = {len(lines)}\n",
        f"skipped_no_text={skipped_no_text}\n",
        f"date range = {date_range}",
        sep=" ",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
