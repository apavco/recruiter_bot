import io
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from skills_matcher import (
    detect_columns,
    load_config,
    match_people_to_job,
    parse_skills,
    save_config,
)

CONFIG_FILE = Path(__file__).parent / "config.json"

st.set_page_config(page_title="Recruiter Bot", page_icon="🔍", layout="wide")
st.title("🔍 Recruiter Bot")
st.caption("Match candidates to job descriptions by skill overlap.")

# ── Jobs file ────────────────────────────────────────────────────────────────
st.header("1. Job Descriptions")

config = load_config()
saved_jobs_path = config.get("jobs_path", "")

jobs_source = st.radio(
    "Jobs file source",
    ["Use saved file", "Upload a new file"],
    horizontal=True,
    index=0 if saved_jobs_path and Path(saved_jobs_path).exists() else 1,
)

jobs_df = None

if jobs_source == "Use saved file":
    if saved_jobs_path and Path(saved_jobs_path).exists():
        st.success(f"Loaded: {saved_jobs_path}")
        jobs_df = pd.read_excel(saved_jobs_path)
        jobs_df.columns = [c.strip().lower().replace(" ", "_") for c in jobs_df.columns]
    else:
        st.warning("No saved jobs file found. Please upload one.")

if jobs_source == "Upload a new file":
    jobs_upload = st.file_uploader("Upload job descriptions Excel file", type=["xlsx", "xls"], key="jobs")
    if jobs_upload:
        jobs_df = pd.read_excel(jobs_upload)
        jobs_df.columns = [c.strip().lower().replace(" ", "_") for c in jobs_df.columns]
        save_path = Path(__file__).parent / jobs_upload.name
        save_path.write_bytes(jobs_upload.getvalue())
        config["jobs_path"] = str(save_path)
        save_config(config)
        st.success(f"Saved as default: {save_path}")

# ── Candidates file ───────────────────────────────────────────────────────────
st.header("2. Candidates / Skills")

people_df = None
people_upload = st.file_uploader("Upload candidates Excel file", type=["xlsx", "xls"], key="people")
if people_upload:
    people_df = pd.read_excel(people_upload)
    people_df.columns = [c.strip().lower().replace(" ", "_") for c in people_df.columns]
    st.success(f"Loaded {len(people_df)} candidates.")

# ── Job selector ──────────────────────────────────────────────────────────────
st.header("3. Select Job")

job_row = None
job_col = None

if jobs_df is not None:
    job_col = next(
        (c for c in jobs_df.columns if c in ("job", "title", "role", "job_title", "position")),
        jobs_df.columns[0],
    )
    job_options = ["— All Jobs —"] + jobs_df[job_col].tolist()
    selected = st.selectbox("Choose a job to match against", job_options)
    if selected != "— All Jobs —":
        job_row = jobs_df[jobs_df[job_col] == selected].iloc[0]

# ── Search ────────────────────────────────────────────────────────────────────
st.header("4. Search")

threshold = st.slider(
    "Minimum required skills match (%)",
    min_value=0,
    max_value=100,
    value=0,
    step=5,
    help="Only show candidates who meet or exceed this required skills match percentage.",
)

search_clicked = st.button("🔍 Search Candidates", type="primary", disabled=(jobs_df is None or people_df is None))

if search_clicked:
    jobs_to_run = (
        [(_, row) for _, row in jobs_df.iterrows()]
        if job_row is None
        else [(None, job_row)]
    )

    for _, row in jobs_to_run:
        title = row[job_col]
        results = match_people_to_job(row, job_col, people_df)
        results_df = pd.DataFrame(results)

        # Apply minimum threshold filter
        results_df = results_df[results_df["% Required Match"] >= threshold].reset_index(drop=True)

        st.subheader(f"Results — {title}")

        req_skills = parse_skills(row.get("required_skills", ""))
        ideal_skills = parse_skills(row.get("ideal_skills", ""))
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Candidates shown", len(results_df))
        col2.metric("Required skills", len(req_skills))
        col3.metric("Ideal skills", len(ideal_skills))
        col4.metric("Min threshold", f"{threshold}%")

        st.dataframe(results_df, use_container_width=True)

        # Download button
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            results_df.to_excel(writer, index=False, sheet_name="Ranked Candidates")
        safe = re.sub(r"[^\w\s-]", "", str(title)).strip().replace(" ", "_")
        st.download_button(
            label=f"⬇️ Download matches_{safe}.xlsx",
            data=buf.getvalue(),
            file_name=f"matches_{safe}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
