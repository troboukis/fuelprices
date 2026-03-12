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
DEFAULT_START_DATE = dt.date(2017, 3, 14)
DEFAULT_OUTPUT_DIR = Path("daily_reports")
CHUNK_SIZE = 64 * 1024


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


def download_report(
    report_date: dt.date,
    destination: Path,
    *,
    timeout: int,
    retries: int,
    sleep_seconds: float,
) -> str:
    url = BASE_URL.format(date=report_date.strftime("%d_%m_%Y"))
    temp_path = destination.with_suffix(".tmp")
    print(f"DEBUG: preparing download for {report_date.isoformat()} from {url}")

    for attempt in range(1, retries + 1):
        print(f"DEBUG: attempt {attempt}/{retries} for {destination.name}")
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                if response.status != 200:
                    print(
                        f"DEBUG: non-200 response for {destination.name}: {response.status}"
                    )
                    return f"missing ({response.status})"

                content_type = response.headers.get("Content-Type", "").lower()
                if "pdf" not in content_type and content_type:
                    print(
                        "DEBUG: unexpected content type for "
                        f"{destination.name}: {content_type}"
                    )
                    return f"unexpected content-type ({content_type})"

                content_length = response.headers.get("Content-Length")
                total_bytes = int(content_length) if content_length else None
                print(
                    "DEBUG: response headers for "
                    f"{destination.name}: content-type={content_type or 'unknown'}, "
                    f"content-length={content_length or 'unknown'}"
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
                print(
                    "DEBUG: completed download for "
                    f"{destination.name} ({format_bytes(bytes_downloaded)})"
                )

                temp_path.replace(destination)
                return "downloaded"
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(f"DEBUG: {destination.name} not found (404)")
                return "missing (404)"
            if attempt == retries:
                print(
                    f"DEBUG: giving up on {destination.name} after HTTP error {exc.code}"
                )
                return f"http error ({exc.code})"
            print(
                f"DEBUG: transient HTTP error for {destination.name}: {exc.code}; retrying"
            )
        except urllib.error.URLError as exc:
            if attempt == retries:
                print(
                    "DEBUG: giving up on "
                    f"{destination.name} after URL error: {exc.reason}"
                )
                return f"url error ({exc.reason})"
            print(
                "DEBUG: transient URL error for "
                f"{destination.name}: {exc.reason}; retrying"
            )
        except Exception as exc:  # pragma: no cover
            if attempt == retries:
                print(f"DEBUG: giving up on {destination.name} after error: {exc}")
                return f"error ({exc})"
            print(f"DEBUG: transient error for {destination.name}: {exc}; retrying")
        finally:
            if temp_path.exists():
                temp_path.unlink()

        time.sleep(sleep_seconds)

    return "failed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download daily fuel price PDF reports from fuelprices.gr."
    )
    parser.add_argument(
        "--start-date",
        type=parse_date,
        default=DEFAULT_START_DATE,
        help="First date to fetch in YYYY-MM-DD format. Default: 2017-03-14.",
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
        default=3,
        help="Retries per file for transient failures. Default: 3.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="Sleep between retries. Default: 0.2.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.start_date > args.end_date:
        parser.error("--start-date cannot be after --end-date.")

    downloaded = 0
    skipped = 0
    missing = 0
    failed = 0
    report_dates = list(daterange(args.start_date, args.end_date))
    total_reports = len(report_dates)

    print(
        "DEBUG: starting download run with "
        f"start_date={args.start_date.isoformat()} "
        f"end_date={args.end_date.isoformat()} "
        f"output_dir={args.output_dir} "
        f"force={args.force} total_reports={total_reports}"
    )

    for index, report_date in enumerate(report_dates, start=1):
        filename = report_filename(report_date)
        destination = args.output_dir / filename
        overall_bar = render_progress(index - 1, total_reports)
        print(
            f"DEBUG: [{index}/{total_reports}] {overall_bar} processing {filename}"
        )

        if destination.exists() and not args.force:
            skipped += 1
            print(f"{report_date.isoformat()} {filename} skipped")
            continue

        result = download_report(
            report_date,
            destination,
            timeout=args.timeout,
            retries=args.retries,
            sleep_seconds=args.sleep_seconds,
        )
        print(f"{report_date.isoformat()} {filename} {result}")

        if result == "downloaded":
            downloaded += 1
        elif result.startswith("missing"):
            missing += 1
        else:
            failed += 1

        completed_bar = render_progress(index, total_reports)
        print(
            "DEBUG: progress "
            f"{completed_bar} completed={index}/{total_reports} "
            f"downloaded={downloaded} skipped={skipped} missing={missing} failed={failed}"
        )

    print(
        "Summary: "
        f"downloaded={downloaded} skipped={skipped} missing={missing} failed={failed}"
    )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
