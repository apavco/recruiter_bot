import pandas as pd
import requests
import time
import re
import os
from pathlib import Path

# ── API credentials (all free) ────────────────────────────────────────────────
# GitHub:  https://github.com/settings/tokens  (no scopes needed)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
# Google:  https://console.cloud.google.com → enable Custom Search API → create key
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
# Google:  https://programmablesearchengine.google.com → create engine → get ID
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "")
# Stack Overflow: https://stackapps.com/apps/oauth/register (optional, raises daily limit)
STACKOVERFLOW_KEY = os.getenv("STACKOVERFLOW_KEY", "")

GITHUB_HEADERS = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}


# ── Column name normalization ─────────────────────────────────────────────────
COLUMN_MAP = {
    "job": ["job", "job_title", "title", "position", "role", "job_name"],
    "location": ["location", "loc", "city", "region"],
    "security_clearance": ["security_clearance", "clearance", "security"],
    "required_skills": ["required_skills", "required", "skills", "must_have"],
    "ideal_skills": ["ideal_skills", "ideal", "preferred_skills", "nice_to_have"],
}


def load_jobs(excel_path):
    df = pd.read_excel(excel_path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    rename = {}
    for standard, candidates in COLUMN_MAP.items():
        if standard not in df.columns:
            for candidate in candidates:
                if candidate in df.columns:
                    rename[candidate] = standard
                    break

    if rename:
        df = df.rename(columns=rename)

    if "job" not in df.columns:
        print(f"\nCould not find a job title column. Columns found: {list(df.columns)}")
        col = input("Enter the column name to use as the job title: ").strip().lower().replace(" ", "_")
        df = df.rename(columns={col: "job"})

    return df


def select_job(df):
    print("\nAvailable Jobs:")
    for i, row in df.iterrows():
        print(f"  {i + 1}. {row['job']}")
    while True:
        choice = input("\nEnter job number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(df):
            return df.iloc[int(choice) - 1]
        print("Invalid choice, try again.")


def parse_skills(skills_str):
    if pd.isna(skills_str):
        return []
    return [s.strip().lower() for s in re.split(r"[,;/]+", str(skills_str)) if s.strip()]


# ── GitHub ────────────────────────────────────────────────────────────────────
def search_github(required_skills, location=None, max_results=20):
    print("\n[GitHub] Searching...")
    url = "https://api.github.com/search/users"

    queries = []
    skill_query = " ".join(required_skills[:3])
    if location and location.lower() not in ["remote", "n/a", "", "various"]:
        queries.append(f"{skill_query} location:{location}")
    queries.append(skill_query)
    if required_skills:
        queries.append(required_skills[0])

    for query in queries:
        print(f"  Query: {query}")
        resp = requests.get(url, headers=GITHUB_HEADERS, params={"q": query, "per_page": min(max_results, 30), "sort": "repositories"})

        if resp.status_code == 403:
            print("  Rate limit hit. Set GITHUB_TOKEN env var for 5000 req/hr.")
            return []
        if resp.status_code != 200:
            print(f"  Error {resp.status_code}: {resp.json().get('message', '')}")
            continue

        items = resp.json().get("items", [])
        print(f"  Found {len(items)} users.")
        if not items:
            time.sleep(1)
            continue

        candidates = []
        for user in items:
            username = user["login"]
            profile = _github_profile(username)
            skills = _github_skills(username)
            bio_words = set(re.split(r"\W+", str(profile.get("bio") or "").lower()))
            all_skills = (skills | bio_words) - {""}

            candidates.append({
                "source": "GitHub",
                "username": username,
                "name": profile.get("name", ""),
                "location": profile.get("location", ""),
                "profile_url": f"https://github.com/{username}",
                "bio": profile.get("bio", ""),
                "skills": all_skills,
                "repos": profile.get("public_repos", 0),
                "followers": profile.get("followers", 0),
            })
            time.sleep(0.1)

        return candidates

    return []


def _github_profile(username):
    resp = requests.get(f"https://api.github.com/users/{username}", headers=GITHUB_HEADERS)
    return resp.json() if resp.status_code == 200 else {}


def _github_skills(username):
    resp = requests.get(
        f"https://api.github.com/users/{username}/repos",
        headers=GITHUB_HEADERS,
        params={"per_page": 50, "sort": "updated"},
    )
    if resp.status_code != 200:
        return set()

    skills = set()
    for repo in resp.json()[:20]:
        if repo.get("language"):
            skills.add(repo["language"].lower())
        for topic in repo.get("topics", []):
            skills.add(topic.lower())
        skills.update(re.split(r"\W+", str(repo.get("description") or "").lower()))

    return skills - {""}


# ── Stack Overflow ────────────────────────────────────────────────────────────
def search_stackoverflow(required_skills, max_results=20):
    print("\n[Stack Overflow] Searching...")
    so_params = {"site": "stackoverflow", "pagesize": 10}
    if STACKOVERFLOW_KEY:
        so_params["key"] = STACKOVERFLOW_KEY

    user_ids = []
    for skill in required_skills[:3]:
        tag = re.sub(r"[^a-z0-9\-#\+]", "", skill.replace(" ", "-").replace(".", ""))
        url = f"https://api.stackexchange.com/2.3/tags/{tag}/top-answerers/all_time"
        print(f"  Tag: {tag}")
        resp = requests.get(url, params=so_params)
        if resp.status_code != 200:
            continue
        data = resp.json()
        if data.get("error_id"):
            print(f"  Tag '{tag}' not found on Stack Overflow.")
            continue
        for item in data.get("items", []):
            uid = item.get("user", {}).get("user_id")
            if uid and uid not in user_ids:
                user_ids.append(uid)
        time.sleep(0.2)

    if not user_ids:
        print("  No Stack Overflow users found.")
        return []

    print(f"  Found {len(user_ids)} users. Fetching profiles...")

    candidates = []
    for i in range(0, min(len(user_ids), max_results), 10):
        batch = user_ids[i:i + 10]
        ids_str = ";".join(str(uid) for uid in batch)
        resp = requests.get(f"https://api.stackexchange.com/2.3/users/{ids_str}", params=so_params)
        if resp.status_code != 200:
            continue

        for user in resp.json().get("items", []):
            uid = user["user_id"]
            tags_resp = requests.get(
                f"https://api.stackexchange.com/2.3/users/{uid}/top-tags",
                params={**so_params, "pagesize": 15},
            )
            user_tags = set()
            if tags_resp.status_code == 200:
                for tag in tags_resp.json().get("items", []):
                    user_tags.add(tag["tag_name"].lower())
            time.sleep(0.1)

            candidates.append({
                "source": "Stack Overflow",
                "username": user.get("display_name", ""),
                "name": user.get("display_name", ""),
                "location": user.get("location", ""),
                "profile_url": user.get("link", ""),
                "bio": f"Reputation: {user.get('reputation', 0)}",
                "skills": user_tags,
                "repos": user.get("reputation", 0),
                "followers": 0,
            })

    print(f"  Retrieved {len(candidates)} profiles.")
    return candidates


# ── Google Custom Search → LinkedIn ──────────────────────────────────────────
def search_google_linkedin(required_skills, location=None, max_results=10):
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        print("\n[Google/LinkedIn] Skipped — GOOGLE_API_KEY or GOOGLE_CSE_ID not set.")
        print("  Setup guide:")
        print("    1. https://console.cloud.google.com → Enable 'Custom Search API' → Create API key")
        print("    2. https://programmablesearchengine.google.com → New engine → search the web → get ID")
        print("    3. $env:GOOGLE_API_KEY = 'your_key'")
        print("    4. $env:GOOGLE_CSE_ID  = 'your_engine_id'")
        return []

    print("\n[Google/LinkedIn] Searching...")
    skill_query = " ".join(f'"{s}"' for s in required_skills[:3])
    query = f"site:linkedin.com/in {skill_query}"
    if location and location.lower() not in ["remote", "n/a", "", "various"]:
        query += f' "{location}"'

    print(f"  Query: {query}")
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": min(max_results, 10)},
    )
    if resp.status_code != 200:
        print(f"  Error {resp.status_code}: {resp.json().get('error', {}).get('message', '')}")
        return []

    items = resp.json().get("items", [])
    print(f"  Found {len(items)} LinkedIn profiles.")

    candidates = []
    for item in items:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        url = item.get("link", "")
        name = title.split(" - ")[0].strip() if " - " in title else title
        snippet_skills = set(re.split(r"\W+", snippet.lower())) - {""}

        candidates.append({
            "source": "LinkedIn (Google)",
            "username": url.split("/in/")[-1].split("/")[0] if "/in/" in url else name,
            "name": name,
            "location": "",
            "profile_url": url,
            "bio": snippet,
            "skills": snippet_skills,
            "repos": 0,
            "followers": 0,
        })

    return candidates


# ── Scoring ───────────────────────────────────────────────────────────────────
def skill_match(candidate_skills, job_skills):
    matched = []
    for skill in job_skills:
        skill_parts = skill.split()
        if any(
            all(part in cs for part in skill_parts) or skill in cs or cs in skill
            for cs in candidate_skills
        ):
            matched.append(skill)
    return matched


def score_candidates(candidates, required_skills, ideal_skills):
    results = []
    for c in candidates:
        req_matched = skill_match(c["skills"], required_skills)
        ideal_matched = skill_match(c["skills"], ideal_skills)
        req_pct = round(len(req_matched) / len(required_skills) * 100, 1) if required_skills else 0
        ideal_pct = round(len(ideal_matched) / len(ideal_skills) * 100, 1) if ideal_skills else 0

        results.append({
            "Combined Score (%)": round(req_pct * 0.7 + ideal_pct * 0.3, 1),
            "% Required Match": req_pct,
            "% Ideal Match": ideal_pct,
            "Source": c["source"],
            "Name": c["name"],
            "Username": c["username"],
            "Location": c.get("location", ""),
            "Security Clearance": "Unknown",
            "Profile URL": c["profile_url"],
            "Bio / Summary": c.get("bio", ""),
            "Required Skills Matched": ", ".join(req_matched),
            "Ideal Skills Matched": ", ".join(ideal_matched),
            "Public Repos / Reputation": c.get("repos", ""),
            "Followers": c.get("followers", ""),
        })

    return sorted(results, key=lambda x: x["Combined Score (%)"], reverse=True)


# ── Output ────────────────────────────────────────────────────────────────────
def output_excel(results, job_title):
    safe_title = re.sub(r"[^\w\s-]", "", job_title).strip().replace(" ", "_")
    filename = f"candidates_{safe_title}.xlsx"

    df = pd.DataFrame(results)
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Candidates")
        ws = writer.sheets["Candidates"]
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 50)

    print(f"\nSaved: {filename}")
    return filename


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    excel_path = input("Path to job descriptions Excel file: ").strip().strip('"')
    if not Path(excel_path).exists():
        print("File not found.")
        return

    df = load_jobs(excel_path)
    job = select_job(df)
    print(f"\nSelected: {job['job']}")

    required_skills = parse_skills(job.get("required_skills", ""))
    ideal_skills = parse_skills(job.get("ideal_skills", ""))
    location = str(job.get("location", "") or "").strip()

    print(f"\nRequired skills: {', '.join(required_skills)}")
    print(f"Ideal skills:    {', '.join(ideal_skills)}")

    all_candidates = []
    all_candidates.extend(search_github(required_skills, location))
    all_candidates.extend(search_stackoverflow(required_skills))
    all_candidates.extend(search_google_linkedin(required_skills, location))

    if not all_candidates:
        print("\nNo candidates found across any source.")
        return

    print(f"\nTotal candidates: {len(all_candidates)} — scoring and ranking...")
    results = score_candidates(all_candidates, required_skills, ideal_skills)

    print(f"\nTop 5 candidates:")
    for c in results[:5]:
        print(f"  [{c['Source']}] {c['Name'] or c['Username']} — {c['Combined Score (%)']}% match")

    output_excel(results, job["job"])


if __name__ == "__main__":
    main()
