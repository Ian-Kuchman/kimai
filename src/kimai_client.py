"""Kimai REST API client — manages Customers, Projects, and Activities."""

import os
import requests


# Delimiter used when embedding the Notion Page ID in Kimai's comment field.
# Format: "...any human comment... [notion:PAGE-ID]"
NOTION_ID_TAG = "[notion:{id}]"
NOTION_ID_PREFIX = "[notion:"
NOTION_ID_SUFFIX = "]"


def _embed_notion_id(comment: str | None, notion_id: str) -> str:
    base = (comment or "").strip()
    tag = NOTION_ID_TAG.format(id=notion_id)
    if tag in (base or ""):
        return base
    return f"{base} {tag}".strip()


def _extract_notion_id(comment: str | None) -> str | None:
    if not comment:
        return None
    start = comment.find(NOTION_ID_PREFIX)
    if start == -1:
        return None
    end = comment.find(NOTION_ID_SUFFIX, start + len(NOTION_ID_PREFIX))
    if end == -1:
        return None
    return comment[start + len(NOTION_ID_PREFIX) : end]


class KimaiClient:
    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ["KIMAI_BASE_URL"]).rstrip("/")
        self.token = token or os.environ["KIMAI_API_TOKEN"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            }
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        """Fetch all pages of a paginated Kimai list endpoint."""
        results = []
        page = 1
        while True:
            p = {"page": page, "size": 250, **(params or {})}
            resp = self.session.get(self._url(path), params=p)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            results.extend(data)
            if len(data) < 250:
                break
            page += 1
        return results

    # ------------------------------------------------------------------ #
    # Customer (= Notion Client)                                           #
    # ------------------------------------------------------------------ #

    def get_customers(self) -> list[dict]:
        return self._get_all("customers")

    def find_customer_by_notion_id(self, notion_id: str) -> dict | None:
        for c in self.get_customers():
            if _extract_notion_id(c.get("comment")) == notion_id:
                return c
        return None

    def create_customer(self, name: str, notion_id: str) -> dict:
        payload = {
            "name": name,
            "comment": _embed_notion_id(None, notion_id),
            "visible": True,
            "currency": "USD",
            "country": "US",
            "timezone": "America/New_York",
        }
        resp = self.session.post(self._url("customers"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def update_customer(self, kimai_id: int, name: str, notion_id: str, existing_comment: str | None = None) -> dict:
        payload = {
            "name": name,
            "comment": _embed_notion_id(existing_comment, notion_id),
        }
        resp = self.session.patch(self._url(f"customers/{kimai_id}"), json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Project (= Notion Project)                                           #
    # ------------------------------------------------------------------ #

    def get_projects(self) -> list[dict]:
        return self._get_all("projects")

    def find_project_by_notion_id(self, notion_id: str) -> dict | None:
        for p in self.get_projects():
            if _extract_notion_id(p.get("comment")) == notion_id:
                return p
        return None

    def create_project(
        self,
        name: str,
        notion_id: str,
        customer_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        visible: bool = True,
    ) -> dict:
        payload = {
            "name": name,
            "comment": _embed_notion_id(None, notion_id),
            "customer": customer_id,
            "visible": visible,
        }
        if start_date:
            payload["start"] = start_date
        if end_date:
            payload["end"] = end_date
        resp = self.session.post(self._url("projects"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def update_project(
        self,
        kimai_id: int,
        name: str,
        notion_id: str,
        customer_id: int,
        start_date: str | None = None,
        end_date: str | None = None,
        visible: bool = True,
        existing_comment: str | None = None,
    ) -> dict:
        payload = {
            "name": name,
            "comment": _embed_notion_id(existing_comment, notion_id),
            "customer": customer_id,
            "visible": visible,
        }
        if start_date:
            payload["start"] = start_date
        if end_date:
            payload["end"] = end_date
        resp = self.session.patch(self._url(f"projects/{kimai_id}"), json=payload)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------ #
    # Activity (= Notion Task)                                             #
    # ------------------------------------------------------------------ #

    def get_activities(self, project_id: int | None = None) -> list[dict]:
        params: dict = {}
        if project_id is not None:
            params["project"] = project_id
        return self._get_all("activities", params or None)

    def find_activity_by_notion_id(self, notion_id: str, project_id: int | None = None) -> dict | None:
        for a in self.get_activities(project_id=project_id):
            if _extract_notion_id(a.get("comment")) == notion_id:
                return a
        return None

    def create_activity(self, name: str, notion_id: str, project_id: int) -> dict:
        payload = {
            "name": name,
            "comment": _embed_notion_id(None, notion_id),
            "project": project_id,
            "visible": True,
        }
        resp = self.session.post(self._url("activities"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def update_activity(
        self,
        kimai_id: int,
        name: str,
        notion_id: str,
        project_id: int,
        existing_comment: str | None = None,
    ) -> dict:
        payload = {
            "name": name,
            "comment": _embed_notion_id(existing_comment, notion_id),
            "project": project_id,
        }
        resp = self.session.patch(self._url(f"activities/{kimai_id}"), json=payload)
        resp.raise_for_status()
        return resp.json()


# ------------------------------------------------------------------ #
# Status mapping: Notion → Kimai visible flag                         #
# ------------------------------------------------------------------ #

# Confirmed from live Notion Projects DB schema.
# Any status not in this set is treated as active (visible=True).
INACTIVE_STATUSES = {"Done", "Canceled"}


def status_to_visible(notion_status: str | None) -> bool:
    if notion_status is None:
        return True
    return notion_status not in INACTIVE_STATUSES
