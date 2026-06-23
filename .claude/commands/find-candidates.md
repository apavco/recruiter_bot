# Find Candidates

You are acting as an AI recruiting assistant. Your job is to source candidates from the web, infer their fit based on their full profile — not just keyword matching — and produce a ranked Excel report.

## Step 1 — Load the job description
Read the saved job description from the dashboard config file:

```bash
python -c "import json; d=json.load(open('C:/Users/AvaPavco(CTR)/Dev/recruiter_bot/recruiter_bot/config.json')); print(d.get('job_description','NO JD FOUND'))"
```

If the output is `NO JD FOUND`, tell the recruiter to paste the job description into the dashboard first and save it, then re-run this skill.

Use the loaded job description for all steps below.

## Step 2 — Analyze the job description
Read the job description carefully. Extract:
- The core role and responsibilities
- Required technical skills (explicit and implied)
- Ideal experience background
- Seniority level
- Any domain knowledge required (e.g. fintech, healthcare, federal)
- Soft skills or culture signals if mentioned

Do NOT limit yourself to exact keywords. Think about what someone who is a strong fit for this role would look like on paper — what titles they'd have held, what technologies they'd have used, what kinds of projects they'd have worked on.

### Step 3 — Source candidates
Run the web sourcer script with the job description to pull candidates from GitHub and Stack Overflow:

```bash
cd "C:\Users\AvaPavco(CTR)\Dev\recruiter_bot\recruiter_bot" && python web_sourcer.py --jd-from-config
```

This will write raw candidate data to `sourced_candidates.json` in the repo folder.

### Step 4 — Infer fit for each candidate
Read `sourced_candidates.json`. For each candidate, reason about their fit against the job description. Go beyond matching skill names — consider:
- Does their job history suggest the right level of experience?
- Do their projects or answered questions imply skills the JD requires, even if not explicitly stated?
- Does their background match the domain or industry context of the role?
- What is missing or unclear?

Assign each candidate:
- **Fit score**: Strong / Possible / Weak
- **2-3 sentence summary** explaining the fit in recruiter-friendly language
- **Inferred skills**: skills you believe they have based on their profile, even if not explicitly listed

### Step 5 — Generate the Excel report
Run the report generator:

```bash
cd "C:\Users\AvaPavco(CTR)\Dev\recruiter_bot\recruiter_bot" && python generate_report.py
```

This reads `sourced_candidates.json` and your analysis, writes `candidates_report.xlsx` to the repo folder.

### Step 6 — Tell the recruiter
Let the recruiter know:
- How many candidates were found and from which sources
- The full path to the saved Excel file
- A brief preview of the top 3 candidates in plain English
- Any sources that returned no results and why
