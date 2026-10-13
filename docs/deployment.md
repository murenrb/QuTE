# Deployment (Streamlit Community Cloud + hosted Postgres)

The public app is one link, e.g. `https://<subdomain>.streamlit.app`. Anyone
with it can open, change and create projects: **everything is public**, with
no accounts (owner, D-069). To use the app privately, fork the repository and
run your own copy.

The code is **MIT licensed** (`LICENSE`, D-070): anyone may use, change,
and redistribute it, including in closed / commercial versions, as long as
they keep the copyright and licence notice. Nobody can change this repo
without being a collaborator; others fork it or open pull requests.

Each project also has its own link, `…/workspace?project=<id>` (project bar →
**Link**).

## Pieces

| Piece | What | Where it is set |
|---|---|---|
| App | this repo, `streamlit_app.py`, branch `main` | share.streamlit.io |
| Python | 3.13 exactly: PySAM has no 3.14 wheels; the version can't be changed later (delete and redeploy) | Community Cloud → app → Advanced settings (chosen at deploy) |
| Packages | `uv.lock` / `requirements.txt` (`uv export …`, CLAUDE.md) | the repo |
| Database | hosted Postgres (Neon free tier recommended) | `DATABASE_URL` secret |
| Weather | NSRDB key + email | `NSRDB_API_KEY`, `NSRDB_EMAIL` secrets |

Locally nothing changes: with no `DATABASE_URL` the app uses
`data/dcs.sqlite`.

## One-time setup

1. **Database (Neon).** Sign up at neon.com → create a project (pick the
   region closest to Streamlit Cloud's servers, US East). Copy the
   connection string ("Connect" → Postgres URL, with
   `?sslmode=require`). The app creates its tables on first start.
   Free tier: 0.5 GB (one project with its snapshots is about 10–20 kB). The
   database sleeps when idle and wakes on the first query.
2. **Copy local projects into it (optional).** In this folder:
   `DATABASE_URL="<connection string>" python -m services.import_files`
   (projects already there are skipped). Your local SQLite database is not
   copied; the importer reads the old JSON files under `data/projects/`.
3. **Push** the code to GitHub `main`.
4. **Deploy.** share.streamlit.io → sign in with GitHub → Create app →
   repo `murenrb/QuTE`, branch `main`, main file
   `streamlit_app.py` → Advanced settings: Python 3.13, and paste the
   secrets:
   ```toml
   NSRDB_API_KEY = "…"
   NSRDB_EMAIL = "…"
   DATABASE_URL = "postgresql://…?sslmode=require"
   ```
   Pick a custom subdomain (that is the shared link).
5. **Make it public.** App settings → Sharing → anyone can view. A private
   GitHub repo can still serve a public app; for "fork it to use it
   privately" the repo must be public too (GitHub → Settings → Danger zone →
   Change visibility). Check its history for anything that must not be
   public first: `.streamlit/secrets.toml` was never committed.

Each push to `main` redeploys the app.

## Behaviour to know
- **Shared NSRDB key:** every visitor's weather downloads count against the
  key in the secrets.
- **Weather cache:** on Community Cloud's disk, so it is lost when the app
  restarts (re-fetched on demand).
- **Sleep:** Community Cloud puts an app with no visitors to sleep; the next
  visitor wakes it (takes about a minute).
- **Two people on one project:** last write wins; the overwritten state is
  kept in Versions → Automatic snapshots, and the one who overwrote it sees a
  notice (data-model.md → Database).
- Community Cloud gives an app limited memory; each open session holds its
  own 8760-hour results.
