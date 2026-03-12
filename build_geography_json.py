from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, UTC
from html import unescape
from pathlib import Path
from urllib.parse import urlencode

from mapping import nomoi_dict


BASE_URL = "https://www.fuelprices.gr/GetGeography"
OUTPUT_PATH = Path("geography.json")
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9,el;q=0.8",
    "Referer": "https://www.fuelprices.gr/GetGeography",
}
ENTRY_PATTERN_TEMPLATE = (
    r'<input[^>]*name="{field_name}"[^>]*value="(?P<code>[^"]+)"[^>]*>'
    r"\s*</td>\s*"
    r'<td class="checktext"[^>]*>(?P<name>.*?)</td>'
)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def infer_kind(name: str) -> str:
    return name.split(" ", 1)[0] if name else ""


def clean_label(value: str) -> str:
    value = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return normalize_whitespace(unescape(value))


def fetch_html(params: dict[str, str]) -> str:
    url = f"{BASE_URL}?{urlencode(params)}"
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)

    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "cp1253"
        return response.read().decode(charset, errors="replace")


def parse_entries(html: str, field_name: str) -> list[dict[str, str]]:
    pattern = re.compile(
        ENTRY_PATTERN_TEMPLATE.format(field_name=re.escape(field_name)),
        re.IGNORECASE | re.DOTALL,
    )
    entries: list[dict[str, str]] = []
    for match in pattern.finditer(html):
        name = clean_label(match.group("name"))
        entries.append(
            {
                "code": match.group("code"),
                "name": name,
                "kind": infer_kind(name),
            }
        )

    return entries


def fetch_municipality_children(
    nomos_code: str,
    municipality_code: str,
) -> list[dict[str, str]]:
    html = fetch_html(
        {
            "nomos": nomos_code,
            "return_to": "CheckPrices",
            "dimos": municipality_code,
            "submit": "Επόμενο",
        }
    )
    return parse_entries(html, "DD")


def fetch_geographies(nomos_code: str) -> list[dict[str, object]]:
    html = fetch_html({"nomos": nomos_code})
    entries = parse_entries(html, "dimos")

    if not entries:
        raise ValueError(f"Δεν βρέθηκαν geography entries για νομό {nomos_code}")

    geographies: list[dict[str, object]] = []
    for entry in entries:
        children = fetch_municipality_children(nomos_code, entry["code"])
        geographies.append(
            {
                **entry,
                "children": children,
            }
        )

    return geographies


def build_payload() -> dict[str, object]:
    nomoi: dict[str, dict[str, object]] = {}

    for nomos_code, nomos_name in nomoi_dict.items():
        print(f"[FETCH] {nomos_code} {nomos_name}")
        nomoi[nomos_code] = {
            "name": nomos_name,
            "geographies": fetch_geographies(nomos_code),
        }

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "https://www.fuelprices.gr/GetGeography?nomos=<nomos_code>",
        "nomoi": nomoi,
    }


def main() -> None:
    payload = build_payload()
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[DONE] Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
