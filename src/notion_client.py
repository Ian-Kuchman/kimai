"""Notion API client — reads Clients, Projects, and Tasks databases."""

import os
import requests


NOTION_VERSION = "2022-06-28"


class NotionClient:
    def __init__(self, token: str | None = None):
        self.token = token or os.environ["NOTION_TOKEN"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def _query_database(self, database_id: str) -> list[dict]:
        """Return all pages from a database, handling pagination."""
        pages = []
        cursor = None
        url = f"https://api.notion.com/v1/databases/{database_id}/query"
        while True:
            body = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            resp = self.session.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
            pages.extend(data["results"])
            if not data.get("has_more"):
                break
            cursor = data["next_cursor"]
        return pages

    def _title(self, props: dict, key: str) -> str:
        items = props.get(key, {}).get("title", [])
        return "".join(t.get("plain_text", "") for t in items).strip()

    def _rich_text(self, props: dict, key: str) -> str:
        items = props.get(key, {}).get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in items).strip()

    def _date(self, props: dict, key: str, part: str = "start") -> str | None:
        d = props.get(key, {}).get("date")
        return d.get(part) if d else None

    def _select(self, props: dict, key: str) -> str | None:
        s = props.get(key, {}).get("select")
        return s.get("name") if s else None

    def _relation_ids(self, props: dict, key: str) -> list[str]:
        return [r["id"] for r in props.get(key, {}).get("relation", [])]

    # ------------------------------------------------------------------ #
    # Public methods                                                        #
    # ------------------------------------------------------------------ #

    def get_clients(self, database_id: str) -> list[dict]:
        """
        Returns list of dicts:
          {notion_id, name}
        """
        pages = self._query_database(database_id)
        clients = []
        for p in pages:
            props = p["properties"]
            # Notion title property key is typically "Name" but may vary;
            # find the property with type "title" dynamically.
            name = ""
            for v in props.values():
                if v.get("type") == "title":
                    name = "".join(t.get("plain_text", "") for t in v["title"]).strip()
                    break
            clients.append({"notion_id": p["id"], "name": name})
        return clients

    def _status(self, props: dict, key: str) -> str | None:
        """Read a Notion status property (different type from select)."""
        s = props.get(key, {}).get("status")
        return s.get("name") if s else None

    def get_projects(self, database_id: str) -> list[dict]:
        """
        Returns list of dicts:
          {notion_id, name, client_notion_ids, start_date, end_date, status}

        Confirmed property names (from live Notion schema):
          title        → "Project Name"
          client rel   → "🌆 Client"
          date range   → "Date" (start + end)
          status       → "Status" (status type, not select)
        """
        pages = self._query_database(database_id)
        projects = []
        for p in pages:
            props = p["properties"]
            name = self._title(props, "Project Name")
            client_ids = self._relation_ids(props, "🌆 Client")
            start_date = self._date(props, "Date", "start")
            end_date = self._date(props, "Date", "end")
            status = self._status(props, "Status")
            projects.append(
                {
                    "notion_id": p["id"],
                    "name": name,
                    "client_notion_ids": client_ids,
                    "start_date": start_date,
                    "end_date": end_date,
                    "status": status,
                }
            )
        return projects

    def get_tasks(self, database_id: str) -> list[dict]:
        """
        Returns list of dicts:
          {notion_id, name, project_notion_ids}
        Status is intentionally omitted — all milestones sync regardless.

        Confirmed property names (from live Notion schema, Milestones DB):
          title       → "Task name"
          project rel → "Projects"
        """
        pages = self._query_database(database_id)
        tasks = []
        for p in pages:
            props = p["properties"]
            name = self._title(props, "Task name")
            project_ids = self._relation_ids(props, "Projects")
            tasks.append(
                {
                    "notion_id": p["id"],
                    "name": name,
                    "project_notion_ids": project_ids,
                }
            )
        return tasks
