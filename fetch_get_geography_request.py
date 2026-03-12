from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


BASE_URL = "https://www.fuelprices.gr/GetGeography"
NOMOS_CODE = "A1000000"
DIMOS_CODES = [
    "A1020000",
    "A1030000",
    "A1040000",
    "A1050000",
    "A1010000",
    "A1060000",
    "A1070000",
    "A1080000",
    "A1090000",
    "A1100000",
    "A1110000",
    "A1120000",
    "A1130000",
    "A1140000",
    "A1150000",
    "A1160000",
    "A1170000",
    "A1180000",
    "A1190000",
    "A1200000",
    "A1210000",
    "A1220000",
    "A1230000",
    "A1240000",
    "A1250000",
    "A1260000",
    "A1270000",
    "A1280000",
    "A1290000",
    "A1300000",
    "A1310000",
    "A1320000",
    "A1330000",
    "A1340000",
    "A1350000",
    "A1360000",
    "A1370000",
    "A1380000",
    "A1390000",
    "A1400000",
    "A1410000",
    "A1420000",
    "A1430000",
    "A1440000",
    "A1450000",
    "A1610000",
    "A1620000",
    "A1630000",
]
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9,el;q=0.8",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


def build_query_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = [
        ("nomos", NOMOS_CODE),
        ("return_to", "CheckPrices"),
    ]
    pairs.extend(("dimos", dimos_code) for dimos_code in DIMOS_CODES)
    pairs.append(("submit", "Επόμενο"))
    return pairs


def fetch_html(timeout: int) -> tuple[str, str]:
    cookie_jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

    initial_request = urllib.request.Request(
        f"{BASE_URL}?{urllib.parse.urlencode({'nomos': NOMOS_CODE})}",
        headers=REQUEST_HEADERS,
    )
    with opener.open(initial_request, timeout=timeout):
        pass

    query_string = urllib.parse.urlencode(build_query_pairs())
    request = urllib.request.Request(
        f"{BASE_URL}?{query_string}",
        headers={
            **REQUEST_HEADERS,
            "Referer": f"{BASE_URL}?{urllib.parse.urlencode({'nomos': NOMOS_CODE})}",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "cp1253"
        html = response.read().decode(charset, errors="replace")
        return html, str(response.geturl())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch the exact fuelprices.gr GetGeography request."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("get_geography_response.html"),
        help="Path to save the HTML response.",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print the fully encoded request URL.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Request timeout in seconds.",
    )
    parser.add_argument(
        "--metadata-output",
        type=Path,
        default=None,
        help="Optional path to save the request metadata as JSON.",
    )
    args = parser.parse_args()

    query_string = urllib.parse.urlencode(build_query_pairs())
    request_url = f"{BASE_URL}?{query_string}"

    if args.print_url:
        print(request_url)

    html, final_url = fetch_html(timeout=args.timeout)
    args.output.write_text(html, encoding="utf-8")
    print(f"[DONE] Saved HTML to {args.output}")

    if args.metadata_output is not None:
        metadata = {
            "request_url": request_url,
            "final_url": final_url,
            "nomos": NOMOS_CODE,
            "dimos": DIMOS_CODES,
        }
        args.metadata_output.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[DONE] Saved metadata to {args.metadata_output}")


if __name__ == "__main__":
    main()
