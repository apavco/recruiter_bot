import time
import re
import requests
import pandas as pd


# ── GitHub ────────────────────────────────────────────────────────────────────

def search_github(skills, github_token="", max_results=30):
    headers = {"Authorization": f"token {github_token}"} if github_token else {}
    query = " ".join(skills[:5])
    params = {"q": query, "per_page": min(max_results, 30), "sort": "repositories"}

    resp = requests.get("https://api.github.com/search/users", headers=headers, params=params)
    if resp.status_code == 403:
        return [], "GitHub rate limit hit — add a token for higher limits."
    if resp.status_code != 200:
        return [], f"GitHub error: {resp.status_code}"

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

def search_stackoverflow(skills, max_results=30):
    user_skills = {}

    for skill in skills[:5]:
        tag = skill.lower().replace(" ", "-").replace(".", "-")
        url = f"https://api.stackexchange.com/2.3/tags/{tag}/top-answerers/all_time"
        params = {"site": "stackoverflow", "pagesize": min(max_results, 30)}

        resp = requests.get(url, params=params)
        if resp.status_code != 200:
            continue

        for item in resp.json().get("items", []):
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

    return candidates, None


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
