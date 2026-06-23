import time
import re
import json
import argparse
import requests
import pandas as pd
from pathlib import Path


# ── GitHub ────────────────────────────────────────────────────────────────────

def _clean_query_term(s):
    return re.sub(r"[^\w\s]", "", s).strip()


def search_github(skills, github_token="", max_results=30):
    headers = {"Authorization": f"token {github_token}"} if github_token else {}

    # Clean each skill and drop empty terms to avoid 422
    clean_skills = [_clean_query_term(s) for s in skills[:5]]
    clean_skills = [s for s in clean_skills if s]
    if not clean_skills:
        return [], "No valid search terms after cleaning skill names."

    query = " ".join(clean_skills)
    params = {"q": query, "per_page": min(max_results, 30), "sort": "repositories"}

    resp = requests.get("https://api.github.com/search/users", headers=headers, params=params)
    if resp.status_code == 403:
        return [], "GitHub rate limit hit — add a token for higher limits."
    if resp.status_code == 422:
        return [], f"GitHub rejected the query '{query}' — try simpler skill names."
    if resp.status_code != 200:
        return [], f"GitHub error {resp.status_code}: {resp.json().get('message', '')}"

    candidates = []
    for user in resp.json().get("items", []):
        username = user["login"]

        profile_resp = requests.get(f"https://api.github.com/users/{username}", headers=headers)
        profile = profile_resp.json() if profile_resp.status_code == 200 else {}

        repos_resp = requests.get(
            f"https://api.github.com/users/{username}/repos",
            headers=headers,
            params={"per_page": 30, "sort": "updated"},
        )
        skill_set = set()
        if repos_resp.status_code == 200:
            for repo in repos_resp.json()[:15]:
                if repo.get("language"):
                    skill_set.add(repo["language"])
                for topic in repo.get("topics", []):
                    skill_set.add(topic)
        bio = str(profile.get("bio") or "")
        for word in re.split(r"\W+", bio.lower()):
            if len(word) > 2:
                skill_set.add(word)

        candidates.append({
            "name": profile.get("name") or username,
            "skills": ", ".join(skill_set),
            "source": "GitHub",
            "profile_url": f"https://github.com/{username}",
            "location": profile.get("location", ""),
        })
        time.sleep(0.15)

    return candidates, None


# ── Stack Overflow ────────────────────────────────────────────────────────────

def _skill_to_so_tag(skill):
    # Normalize to Stack Overflow tag format
    tag = skill.lower().strip()
    tag = re.sub(r"[^\w\s\+\#]", "", tag)
    tag = re.sub(r"\s+", "-", tag)
    return tag


def search_stackoverflow(skills, max_results=30):
    user_skills = {}
    errors = []

    for skill in skills[:5]:
        tag = _skill_to_so_tag(skill)
        url = f"https://api.stackexchange.com/2.3/tags/{tag}/top-answerers/all_time"
        params = {"site": "stackoverflow", "pagesize": min(max_results, 30)}

        resp = requests.get(url, params=params)
        data = resp.json()

        if resp.status_code != 200 or not data.get("items"):
            # Tag not found — try searching for the closest tag first
            search_resp = requests.get(
                "https://api.stackexchange.com/2.3/tags",
                params={"site": "stackoverflow", "inname": tag, "pagesize": 1, "order": "desc", "sort": "popular"},
            )
            if search_resp.status_code == 200:
                found = search_resp.json().get("items", [])
                if found:
                    tag = found[0]["name"]
                    resp = requests.get(
                        f"https://api.stackexchange.com/2.3/tags/{tag}/top-answerers/all_time",
                        params={"site": "stackoverflow", "pagesize": min(max_results, 30)},
                    )
                    data = resp.json()
                else:
                    errors.append(skill)
                    continue
            time.sleep(0.2)

        for item in data.get("items", []):
            uid = item["user"]["user_id"]
            if uid not in user_skills:
                user_skills[uid] = {
                    "name": item["user"].get("display_name", ""),
                    "profile_url": item["user"].get("link", ""),
                    "location": item["user"].get("location", ""),
                    "matched_skills": set(),
                }
            user_skills[uid]["matched_skills"].add(skill)

        time.sleep(0.2)

    candidates = []
    for uid, data in user_skills.items():
        candidates.append({
            "name": data["name"],
            "skills": ", ".join(data["matched_skills"]),
            "source": "Stack Overflow",
            "profile_url": data["profile_url"],
            "location": data["location"],
        })

    warning = f"No Stack Overflow tag found for: {', '.join(errors)}" if errors else None
    return candidates, warning


# ── Google → LinkedIn ─────────────────────────────────────────────────────────

def search_google_linkedin(skills, api_key, cx, max_results=10):
    if not api_key or not cx:
        return [], "Google API key and Custom Search Engine ID are required."

    query = " ".join(skills[:4]) + " site:linkedin.com/in/"
    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": min(max_results, 10),
    }

    resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params)
    if resp.status_code == 429:
        return [], "Google daily search quota reached (100/day free limit)."
    if resp.status_code != 200:
        return [], f"Google search error: {resp.status_code}"

    candidates = []
    for item in resp.json().get("items", []):
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        name = title.split(" - ")[0].strip() if " - " in title else title
        skill_words = [w for w in re.split(r"\W+", snippet.lower()) if len(w) > 2]

        candidates.append({
            "name": name,
            "skills": snippet,
            "source": "LinkedIn (Google)",
            "profile_url": item.get("link", ""),
            "location": "",
        })

    return candidates, None


# ── Merge results ─────────────────────────────────────────────────────────────

def build_candidates_df(sourced_lists):
    all_candidates = []
    for candidates in sourced_lists:
        all_candidates.extend(candidates)

    if not all_candidates:
        return pd.DataFrame()

    df = pd.DataFrame(all_candidates)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df.drop_duplicates(subset=["name", "source"]).reset_index(drop=True)


# ── CLI entry point (called by the Claude skill) ──────────────────────────────

def extract_keywords_from_jd(jd_text):
    # Pull meaningful words from the JD as search terms — Claude will do deeper inference later
    stopwords = {
        "the", "and", "for", "with", "will", "have", "this", "that", "are", "you",
        "our", "your", "from", "about", "they", "their", "experience", "ability",
        "strong", "work", "team", "role", "must", "also", "well", "good", "using",
        "we", "a", "an", "in", "to", "of", "or", "is", "be", "as", "at", "on",
    }
    words = re.findall(r"\b[a-zA-Z][a-zA-Z0-9\+\#\.]{2,}\b", jd_text)
    seen, keywords = set(), []
    for w in words:
        lw = w.lower()
        if lw not in stopwords and lw not in seen:
            seen.add(lw)
            keywords.append(w)
    return keywords[:10]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--jd", default="", help="Full job description text")
    parser.add_argument("--jd-from-config", action="store_true", help="Load JD from dashboard config.json")
    parser.add_argument("--github-token", default="", help="GitHub personal access token")
    parser.add_argument("--max-results", type=int, default=20)
    args = parser.parse_args()

    config_path = Path(__file__).parent / "config.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}

    if args.jd_from_config:
        jd_text = config.get("job_description", "")
        if not jd_text:
            print("ERROR: No job description found in config.json. Please paste it into the dashboard first.")
            exit(1)
    else:
        jd_text = args.jd
        if not jd_text:
            print("ERROR: Provide --jd or --jd-from-config.")
            exit(1)

    github_token = args.github_token or config.get("github_token", "")
    keywords = extract_keywords_from_jd(jd_text)
    print(f"Extracted search terms: {keywords}")

    all_candidates = []

    print("Searching GitHub...")
    gh_results, gh_err = search_github(keywords, github_token, args.max_results)
    if gh_err:
        print(f"GitHub warning: {gh_err}")
    else:
        print(f"GitHub: {len(gh_results)} candidates found")
        all_candidates.extend(gh_results)

    print("Searching Stack Overflow...")
    so_results, so_err = search_stackoverflow(keywords, args.max_results)
    if so_err:
        print(f"Stack Overflow warning: {so_err}")
    else:
        print(f"Stack Overflow: {len(so_results)} candidates found")
        all_candidates.extend(so_results)

    # Deduplicate
    seen_keys = set()
    unique = []
    for c in all_candidates:
        key = (c.get("name", "").lower(), c.get("source", ""))
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(c)

    output_path = Path(__file__).parent / "sourced_candidates.json"
    with open(output_path, "w") as f:
        json.dump({"job_description": jd_text, "candidates": unique}, f, indent=2)

    print(f"\nSaved {len(unique)} candidates to {output_path}")
