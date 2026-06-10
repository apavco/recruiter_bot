import json
import re
import sys
from pathlib import Path

import pandas as pd

INPUT_FILE = Path(__file__).parent / "sourced_candidates.json"
OUTPUT_FILE = Path(__file__).parent / "candidates_report.xlsx"

SUMMARY_PLACEHOLDER = "(Claude will fill this in during the skill run)"


def load_data():
    if not INPUT_FILE.exists():
        print(f"ERROR: {INPUT_FILE} not found. Run web_sourcer.py first.")
        sys.exit(1)
    with open(INPUT_FILE) as f:
        return json.load(f)


def build_rows(data, summaries=None):
    candidates = data.get("candidates", [])
    rows = []
    for i, c in enumerate(candidates):
        summary = summaries[i] if summaries and i < len(summaries) else SUMMARY_PLACEHOLDER
        rows.append({
            "Rank": i + 1,
            "Name": c.get("name", ""),
            "Fit Summary": summary,
            "Inferred Skills": c.get("skills", ""),
            "Source": c.get("source", ""),
            "Profile URL": c.get("profile_url", ""),
            "Location": c.get("location", ""),
        })
    return rows


def save_excel(rows):
    df = pd.DataFrame(rows)

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Candidates")
        ws = writer.sheets["Candidates"]

        # Column widths
        col_widths = {
            "A": 6,   # Rank
            "B": 28,  # Name
            "C": 60,  # Fit Summary
            "D": 45,  # Inferred Skills
            "E": 18,  # Source
            "F": 40,  # Profile URL
            "G": 20,  # Location
        }
        for col, width in col_widths.items():
            ws.column_dimensions[col].width = width

        # Wrap text in summary column
        from openpyxl.styles import Alignment
        for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True)

    print(f"Saved: {OUTPUT_FILE.resolve()}")
    return str(OUTPUT_FILE.resolve())


if __name__ == "__main__":
    # Optional: accept summaries piped in as a JSON array argument
    summaries = None
    if len(sys.argv) > 1:
        try:
            summaries = json.loads(sys.argv[1])
        except json.JSONDecodeError:
            pass

    data = load_data()
    rows = build_rows(data, summaries)
    path = save_excel(rows)
    print(f"Report written with {len(rows)} candidates.")
    print(f"File: {path}")
