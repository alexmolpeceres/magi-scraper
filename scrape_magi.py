#!/usr/bin/env python3
"""
Scrapea el RSS de MAGI//ARCHIVE y manda los repos nuevos a Telegram.
Usa el feed Atom: https://tom-doerr.github.io/repo_posts/feed.xml

Ejecutar: python scrape_magi.py
Opcional: python scrape_magi.py --once  (manda todo, sin filtro de novedades)
"""

import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config ──────────────────────────────────────────────────
FEED_URL = "https://tom-doerr.github.io/repo_posts/feed.xml"
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
STATE_FILE = Path(__file__).parent / ".magi_state.json"

# ── Atom namespace ──────────────────────────────────────────
NS = {"atom": "http://www.w3.org/2005/Atom"}


def load_state() -> set:
    """Carga los IDs ya enviados desde el archivo de estado."""
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            return set(data.get("sent_ids", []))
        except (json.JSONDecodeError, KeyError):
            return set()
    return set()


def save_state(sent_ids: set):
    """Guarda los IDs enviados."""
    STATE_FILE.write_text(json.dumps({
        "sent_ids": list(sent_ids),
        "updated": datetime.now(timezone.utc).isoformat()
    }))


def fetch_feed() -> str:
    """Descarga el feed Atom."""
    resp = requests.get(FEED_URL, timeout=30, headers={
        "User-Agent": "MAGI-Scraper/1.0 (GitHub Actions bot)"
    })
    resp.raise_for_status()
    return resp.text


def parse_entries(xml_text: str) -> list[dict]:
    """Parsea el feed Atom y extrae titulo, link GitHub, descripcion, fecha."""
    root = ET.fromstring(xml_text)
    entries = []

    for entry in root.findall("atom:entry", NS):
        # Titulo
        title_el = entry.find("atom:title", NS)
        title = title_el.text.strip() if title_el is not None and title_el.text else "Unknown"

        # Fecha
        updated_el = entry.find("atom:updated", NS)
        updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""

        # Link a GitHub (rel="related")
        github_url = ""
        for link in entry.findall("atom:link", NS):
            rel = link.get("rel", "")
            if rel == "related":
                github_url = link.get("href", "")
                break

        # Descripcion desde <content> — el 2o <p> sin img
        desc = ""
        content_el = entry.find("atom:content", NS)
        if content_el is not None and content_el.text:
            paragraphs = re.findall(r"<p>(.*?)</p>", content_el.text, re.DOTALL)
            for p in paragraphs:
                if "<img" not in p:
                    desc = re.sub(r"<[^>]+>", "", p).strip()
                    break

        # ID unico para deduplicacion
        entry_id_el = entry.find("atom:id", NS)
        entry_id = entry_id_el.text.strip() if entry_id_el is not None and entry_id_el.text else ""

        entries.append({
            "id": entry_id,
            "title": title,
            "github_url": github_url,
            "description": desc,
            "updated": updated,
        })

    return entries


def send_telegram(text: str):
    """Envia mensaje a Telegram via Bot API."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN o TELEGRAM_CHAT_ID no configurados")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        print(f"Telegram error {resp.status_code}: {resp.text}")
        return False
    return True


def format_message(entries: list[dict]) -> str:
    """Formatea los repos para Telegram."""
    lines = []
    # Agrupar por fecha
    by_date = {}
    for e in entries:
        date_str = e["updated"][:10] if e["updated"] else "???"
        by_date.setdefault(date_str, []).append(e)

    for date_str in sorted(by_date.keys(), reverse=True):
        lines.append(f"<b>📅 {date_str}</b>")
        for e in by_date[date_str]:
            desc = e["description"]
            desc_line = f"  — <i>{desc}</i>" if desc else ""
            if e["github_url"]:
                lines.append(f"• <a href=\"{e['github_url']}\">{e['title']}</a>{desc_line}")
            else:
                lines.append(f"• {e['title']}{desc_line}")
        lines.append("")

    header = "<b>🔍 MAGI//ARCHIVE — Nuevos repos</b>\n"
    return header + "\n".join(lines)


def main():
    once = "--once" in sys.argv

    print(f"[{datetime.now().isoformat()}] Fetching MAGI feed...")
    xml_text = fetch_feed()
    entries = parse_entries(xml_text)
    print(f"  Found {len(entries)} entries in feed")

    sent_ids = load_state() if not once else set()
    new_entries = [e for e in entries if e["id"] and e["id"] not in sent_ids]

    if not new_entries:
        print("  No new repos to send.")
        return

    print(f"  {len(new_entries)} new repos to send")

    # Enviar en lotes de 10 para no exceder limite de Telegram
    batch_size = 10
    for i in range(0, len(new_entries), batch_size):
        batch = new_entries[i:i + batch_size]
        msg = format_message(batch)
        ok = send_telegram(msg)
        if ok:
            for e in batch:
                sent_ids.add(e["id"])
            print(f"  Sent batch {i // batch_size + 1} ({len(batch)} repos)")
        else:
            print(f"  FAILED to send batch {i // batch_size + 1}")

    if not once:
        save_state(sent_ids)
        print(f"  State saved ({len(sent_ids)} total sent)")
    print("Done.")


if __name__ == "__main__":
    main()
