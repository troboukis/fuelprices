from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = (
    "https://www.fuelprices.gr/deltia_d/files/deltia/"
    "IMERISIO_DELTIO_PANELLINIO_{date}.pdf"
)
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
    "Accept-Encoding": "gzip, deflate, br",
    "Host": "www.fuelprices.gr",
    "Referer": "https://www.fuelprices.gr/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Connection": "keep-alive",
}
DEFAULT_START_DATE = dt.date(2017, 3, 14)
DEFAULT_OUTPUT_DIR = Path("daily_reports")
CHUNK_SIZE = 64 * 1024
DEFAULT_RETRIES = 8
PER_DOWNLOAD_DELAY_SECONDS = 2.0
RETRY_DELAY_SECONDS = 5.0
REPORT_GLOB = "IMERISIO_DELTIO_PANELLINIO_*.pdf"


def parse_date(value: str) -> dt.date:
    try:
        return dt.datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def daterange(start_date: dt.date, end_date: dt.date):
    current = start_date
    while current <= end_date:
        yield current
        current += dt.timedelta(days=1)


def report_filename(report_date: dt.date) -> str:
    return f"IMERISIO_DELTIO_PANELLINIO_{report_date.strftime('%d_%m_%Y')}.pdf"


def find_latest_local_report_date(output_dir: Path) -> dt.date | None:
    latest_date: dt.date | None = None

    for path in output_dir.glob(REPORT_GLOB):
        try:
            report_date = dt.datetime.strptime(
                path.stem.removeprefix("IMERISIO_DELTIO_PANELLINIO_"),
                "%d_%m_%Y",
            ).date()
        except ValueError:
            continue

        if latest_date is None or report_date > latest_date:
            latest_date = report_date

    return latest_date


def format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{num_bytes}B"


def render_progress(current: int, total: int, *, width: int = 28) -> str:
    if total <= 0:
        return "[" + ("-" * width) + "]"
    ratio = min(max(current / total, 0), 1)
    filled = int(width * ratio)
    return "[" + ("#" * filled) + ("-" * (width - filled)) + "]"


def print_file_progress(
    label: str,
    bytes_downloaded: int,
    total_bytes: int | None,
) -> None:
    if total_bytes:
        bar = render_progress(bytes_downloaded, total_bytes)
        percent = min((bytes_downloaded / total_bytes) * 100, 100)
        message = (
            f"\r{label} {bar} {percent:6.2f}% "
            f"{format_bytes(bytes_downloaded)}/{format_bytes(total_bytes)}"
        )
    else:
        message = f"\r{label} downloaded {format_bytes(bytes_downloaded)}"
    print(message, end="", flush=True)


def log_info(message: str) -> None:
    print(f"[INFO] {message}")


def log_retry(message: str) -> None:
    print(f"[RETRY] {message}")


def log_error(message: str) -> None:
    print(f"[ERROR] {message}")


def log_fatal(message: str) -> None:
    print(f"[FATAL] {message}")


def download_report(
    report_date: dt.date,
    destination: Path,
    *,
    timeout: int,
    retries: int,
) -> str:
    url = BASE_URL.format(date=report_date.strftime("%d_%m_%Y"))
    temp_path = destination.with_suffix(".tmp")
    log_info(f"{report_date.isoformat()} -> {destination.name}")
    log_info(f"URL: {url}")

    for attempt in range(1, retries + 1):
        log_info(f"Attempt {attempt}/{retries}")
        try:
            request = urllib.request.Request(url, headers=REQUEST_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                if response.status != 200:
                    if response.status == 404:
                        return "missing (404)"
                    if attempt == retries:
                        return f"fatal http error ({response.status})"
                    log_retry(
                        f"HTTP {response.status} for {destination.name}. "
                        f"Waiting {RETRY_DELAY_SECONDS:.0f}s before retry."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                content_type = response.headers.get("Content-Type", "").lower()
                if "pdf" not in content_type and content_type:
                    if "text/html" in content_type:
                        return f"missing content-type ({content_type})"
                    if attempt == retries:
                        return f"fatal content-type ({content_type})"
                    log_retry(
                        f"Server returned '{content_type}' instead of PDF for "
                        f"{destination.name}. Waiting {RETRY_DELAY_SECONDS:.0f}s before retry."
                    )
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

                content_length = response.headers.get("Content-Length")
                total_bytes = int(content_length) if content_length else None
                size_label = content_length or "unknown"
                log_info(
                    f"Response OK: content-type={content_type or 'unknown'}, "
                    f"content-length={size_label}"
                )

                destination.parent.mkdir(parents=True, exist_ok=True)
                with temp_path.open("wb") as handle:
                    bytes_downloaded = 0
                    label = f"{destination.name}"
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        bytes_downloaded += len(chunk)
                        print_file_progress(label, bytes_downloaded, total_bytes)

                print()
                log_info(
                    f"Saved {destination.name} ({format_bytes(bytes_downloaded)})"
                )

                temp_path.replace(destination)
                return "downloaded"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "missing (404)"
            if attempt == retries:
                return f"fatal http error ({exc.code})"
            log_retry(
                f"HTTP error {exc.code} for {destination.name}. "
                f"Waiting {RETRY_DELAY_SECONDS:.0f}s before retry."
            )
        except urllib.error.URLError as exc:
            if attempt == retries:
                return f"fatal url error ({exc.reason})"
            log_retry(
                f"Network error for {destination.name}: {exc.reason}. "
                f"Waiting {RETRY_DELAY_SECONDS:.0f}s before retry."
            )
        except Exception as exc:  # pragma: no cover
            if attempt == retries:
                return f"fatal error ({exc})"
            log_retry(
                f"Unexpected error for {destination.name}: {exc}. "
                f"Waiting {RETRY_DELAY_SECONDS:.0f}s before retry."
            )
        finally:
            if temp_path.exists():
                temp_path.unlink()

        time.sleep(RETRY_DELAY_SECONDS)

    return "failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download daily fuel price PDF reports from fuelprices.gr."
    )
    parser.add_argument(
        "--start-date",
        type=parse_date,
        default=None,
        help=(
            "First date to fetch in YYYY-MM-DD format. "
            "Default: latest local PDF date, or 2017-03-14 if none exist."
        ),
    )
    parser.add_argument(
        "--end-date",
        type=parse_date,
        default=dt.date.today(),
        help="Last date to fetch in YYYY-MM-DD format. Default: today.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where PDF files will be stored. Default: daily_reports.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files even if they already exist.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help=f"Retries per file for transient failures. Default: {DEFAULT_RETRIES}.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.start_date is None:
        args.start_date = find_latest_local_report_date(args.output_dir) or DEFAULT_START_DATE

    if args.start_date > args.end_date:
        parser.error("--start-date cannot be after --end-date.")

    downloaded = 0
    skipped = 0
    missing = 0
    failed = 0
    report_dates = list(daterange(args.start_date, args.end_date))
    total_reports = len(report_dates)

    print(
        "[INFO] Starting download run with "
        f"start_date={args.start_date.isoformat()} "
        f"end_date={args.end_date.isoformat()} "
        f"output_dir={args.output_dir} "
        f"force={args.force} total_reports={total_reports}"
    )

    for index, report_date in enumerate(report_dates, start=1):
        filename = report_filename(report_date)
        destination = args.output_dir / filename
        overall_bar = render_progress(index - 1, total_reports)
        print(f"[INFO] [{index}/{total_reports}] {overall_bar} {filename}")

        if destination.exists() and not args.force:
            skipped += 1
            print(f"[SKIP] {report_date.isoformat()} {filename} already exists")
            continue

        result = download_report(
            report_date,
            destination,
            timeout=args.timeout,
            retries=args.retries,
        )
        if result == "downloaded":
            print(f"[OK] {report_date.isoformat()} {filename} downloaded")
        elif result.startswith("missing"):
            print(f"[MISSING] {report_date.isoformat()} {filename} {result}")
        else:
            print(f"[ERROR] {report_date.isoformat()} {filename} {result}")

        if result == "downloaded":
            downloaded += 1
        elif result.startswith("missing"):
            missing += 1
        else:
            failed += 1
            log_fatal(
                f"Stopping run. {filename} failed after {args.retries} attempts. "
                f"Last status: {result}"
            )
            return 1

        completed_bar = render_progress(index, total_reports)
        print(
            f"[INFO] Progress {completed_bar} {index}/{total_reports} "
            f"(downloaded={downloaded}, skipped={skipped}, missing={missing})"
        )

        log_info(
            f"Waiting {PER_DOWNLOAD_DELAY_SECONDS:.0f}s before next report"
        )
        time.sleep(PER_DOWNLOAD_DELAY_SECONDS)

    print(
        "[SUMMARY] "
        f"downloaded={downloaded} skipped={skipped} missing={missing} failed={failed}"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
