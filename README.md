# recruiter_bot

Searches GitHub for technical candidates matching job descriptions from an Excel file. Outputs a ranked Excel file sorted by % of required and ideal skills matched.

## Setup

```
pip install -r requirements.txt
```

Get a free GitHub token at https://github.com/settings/tokens (no scopes needed) and set it:

```powershell
$env:GITHUB_TOKEN = "your_token_here"
```

## Usage

```
python job_matcher.py
```

1. Enter the path to your job descriptions Excel file
2. Select a job from the list
3. The script searches GitHub and outputs `candidates_JobTitle.xlsx`

## Excel Format

Your input file should have these columns:
`job`, `location`, `security clearance`, `responsibilities`, `qualifications`, `required skills`, `ideal skills`

## Output Columns

| Column | Description |
|---|---|
| Combined Score (%) | Weighted score: 70% required + 30% ideal |
| % Required Match | % of required skills found on candidate's profile |
| % Ideal Match | % of ideal skills found on candidate's profile |
| GitHub Username | Candidate's GitHub handle |
| Name | Full name (if public) |
| Location | Location (if public) |
| Security Clearance | Always "Unknown" — not available on GitHub |
| Profile URL | Link to GitHub profile |
| Required Skills Matched | Which required skills were matched |
| Ideal Skills Matched | Which ideal skills were matched |
