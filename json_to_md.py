import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
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


def load_ignore_tokens(path: Path) -> list[str]:
    if not path.exists():
        return []

    tokens: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        tokens.append(line.lower())
    return tokens


def get_sender_display(msg: dict[str, Any]) -> str:
    return msg.get("from") or msg.get("actor") or "Channel"


def get_sender_tokens(msg: dict[str, Any]) -> list[str]:
    values = [
        msg.get("from"),
        msg.get("actor"),
        msg.get("from_id"),
        msg.get("actor_id"),
    ]
    tokens = [value.strip().lower() for value in values if isinstance(value, str) and value.strip()]
    return list(dict.fromkeys(tokens))


def sender_is_ignored(msg: dict[str, Any], ignore_tokens: list[str]) -> bool:
    if not ignore_tokens:
        return False
    sender_tokens = get_sender_tokens(msg)
    return any(ignore_token in sender_token for ignore_token in ignore_tokens for sender_token in sender_tokens)


def build_ignored_breakdown_lines(ignored_by_sender: dict[str, int]) -> list[str]:
    if not ignored_by_sender:
        return ["ignored by sender: none"]

    ordered = sorted(ignored_by_sender.items(), key=lambda item: (-item[1], item[0].lower()))
    return ["ignored by sender:"] + [f"  {sender} = {count}" for sender, count in ordered]


def choose_export_directory(base_parent: Path, now: Optional[datetime] = None) -> Path:
    timestamp = now or datetime.now()
    date_prefix = timestamp.strftime("%Y-%m_%d")

    existing_indices: set[int] = set()
    pattern = re.compile(rf"^{re.escape(date_prefix)}-(\d+)$")
    for entry in base_parent.iterdir():
        if not entry.is_dir():
            continue
        match = pattern.match(entry.name)
        if not match:
            continue
        existing_indices.add(int(match.group(1)))

    next_index = 1
    while next_index in existing_indices:
        next_index += 1

    export_dir_name = f"{date_prefix}-{next_index:02d}"
    export_dir = base_parent / export_dir_name
    export_dir.mkdir(parents=True, exist_ok=False)
    return export_dir


def maybe_move_input_json(input_path: Path, export_dir: Path, enabled: bool) -> Optional[Path]:
    if not enabled:
        return None

    src = input_path.resolve()
    dest = (export_dir / input_path.name).resolve()
    if src == dest:
        return dest

    shutil.move(str(src), str(dest))
    return dest


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
    parser.add_argument(
        "--move-json",
        action="store_true",
        help="Move input JSON to the created export directory after successful conversion",
    )

    args = parser.parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_parent = output_path.parent if output_path.parent != Path("") else Path(".")
    export_dir = choose_export_directory(output_parent)
    output_path = export_dir / output_path.name
    ignore_senders_path = Path("ignore_senders.txt")
    ignore_tokens = load_ignore_tokens(ignore_senders_path)

    data = json.loads(input_path.read_text(encoding="utf-8"))

    export_messages = data.get("messages", [])
    messages = export_messages if isinstance(export_messages, list) else []
    total_in_export = len(messages)
    is_supergroup = detect_is_supergroup(data)

    total_type_message = 0
    skipped_no_text = 0
    skipped_ignored = 0
    ignored_by_sender: dict[str, int] = defaultdict(int)
    min_date_raw: Optional[str] = None
    max_date_raw: Optional[str] = None

    if not is_supergroup:
        lines: list[str] = []
        for msg in messages:
            if msg.get("type") != "message":
                continue

            total_type_message += 1
            sender_display = get_sender_display(msg)
            if sender_is_ignored(msg, ignore_tokens):
                skipped_ignored += 1
                ignored_by_sender[sender_display] += 1
                continue

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
        moved_json_path = maybe_move_input_json(input_path, export_dir, args.move_json)

        print_report(
            "\n".join(
                [
                    "Done.",
                    "",
                    f"messages in export file = {total_in_export}",
                    f"  ...with type==message = {total_type_message}",
                    f"written to .md = {len(lines)}",
                    f"skipped_ignored = {skipped_ignored}",
                    f"skipped_no_text = {skipped_no_text}",
                    f"date range = {date_range}",
                    f"ignore rules loaded = {len(ignore_tokens)} ({ignore_senders_path})",
                    f"export directory = {export_dir}",
                    f"moved json = {moved_json_path if moved_json_path else 'no'}",
                ]
                + [""] + build_ignored_breakdown_lines(ignored_by_sender)
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
        sender_display = get_sender_display(msg)
        if sender_is_ignored(msg, ignore_tokens):
            skipped_ignored += 1
            ignored_by_sender[sender_display] += 1
            continue

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
    moved_json_path = maybe_move_input_json(input_path, export_dir, args.move_json)

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
                f"skipped_ignored = {skipped_ignored}",
                f"skipped_no_text = {skipped_no_text}",
                f"date range = {date_range}",
                f"ignore rules loaded = {len(ignore_tokens)} ({ignore_senders_path})",
                f"export directory = {export_dir}",
                f"moved json = {moved_json_path if moved_json_path else 'no'}",
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
            + [""] + build_ignored_breakdown_lines(ignored_by_sender)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
