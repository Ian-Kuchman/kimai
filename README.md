# Kimai ↔ Notion Sync

One-way sync: **Notion is the source of truth.** Clients, Projects, and Tasks are pulled from Notion and pushed into Kimai as Customers, Projects, and Activities. Kimai is never written back to Notion.

## How it works

- Notion Page IDs are stored in each Kimai record's `comment` field as `[notion:PAGE-ID]`.
- On each run the script looks up the Kimai record by that tag, updates fields that changed, or creates a new record if none exists.
- Deletions in Notion are ignored — historical time entries are never affected.
- Re-running with no Notion changes produces zero Kimai writes.

Run order: **Clients → Projects → Tasks**

## Setup

### 1. Secrets

Add the following to your GitHub repo's **Settings → Secrets → Actions**:

| Secret | Description |
|---|---|
| `NOTION_TOKEN` | Notion internal integration token |
| `NOTION_CLIENTS_DB_ID` | ID of the Clients database in Notion |
| `NOTION_PROJECTS_DB_ID` | ID of the Projects database in Notion |
| `NOTION_TASKS_DB_ID` | ID of the Tasks database in Notion |
| `KIMAI_BASE_URL` | e.g. `https://kimai.example.com` |
| `KIMAI_API_TOKEN` | Kimai API token (user profile → API access) |

### 2. Local testing

```bash
cp .env.example .env
# Fill in .env values
pip install -r requirements.txt
cd src && python sync.py
```

### 3. Schedule

The sync runs nightly at 2 AM UTC via GitHub Actions. Trigger it manually from the **Actions** tab → **Kimai ↔ Notion Sync** → **Run workflow**.

## Configuration to confirm before first run

1. **Notion property names** — The script tries common variants (`Client`/`Clients`, `Start Date`/`Start date`, etc.). If your database uses different names, update `notion_client.py`.
2. **Status → active/inactive mapping** — Edit `INACTIVE_STATUSES` in `kimai_client.py` to match the exact status option names used in your Notion Projects database.
3. **Kimai currency/country/timezone** — Defaults in `create_customer()` are `USD / US / America/New_York`. Adjust if needed.

## Files

```
src/
  notion_client.py   — Notion API reads
  kimai_client.py    — Kimai API reads/writes + Notion-ID embedding
  sync.py            — Orchestration: clients → projects → tasks
.github/workflows/sync.yml
requirements.txt
.env.example
```
