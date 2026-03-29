import argparse
import json
import re
import sys
from collections import defaultdict
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


def slugify(text: str) -> str:
    slug = re.sub(r"[^\w]+", "-", text.lower(), flags=re.UNICODE)
    slug = slug.strip("-_")
    return slug or "untitled"


def detect_is_supergroup(data: dict[str, Any]) -> bool:
    chat_type = data.get("type")
    return isinstance(chat_type, str) and chat_type.endswith("supergroup")


def build_topic_roots(messages: list[dict[str, Any]]) -> dict[int, str]:
    topic_roots: dict[int, str] = {}
    for msg in messages:
        if msg.get("type") != "service":
            continue
        if msg.get("action") != "topic_created":
            continue
        msg_id = msg.get("id")
        if not isinstance(msg_id, int):
            continue
        title = msg.get("title")
        topic_roots[msg_id] = title if isinstance(title, str) and title.strip() else f"topic-{msg_id}"
    return topic_roots


def resolve_thread_bucket(
    msg: dict[str, Any],
    id_index: dict[int, dict[str, Any]],
    topic_roots: dict[int, str],
) -> tuple[tuple[str, str], str]:
    thread_id = msg.get("thread_id")
    if thread_id is not None:
        return ("thread", str(thread_id)), "thread_id"

    seen_ids: set[int] = set()
    parent_id = msg.get("reply_to_message_id")
    while isinstance(parent_id, int) and parent_id not in seen_ids:
        seen_ids.add(parent_id)

        if parent_id in topic_roots:
            return ("topic", str(parent_id)), "reply_topic"

        parent_msg = id_index.get(parent_id)
        if not isinstance(parent_msg, dict):
            break

        parent_thread_id = parent_msg.get("thread_id")
        if parent_thread_id is not None:
            return ("thread", str(parent_thread_id)), "reply_parent_thread_id"

        parent_id = parent_msg.get("reply_to_message_id")

    # In Telegram forum supergroups, the built-in General topic often has no
    # explicit `topic_created` service message in exports. When topics exist
    # but no topic/thread root can be resolved, treat it as General.
    if topic_roots:
        return ("general", "general"), "general_fallback"

    return ("unassigned", "unassigned"), "unassigned"


def build_bucket_file_name(
    base_output_path: Path,
    bucket_key: tuple[str, str],
    topic_roots: dict[int, str],
) -> Path:
    stem = base_output_path.stem
    suffix = base_output_path.suffix or ".md"

    bucket_type, bucket_value = bucket_key
    if bucket_type == "topic":
        topic_id = int(bucket_value)
        topic_title = topic_roots.get(topic_id, f"topic-{topic_id}")
        title_slug = slugify(topic_title)
        bucket_suffix = f"topic-{topic_id}-{title_slug}"
    elif bucket_type == "thread":
        bucket_suffix = f"thread-{bucket_value}"
    elif bucket_type == "general":
        bucket_suffix = "general"
    else:
        bucket_suffix = "unassigned"

    return base_output_path.with_name(f"{stem}__{bucket_suffix}{suffix}")


def format_message_line(msg: dict[str, Any], text: str, date_format: str) -> tuple[str, str]:
    date_raw = msg.get("date", "")
    date = date_raw[:10] if date_format == "short" else date_raw
    sender = msg.get("from") or msg.get("actor") or "Channel"
    return f"**[{date}] {sender}:** {text}", date_raw


def print_report(text: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    payload = (text + "\n").encode(encoding, errors="replace")
    sys.stdout.buffer.write(payload)


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
    messages = export_messages if isinstance(export_messages, list) else []
    total_in_export = len(messages)
    is_supergroup = detect_is_supergroup(data)

    total_type_message = 0
    skipped_no_text = 0
    min_date_raw: Optional[str] = None
    max_date_raw: Optional[str] = None

    if not is_supergroup:
        lines: list[str] = []
        for msg in messages:
            if msg.get("type") != "message":
                continue

            total_type_message += 1
            text = extract_text(msg)
            if not text:
                skipped_no_text += 1
                continue

            line, date_raw = format_message_line(msg, text, args.date_format)
            lines.append(line)

            if date_raw:
                min_date_raw = date_raw if min_date_raw is None or date_raw < min_date_raw else min_date_raw
                max_date_raw = date_raw if max_date_raw is None or date_raw > max_date_raw else max_date_raw

        output_path.write_text("\n\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        if min_date_raw and max_date_raw:
            date_range = f"{min_date_raw[:10]} .. {max_date_raw[:10]}"
        else:
            date_range = "N/A"

        print_report(
            "\n".join(
                [
                    "Done.",
                    "",
                    f"messages in export file = {total_in_export}",
                    f"  ...with type==message = {total_type_message}",
                    f"written to .md = {len(lines)}",
                    f"skipped_no_text = {skipped_no_text}",
                    f"date range = {date_range}",
                ]
            )
        )
        return 0

    id_index: dict[int, dict[str, Any]] = {}
    for msg in messages:
        msg_id = msg.get("id")
        if isinstance(msg_id, int):
            id_index[msg_id] = msg
    topic_roots = build_topic_roots(messages)

    bucket_lines: dict[tuple[str, str], list[str]] = defaultdict(list)
    resolution_counts: dict[str, int] = defaultdict(int)
    assigned_written = 0
    unassigned_written = 0

    for msg in messages:
        if msg.get("type") != "message":
            continue

        total_type_message += 1
        text = extract_text(msg)
        if not text:
            skipped_no_text += 1
            continue

        bucket_key, resolution_method = resolve_thread_bucket(msg, id_index, topic_roots)
        resolution_counts[resolution_method] += 1
        if bucket_key[0] == "unassigned":
            unassigned_written += 1
        else:
            assigned_written += 1

        line, date_raw = format_message_line(msg, text, args.date_format)
        bucket_lines[bucket_key].append(line)
        if date_raw:
            min_date_raw = date_raw if min_date_raw is None or date_raw < min_date_raw else min_date_raw
            max_date_raw = date_raw if max_date_raw is None or date_raw > max_date_raw else max_date_raw

    files_written: list[tuple[Path, int, tuple[str, str]]] = []
    for bucket_key in sorted(bucket_lines, key=lambda item: (item[0] == "unassigned", item[0], item[1])):
        bucket_output = build_bucket_file_name(output_path, bucket_key, topic_roots)
        lines = bucket_lines[bucket_key]
        bucket_output.write_text("\n\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        files_written.append((bucket_output, len(lines), bucket_key))

    if min_date_raw and max_date_raw:
        date_range = f"{min_date_raw[:10]} .. {max_date_raw[:10]}"
    else:
        date_range = "N/A"

    total_written = sum(item[1] for item in files_written)
    non_unassigned_bucket_count = sum(1 for key in bucket_lines if key[0] != "unassigned")
    topic_bucket_count = sum(1 for key in bucket_lines if key[0] == "topic")
    thread_bucket_count = sum(1 for key in bucket_lines if key[0] == "thread")
    general_bucket_count = sum(1 for key in bucket_lines if key[0] == "general")

    print_report(
        "\n".join(
            [
                "Done.",
                "",
                f"chat_type = {data.get('type', 'unknown')}",
                f"chat_name = {data.get('name', 'unknown')}",
                f"chat_id = {data.get('id', 'unknown')}",
                f"messages in export file = {total_in_export}",
                f"  ...with type==message = {total_type_message}",
                f"written to .md = {total_written}",
                f"skipped_no_text = {skipped_no_text}",
                f"date range = {date_range}",
                "",
                f"topic_roots_detected = {len(topic_roots)}",
                f"thread/topic buckets = {non_unassigned_bucket_count} (topic={topic_bucket_count}, thread={thread_bucket_count}, general={general_bucket_count})",
                f"assigned messages = {assigned_written}",
                f"unassigned messages = {unassigned_written}",
                "resolution methods:",
                f"  thread_id = {resolution_counts.get('thread_id', 0)}",
                f"  reply_topic = {resolution_counts.get('reply_topic', 0)}",
                f"  reply_parent_thread_id = {resolution_counts.get('reply_parent_thread_id', 0)}",
                f"  general_fallback = {resolution_counts.get('general_fallback', 0)}",
                f"  unassigned = {resolution_counts.get('unassigned', 0)}",
                "",
                f"files written = {len(files_written)}",
                "per-file message counts:",
            ]
            + [f"  {path.name} = {count}" for path, count, _ in files_written]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
