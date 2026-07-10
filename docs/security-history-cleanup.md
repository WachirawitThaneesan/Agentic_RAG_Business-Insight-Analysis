# Runbook: Purge secrets from Git history

The following once lived in tracked files and are therefore in the **public**
Git history, even though they are no longer tracked on the current branch:

- `.env` (contained `TYPHOON_API_KEY`, `TAVILY_API_KEY`, DB password)
- `scrape_output/chrome_user_data/` (browser profile: `Login Data`, cookies, `Web Data`)
- `warehouse.duckdb`, `qa_history.json`, assorted debug dumps
- the old Postgres password string in `docker-compose.yml` / `config.py` defaults
  (referred to below as `<OLD_DB_PW>` — substitute your real old value when you run it)

Removing them from the *current* tree does **not** remove them from history. This
runbook rewrites history with [`git-filter-repo`](https://github.com/newren/git-filter-repo).

> ⚠️ **This rewrites every commit hash and requires a force-push.** It is safe for
> this repo because it is solo-owned, but anyone who has cloned it must re-clone
> afterwards. Rewriting history does **not** un-leak already-exposed secrets —
> **rotate the keys regardless** (GitHub, forks, and scrapers may retain copies).

---

## 0. Prerequisites

```bash
pip install git-filter-repo
```

## 1. Back up first (mirror clone)

```bash
cd ..
git clone --mirror https://github.com/WachirawitThaneesan/Agentic_RAG_Business-Insight-Analysis.git backup-before-cleanup.git
cd Project_1
```

## 2. Remove sensitive paths from all history

```bash
git filter-repo --force \
  --path .env \
  --path scrape_output \
  --path warehouse.duckdb \
  --path qa_history.json \
  --invert-paths
```

`--invert-paths` = delete these paths from every commit (keep everything else).

## 3. Redact leaked strings that lived inside kept files

Create `../replace-text.txt`. Use **specific** patterns (include the surrounding
`postgres:` / `PASSWORD:` context) so a bare number that also appears as a year in
the financial data is not clobbered. Substitute `<OLD_DB_PW>` with your real old
password:

```
postgres:<OLD_DB_PW>@==>postgres:***REMOVED***@
PASSWORD: "<OLD_DB_PW>"==>PASSWORD: "***REMOVED***"
```

If an API key was ever hard-coded outside `.env` at some point, add one line per
key value (paste the OLD key you are about to revoke):

```
tk-your-old-typhoon-key-here==>***REMOVED***
tvly-your-old-tavily-key-here==>***REMOVED***
```

Then run:

```bash
git filter-repo --force --replace-text ../replace-text.txt
```

Delete `../replace-text.txt` afterwards (it holds the old keys).

## 4. Re-add the remote and force-push

`git-filter-repo` removes `origin` on purpose. Re-add and push all branches/tags:

```bash
git remote add origin https://github.com/WachirawitThaneesan/Agentic_RAG_Business-Insight-Analysis.git
git push origin --force --all
git push origin --force --tags
```

## 5. After the rewrite (do NOT skip)

1. **Rotate every key anyway** — Typhoon, Tavily, Postgres password. History rewrite
   cannot recall what was already public.
2. If any real account was logged into the scraper Chrome profile, **log it out /
   change that account's password** (cookies allow session hijacking).
3. Old commit SHAs may stay reachable on GitHub for a while and in any forks/caches.
   To purge GitHub's cache, open a request with GitHub Support referencing the SHAs.
4. Tell anyone with an old clone to delete it and re-clone.

## 6. Verify

```bash
git log --all --full-history -- .env scrape_output warehouse.duckdb   # should print nothing
git grep -I "postgres:<OLD_DB_PW>@" $(git rev-list --all) | head      # should print nothing
```
