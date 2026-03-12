from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

try:
    from natural_pdf import PDF
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "natural-pdf is not installed. Run '.fuelprices/bin/pip install -r requirements.txt' first."
    ) from exc


DEFAULT_INPUT_DIR = Path("daily_reports")
DEFAULT_OUTPUT_DIR = Path("parsed_reports")
REPORT_OUTPUT = "daily_reports_parsed.csv"

REPORT_DATE_RE = re.compile(r"(\d{2})_(\d{2})_(\d{4})")
ISSUE_LINE_RE = re.compile(
    r"^(?P<city>[^,\d]+?)\s*,?\s*(?P<date>\d{2}[-/]\d{2}[-/]\d{4})$"
)
PROTOCOL_RE = re.compile(
    r"(?:Αρ(?:ιθ)?\.?\s*Πρωτ\.?|Αριθ\.?\s*Πρωτ\.?)\s*:?\s*(?P<value>.+)$"
)
PAGE_NUMBER_RE = re.compile(r"^\d+$")
BULLET_MARKER_RE = re.compile(r"^(\*{1,4})\s*(.*)$")
CID_MARKER_RE = re.compile(r"^\(cid:\d+\)$")
BULLET_SYMBOLS = {""}
BULLET_SYMBOL_LINE_RE = re.compile(r"^()\s*(.*)$")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

PRODUCT_COLUMN_MAP = {
    "amolyvdi_95_okt": "amolyvdi_95",
    "amolyvdi_100_okt": "amolyvdi_100",
    "amolyvdth_95_okt": "amolyvdi_95",
    "amolyvdth_100_okt": "amolyvdi_100",
    "amolsvdi_95_oki": "amolyvdi_95",
    "amolsvdi_100_oki": "amolyvdi_100",
}

FIXED_ROW_PREFIXES = [
    "amolyvdi_95",
    "amolyvdi_100",
    "super",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse fuelprices.gr daily report PDFs into CSV files."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="Directory containing downloaded PDF reports. Default: daily_reports.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where parsed CSV files will be written. Default: parsed_reports.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only parse the first N PDFs, useful for debugging.",
    )
    return parser.parse_args()


def log(message: str) -> None:
    print(f"[INFO] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)


def parse_report_date(path: Path) -> str:
    match = REPORT_DATE_RE.search(path.name)
    if not match:
        raise ValueError(f"Could not parse report date from filename: {path.name}")
    day, month, year = match.groups()
    return f"{int(day)}-{int(month)}-{year}"


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    value = value.replace("∆", "Δ").replace("Ω", "Ω")
    value = " ".join(value.split()).strip()
    value = value.replace(" ,", ",").replace(" .", ".").replace(" :", ":")
    return value


def group_text_elements(page) -> list[dict[str, float | str]]:
    elements = [
        element
        for element in sorted(page.words, key=lambda item: (round(item.top, 1), item.x0))
        if clean_text(element.text)
    ]

    grouped: list[dict[str, object]] = []
    current: dict[str, object] | None = None

    for element in elements:
        text = clean_text(element.text)
        if current and abs(element.top - float(current["top"])) <= 3.0:
            current["parts"].append((element.x0, text))
            current["bottom"] = max(float(current["bottom"]), element.bottom)
            continue

        if current:
            grouped.append(finalize_group(current))
        current = {
            "top": element.top,
            "bottom": element.bottom,
            "parts": [(element.x0, text)],
        }

    if current:
        grouped.append(finalize_group(current))

    return grouped


def finalize_group(group: dict[str, object]) -> dict[str, float | str]:
    parts = sorted(group["parts"], key=lambda item: item[0])
    text = clean_text(" ".join(text for _, text in parts))
    return {
        "top": float(group["top"]),
        "bottom": float(group["bottom"]),
        "text": text,
    }


def parse_metadata(lines: list[str]) -> dict[str, str]:
    metadata = {
        "issue_city": "",
        "issue_date": "",
        "protocol_number": "",
        "subject": "",
    }

    joined = clean_text(" ".join(lines[:20]))

    issue_joined = re.search(r"(Αθήνα)\s*,?\s*(\d{2}[-/]\d{2}[-/]\d{4})", joined)
    if issue_joined:
        metadata["issue_city"] = clean_text(issue_joined.group(1))
        metadata["issue_date"] = normalize_date(issue_joined.group(2))

    protocol_joined = re.search(
        r"(?:Αρ(?:ιθ)?\.?\s*Πρωτ\.?|Αριθ\.?\s*Πρωτ\.?)\s*:?\s*([0-9]+(?:\s*-\s*\d{2}/\d{2}/\d{4})?)",
        joined,
    )
    if protocol_joined:
        metadata["protocol_number"] = clean_text(protocol_joined.group(1))

    subject_joined = re.search(
        r"ΘΕΜΑ\s*:?\s*(.+?)(?=Μέσες τιμές|Προϊόν|$)",
        joined,
    )
    if subject_joined:
        metadata["subject"] = clean_text(subject_joined.group(0))

    for line in lines[:15]:
        cleaned = clean_text(line)
        if not cleaned:
            continue

        if not metadata["issue_city"] or not metadata["issue_date"]:
            issue_match = ISSUE_LINE_RE.match(cleaned)
            if issue_match:
                metadata["issue_city"] = clean_text(issue_match.group("city"))
                metadata["issue_date"] = normalize_date(issue_match.group("date"))
                continue

        if not metadata["protocol_number"]:
            protocol_match = PROTOCOL_RE.search(cleaned)
            if protocol_match:
                metadata["protocol_number"] = clean_text(protocol_match.group("value"))
                continue

        if cleaned.startswith("ΘΕΜΑ"):
            metadata["subject"] = cleaned

    return metadata


def normalize_date(value: str) -> str:
    value = value.replace("-", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            parsed = datetime.strptime(value, fmt)
            return f"{parsed.day}-{parsed.month}-{parsed.year}"
        except ValueError:
            continue
    return value


def compact_row(row: list[str | None]) -> list[str]:
    return [clean_text(cell) for cell in row if clean_text(cell)]


def slugify_product(value: str) -> str:
    value = clean_text(value).lower()
    translit = (
        ("ά", "a"),
        ("α", "a"),
        ("β", "v"),
        ("γ", "g"),
        ("δ", "d"),
        ("έ", "e"),
        ("ε", "e"),
        ("ζ", "z"),
        ("ή", "i"),
        ("η", "i"),
        ("θ", "th"),
        ("ι", "i"),
        ("ί", "i"),
        ("ϊ", "i"),
        ("ΐ", "i"),
        ("κ", "k"),
        ("λ", "l"),
        ("μ", "m"),
        ("ν", "n"),
        ("ξ", "x"),
        ("ό", "o"),
        ("ο", "o"),
        ("π", "p"),
        ("ρ", "r"),
        ("σ", "s"),
        ("ς", "s"),
        ("τ", "t"),
        ("ύ", "y"),
        ("υ", "y"),
        ("ϋ", "y"),
        ("ΰ", "y"),
        ("φ", "f"),
        ("χ", "ch"),
        ("ψ", "ps"),
        ("ώ", "o"),
        ("ω", "o"),
        ("΄", ""),
        ("'", ""),
        ("’", ""),
        ("`", ""),
        ("(", " "),
        (")", " "),
        ("/", " "),
        ("-", " "),
        ("΄", ""),
        ("τ΄", "t"),
    )
    for src, dst in translit:
        value = value.replace(src, dst)
    value = NON_ALNUM_RE.sub("_", value).strip("_")
    return PRODUCT_COLUMN_MAP.get(value, value)


def detect_dynamic_product_prefix(product_label: str) -> str:
    label = clean_text(product_label).lower()

    if "autogas" in label:
        return "autogas"
    if "diesel κ" in label or "diesel κί" in label or "diesel κίν" in label:
        return "diesel_kinisis"
    if "diesel κιν" in label or "diesel κην" in label:
        return "diesel_kinisis"
    if "diesel θ" in label or "diesel θέ" in label or "diesel θερ" in label:
        return "diesel_thermansis"
    if "diesel θερ" in label or "diesel ζη" in label:
        return "diesel_thermansis"

    return ""


def validate_pdf_path(path: Path) -> None:
    if not path.exists():
        raise ValueError(f"Input file does not exist: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Input file is empty: {path}")
    with path.open("rb") as handle:
        header = handle.read(5)
    if header != b"%PDF-":
        raise ValueError(f"Input file does not start with a PDF header: {path}")


def extract_table_rows(path: Path) -> list[dict[str, str]]:
    validate_pdf_path(path)
    pdf = PDF(str(path))
    try:
        page = pdf.pages[0]
        table = page.extract_table()
        rows = list(table)
        if not rows:
            return []

        normalized_rows: list[dict[str, str]] = []
        for raw_row in rows[1:]:
            compact = compact_row(raw_row)
            if len(compact) < 3:
                continue

            normalized_rows.append(
                {
                    "product": compact[0],
                    "station_count_raw": compact[1],
                    "mean_price_raw": compact[2],
                }
            )
        return normalized_rows
    finally:
        pdf.close()


def extract_footer_entries(path: Path, product_names: list[str]) -> tuple[list[str], list[dict[str, str]]]:
    pdf = PDF(str(path))
    try:
        page = pdf.pages[0]
        lines = group_text_elements(page)
        line_texts = [str(line["text"]) for line in lines]

        table_bottom = 0.0
        for line in lines:
            text = str(line["text"])
            if (
                any(product and product in text for product in product_names)
                or "Προϊόν" in text
                or "Αρ. Πρατηρίων" in text
                or "Μέση Τιμή" in text
            ):
                table_bottom = max(table_bottom, float(line["bottom"]))

        if table_bottom == 0.0:
            return line_texts, []

        footer_lines: list[str] = []
        previous_top: float | None = None
        for line in lines:
            text = str(line["text"])
            top = float(line["top"])
            if top <= table_bottom + 5:
                continue
            if PAGE_NUMBER_RE.fullmatch(text):
                continue
            if previous_top is not None and top - previous_top > 20:
                break
            footer_lines.append(text)
            previous_top = top

        return line_texts, group_footer_lines(footer_lines)
    finally:
        pdf.close()


def group_footer_lines(lines: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    def flush_current() -> None:
        nonlocal current
        if current and current["text"]:
            current["text"] = clean_text(current["text"])
            entries.append(current)
        current = None

    for line in lines:
        if not line or PAGE_NUMBER_RE.fullmatch(line):
            continue

        if line.startswith("ΣΗΜΕΙΩΣΕΙΣ"):
            flush_current()
            entries.append({"entry_type": "section_header", "marker": "", "text": "ΣΗΜΕΙΩΣΕΙΣ"})
            remainder = clean_text(line[len("ΣΗΜΕΙΩΣΕΙΣ") :])
            if not remainder:
                continue
            if remainder in BULLET_SYMBOLS:
                current = {"entry_type": "note", "marker": remainder, "text": ""}
                continue
            if CID_MARKER_RE.fullmatch(remainder):
                current = {"entry_type": "note", "marker": remainder, "text": ""}
                continue
            symbol_match = BULLET_SYMBOL_LINE_RE.match(remainder)
            if symbol_match:
                current = {
                    "entry_type": "note",
                    "marker": symbol_match.group(1),
                    "text": symbol_match.group(2),
                }
                continue
            if remainder:
                entries.append({"entry_type": "footer_text", "marker": "", "text": remainder})
            continue

        if line in BULLET_SYMBOLS:
            flush_current()
            current = {"entry_type": "note", "marker": line, "text": ""}
            continue

        bullet_match = BULLET_MARKER_RE.match(line)
        if bullet_match:
            flush_current()
            current = {
                "entry_type": "note",
                "marker": bullet_match.group(1),
                "text": bullet_match.group(2),
            }
            continue

        symbol_match = BULLET_SYMBOL_LINE_RE.match(line)
        if symbol_match:
            flush_current()
            current = {
                "entry_type": "note",
                "marker": symbol_match.group(1),
                "text": symbol_match.group(2),
            }
            continue

        if CID_MARKER_RE.fullmatch(line):
            flush_current()
            current = {"entry_type": "note", "marker": line, "text": ""}
            continue

        if current is not None:
            current["text"] = f"{current['text']} {line}".strip()
            continue

        entries.append({"entry_type": "footer_text", "marker": "", "text": line})

    flush_current()
    return entries


def build_report_row(
    *,
    report_date: str,
    source_file: str,
    metadata: dict[str, str],
    table_rows: list[dict[str, str]],
    footer_entries: list[dict[str, str]],
    footer_note_count: int,
) -> dict[str, str]:
    row = {
        "report_date": report_date,
        "source_file": source_file,
        "issue_city": metadata["issue_city"],
        "issue_date": metadata["issue_date"],
        "protocol_number": metadata["protocol_number"],
        "subject": metadata["subject"],
    }

    product_prefixes = [
        "amolyvdi_95",
        "amolyvdi_100",
        "super",
        "diesel_kinisis",
        "diesel_thermansis",
        "autogas",
    ]
    for prefix in product_prefixes:
        row[f"{prefix}_product_label"] = ""
        row[f"{prefix}_station_count_raw"] = ""
        row[f"{prefix}_mean_price_raw"] = ""

    for index, item in enumerate(table_rows):
        if index < len(FIXED_ROW_PREFIXES):
            prefix = FIXED_ROW_PREFIXES[index]
        else:
            prefix = detect_dynamic_product_prefix(item["product"])
        if not prefix:
            continue
        row[f"{prefix}_product_label"] = item["product"]
        row[f"{prefix}_station_count_raw"] = item["station_count_raw"]
        row[f"{prefix}_mean_price_raw"] = item["mean_price_raw"]

    notes = [
        entry["text"]
        for entry in footer_entries
        if entry["entry_type"] in {"note", "footer_text"}
    ]
    for index in range(1, footer_note_count + 1):
        row[f"footer_note_{index}"] = notes[index - 1] if index <= len(notes) else ""

    return row


def write_report_csv(rows: list[dict[str, str]], output_path: Path, footer_note_count: int) -> None:
    fieldnames = [
        "report_date",
        "source_file",
        "issue_city",
        "issue_date",
        "protocol_number",
        "subject",
        "amolyvdi_95_product_label",
        "amolyvdi_95_station_count_raw",
        "amolyvdi_95_mean_price_raw",
        "amolyvdi_100_product_label",
        "amolyvdi_100_station_count_raw",
        "amolyvdi_100_mean_price_raw",
        "super_product_label",
        "super_station_count_raw",
        "super_mean_price_raw",
        "diesel_kinisis_product_label",
        "diesel_kinisis_station_count_raw",
        "diesel_kinisis_mean_price_raw",
        "diesel_thermansis_product_label",
        "diesel_thermansis_station_count_raw",
        "diesel_thermansis_mean_price_raw",
        "autogas_product_label",
        "autogas_station_count_raw",
        "autogas_mean_price_raw",
    ]
    fieldnames.extend([f"footer_note_{index}" for index in range(1, footer_note_count + 1)])
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir

    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    pdf_paths = sorted(input_dir.glob("*.pdf"))
    if args.limit is not None:
        pdf_paths = pdf_paths[: args.limit]

    output_dir.mkdir(parents=True, exist_ok=True)

    report_rows: list[dict[str, str]] = []
    footer_note_count = 0
    skipped_paths: list[Path] = []

    log(f"Parsing {len(pdf_paths)} PDF files from {input_dir}")

    for index, path in enumerate(pdf_paths, start=1):
        log(f"[{index}/{len(pdf_paths)}] {path.name}")
        try:
            report_date = parse_report_date(path)

            table = extract_table_rows(path)
            line_texts, footer_entries = extract_footer_entries(
                path, [row["product"] for row in table]
            )
            metadata = parse_metadata(line_texts)

            footer_notes = [
                entry
                for entry in footer_entries
                if entry["entry_type"] in {"note", "footer_text"}
            ]
            footer_note_count = max(footer_note_count, len(footer_notes))
            report_rows.append(
                build_report_row(
                    report_date=report_date,
                    source_file=path.name,
                    metadata=metadata,
                    table_rows=table,
                    footer_entries=footer_entries,
                    footer_note_count=footer_note_count,
                )
            )
        except (OSError, ValueError) as exc:
            skipped_paths.append(path)
            warn(f"Skipping {path.name}: {exc}")

    report_rows = [
        build_report_row(
            report_date=row["report_date"],
            source_file=row["source_file"],
            metadata={
                "issue_city": row["issue_city"],
                "issue_date": row["issue_date"],
                "protocol_number": row["protocol_number"],
                "subject": row["subject"],
            },
            table_rows=[
                {
                    "product": row[f"{prefix}_product_label"],
                    "station_count_raw": row[f"{prefix}_station_count_raw"],
                    "mean_price_raw": row[f"{prefix}_mean_price_raw"],
                }
                for prefix in [
                    "amolyvdi_95",
                    "amolyvdi_100",
                    "super",
                    "diesel_kinisis",
                    "diesel_thermansis",
                    "autogas",
                ]
                if row[f"{prefix}_product_label"]
            ],
            footer_entries=[
                {"entry_type": "note", "marker": "", "text": row.get(key, "")}
                for key in row
                if key.startswith("footer_note_") and row.get(key, "")
            ],
            footer_note_count=footer_note_count,
        )
        for row in report_rows
    ]

    write_report_csv(report_rows, output_dir / REPORT_OUTPUT, footer_note_count)

    log(f"Wrote {len(report_rows)} report rows to {output_dir / REPORT_OUTPUT}")
    if skipped_paths:
        warn(f"Skipped {len(skipped_paths)} invalid PDF file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
