import io
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from skills_matcher import (
    detect_columns,
    get_model,
    load_config,
    match_people_to_job,
    parse_skills,
    save_config,
)
from web_sourcer import (
    build_candidates_df,
    search_github,
    search_google_linkedin,
    search_stackoverflow,
)


@st.cache_resource(show_spinner=False)
def load_semantic_model():
    return get_model()

CONFIG_FILE = Path(__file__).parent / "config.json"

st.set_page_config(page_title="Recruiter Bot", page_icon="🔍", layout="wide")
st.title("🔍 Recruiter Bot")
st.caption("Match candidates to job descriptions by skill overlap.")

with st.spinner("Loading AI model (first run only)..."):
    load_semantic_model()

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
people_upload = st.file_uploader("Upload candidates Excel file (optional if using web sourcing)", type=["xlsx", "xls"], key="people")
if people_upload:
    people_df = pd.read_excel(people_upload)
    people_df.columns = [c.strip().lower().replace(" ", "_") for c in people_df.columns]
    st.success(f"Loaded {len(people_df)} candidates.")

# ── Web sourcing ──────────────────────────────────────────────────────────────
st.header("3. Source Candidates from Web (optional)")

use_web = st.toggle("Enable web sourcing")

github_token, google_api_key, google_cx = "", "", ""
use_github, use_stackoverflow, use_google = False, False, False

if use_web:
    st.caption("Select which sources to search. Results will be combined with any uploaded candidates.")

    col_src1, col_src2, col_src3 = st.columns(3)
    use_github = col_src1.checkbox("GitHub", value=True)
    use_stackoverflow = col_src2.checkbox("Stack Overflow", value=True)
    use_google = col_src3.checkbox("Google → LinkedIn")

    if use_github:
        github_token = st.text_input(
            "GitHub token (optional — increases rate limit)",
            value=config.get("github_token", ""),
            type="password",
            help="Get a free token at github.com/settings/tokens — no scopes needed.",
        )
        if github_token and github_token != config.get("github_token"):
            config["github_token"] = github_token
            save_config(config)

    if use_google:
        g1, g2 = st.columns(2)
        google_api_key = g1.text_input(
            "Google API key",
            value=config.get("google_api_key", ""),
            type="password",
            help="Free at console.developers.google.com — enable Custom Search API.",
        )
        google_cx = g2.text_input(
            "Custom Search Engine ID",
            value=config.get("google_cx", ""),
            help="Create a free search engine at programmablesearchengine.google.com.",
        )
        if google_api_key and google_api_key != config.get("google_api_key"):
            config["google_api_key"] = google_api_key
            save_config(config)
        if google_cx and google_cx != config.get("google_cx"):
            config["google_cx"] = google_cx
            save_config(config)

# ── Job selector ──────────────────────────────────────────────────────────────
st.header("4. Select Job")

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
st.header("5. Search")

col_a, col_b = st.columns(2)
threshold = col_a.slider(
    "Minimum required skills match (%)",
    min_value=0,
    max_value=100,
    value=0,
    step=5,
    help="Only show candidates who meet or exceed this required skills match percentage.",
)
similarity = col_b.slider(
    "Semantic similarity sensitivity",
    min_value=0.30,
    max_value=0.90,
    value=0.55,
    step=0.05,
    help="How closely a candidate skill must match a job skill. Lower = more lenient, higher = stricter.",
)

can_search = jobs_df is not None and (people_df is not None or use_web)
search_clicked = st.button("🔍 Search Candidates", type="primary", disabled=not can_search)

if search_clicked:
    jobs_to_run = (
        [(_, row) for _, row in jobs_df.iterrows()]
        if job_row is None
        else [(None, job_row)]
    )

    for _, row in jobs_to_run:
        title = row[job_col]
        req_skills = parse_skills(row.get("required_skills", ""))
        ideal_skills = parse_skills(row.get("ideal_skills", ""))

        sourced = []
        if use_web:
            if use_github:
                with st.spinner("Searching GitHub..."):
                    results, err = search_github(req_skills, github_token)
                    if err:
                        st.warning(f"GitHub: {err}")
                    else:
                        sourced.append(results)
                        st.success(f"GitHub: found {len(results)} candidates")

            if use_stackoverflow:
                with st.spinner("Searching Stack Overflow..."):
                    results, err = search_stackoverflow(req_skills)
                    if err:
                        st.warning(f"Stack Overflow: {err}")
                    else:
                        sourced.append(results)
                        st.success(f"Stack Overflow: found {len(results)} candidates")

            if use_google:
                with st.spinner("Searching Google → LinkedIn..."):
                    results, err = search_google_linkedin(req_skills, google_api_key, google_cx)
                    if err:
                        st.warning(f"Google: {err}")
                    else:
                        sourced.append(results)
                        st.success(f"LinkedIn (Google): found {len(results)} candidates")

        web_df = build_candidates_df(sourced) if sourced else pd.DataFrame()
        if people_df is not None and not web_df.empty:
            combined_df = pd.concat([people_df, web_df], ignore_index=True)
        elif people_df is not None:
            combined_df = people_df
        else:
            combined_df = web_df

        if combined_df.empty:
            st.warning("No candidates to score.")
            continue

        matched = match_people_to_job(row, job_col, combined_df, threshold=similarity)
        results_df = pd.DataFrame(matched)
        results_df = results_df[results_df["% Required Match"] >= threshold].reset_index(drop=True)

        st.subheader(f"Results — {title}")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Candidates shown", len(results_df))
        col2.metric("Required skills", len(req_skills))
        col3.metric("Ideal skills", len(ideal_skills))
        col4.metric("Min threshold", f"{threshold}%")

        st.dataframe(results_df, use_container_width=True)

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

# ── Skill Results Import ───────────────────────────────────────────────────────
st.divider()
st.header("Skill Results — /find-candidates")
st.caption("Candidates sourced by the Claude skill are automatically shown here.")

SOURCED_JSON = Path(__file__).parent / "sourced_candidates.json"
REPORT_XLSX  = Path(__file__).parent / "candidates_report.xlsx"

if SOURCED_JSON.exists():
    with open(SOURCED_JSON) as f:
        skill_data = json.load(f)

    candidates = skill_data.get("candidates", [])
    jd_preview = skill_data.get("job_description", "")[:300]

    if jd_preview:
        with st.expander("Job description used"):
            st.write(jd_preview + ("..." if len(skill_data.get("job_description", "")) > 300 else ""))

    if candidates:
        skill_df = pd.DataFrame(candidates)
        skill_df.columns = [c.replace("_", " ").title() for c in skill_df.columns]

        st.metric("Candidates found", len(skill_df))
        st.dataframe(skill_df, use_container_width=True)

        # Download the skill Excel report if it exists
        if REPORT_XLSX.exists():
            with open(REPORT_XLSX, "rb") as f:
                st.download_button(
                    label="⬇️ Download candidates_report.xlsx",
                    data=f.read(),
                    file_name="candidates_report.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
        else:
            # Let the user download the raw data as Excel
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                skill_df.to_excel(writer, index=False, sheet_name="Skill Candidates")
            st.download_button(
                label="⬇️ Download skill_candidates.xlsx",
                data=buf.getvalue(),
                file_name="skill_candidates.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
    else:
        st.info("No candidates in the last skill run.")
else:
    st.info("No skill results yet. Run /find-candidates in Claude Code to populate this table.")
