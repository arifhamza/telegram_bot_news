"""
Formats the selected stories into clean, compact Telegram messages and
sends them via the plain Bot API (no heavy SDK dependency needed - it's
one HTTP POST per message).

Format (per story):

    1. News Article Title - Source Name
    https://example.com/article

We use Telegram's HTML parse mode rather than Markdown because article
titles routinely contain characters (parentheses, asterisks, brackets,
underscores) that would break Markdown parsing. HTML only requires
escaping &, < and >, which is far more robust for arbitrary titles.
"""

import html
import logging

import requests

from . import config

logger = logging.getLogger("digest_bot.telegram")

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def format_entries(articles: list) -> list:
    """Turns a list of scored/ranked articles into numbered text blocks,
    e.g. ['1. <b>Title</b> - Source\\nhttps://...', '2. ...']."""
    blocks = []
    for i, article in enumerate(articles, start=1):
        title = _escape(article["title"])
        source = _escape(article.get("source_name", ""))
        url = article["url"]  # URLs aren't HTML-escaped; Telegram auto-links plain URLs
        header = f"{i}. <b>{title}</b>"
        if source:
            header += f" - {source}"
        blocks.append(f"{header}\n{url}")
    return blocks


def chunk_message(blocks: list, limit: int = config.TELEGRAM_MESSAGE_LIMIT) -> list:
    """Packs numbered entry blocks into as few messages as possible while
    staying under Telegram's per-message character limit."""
    messages = []
    current = []
    current_len = 0
    separator = "\n\n"

    for block in blocks:
        added_len = len(block) + (len(separator) if current else 0)
        if current and current_len + added_len > limit:
            messages.append(separator.join(current))
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len += added_len

    if current:
        messages.append(separator.join(current))

    return messages


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = API_BASE.format(token=bot_token, method="sendMessage")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT_SECONDS)
        if resp.status_code == 200 and resp.json().get("ok"):
            return True
        logger.error("Telegram API error (%s): %s", resp.status_code, resp.text[:500])
        return False
    except requests.RequestException as exc:
        logger.error("Failed to reach Telegram API: %s", exc)
        return False


def send_digest(bot_token: str, chat_id: str, articles: list, generated_at_label: str) -> bool:
    """Sends the full set of stories, split across multiple messages if
    needed. Returns True only if every chunk was sent successfully."""
    if not articles:
        text = f"No new updates, sir ({generated_at_label})"
        return send_telegram_message(bot_token, chat_id, text)

    blocks = format_entries(articles)
    messages = chunk_message(blocks)

    header = f"📰 Organic Marketing Insights - {generated_at_label} ({len(articles)} updates)"
    all_ok = send_telegram_message(bot_token, chat_id, header)

    for i, message_text in enumerate(messages, start=1):
        ok = send_telegram_message(bot_token, chat_id, message_text)
        all_ok = all_ok and ok
        if not ok:
            logger.error("Failed to send digest chunk %d/%d", i, len(messages))

    return all_ok
