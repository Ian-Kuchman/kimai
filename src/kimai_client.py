"""Kimai REST API client — manages Customers, Projects, and Activities."""

import os
import time
import requests


# Delimiter used when embedding the Notion Page ID in Kimai's comment field.
# Format: "...any human comment... [notion:PAGE-ID]"
NOTION_ID_TAG = "[notion:{id}]"
NOTION_ID_PREFIX = "[notion:"
NOTION_ID_SUFFIX = "]"

# Characters Kimai forbids in name fields
_NAME_FORBIDDEN = str.maketrans({c: "" for c in '<>\\\"='})


def _safe_name(name: str) -> str:
    return name.translate(_NAME_FORBIDDEN).strip()


def _embed_notion_id(comment: str | None, notion_id: str) -> str:
    base = (comment or "").strip()
    tag = NOTION_ID_TAG.format(id=notion_id)
    if tag in base:
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
        # Caches — populated once by load_all(), used for all lookups thereafter
        self._customers: list[dict] = []
        self._projects: list[dict] = []
        self._activities: list[dict] = []

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make a request with exponential backoff retry on connection errors."""
        url = self._url(path)
        delays = [2, 4, 8, 16]
        last_exc: Exception | None = None
        for attempt, delay in enumerate([0] + delays):
            if delay:
                time.sleep(delay)
            try:
                resp = self.session.request(method, url, timeout=30, **kwargs)
                return resp
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_exc = e
                if attempt < len(delays):
                    import logging
                    logging.getLogger(__name__).warning(
                        "Connection error on %s %s (attempt %d), retrying in %ds: %s",
                        method, path, attempt + 1, delays[attempt] if attempt < len(delays) else 0, e,
                    )
        raise last_exc  # type: ignore[misc]

    def _get_all(self, path: str, params: dict | None = None) -> list[dict]:
        """Fetch all pages of a paginated Kimai list endpoint."""
        results = []
        page = 1
        while True:
            p = {"page": page, "size": 250, **(params or {})}
            resp = self._request("GET", path, params=p)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            results.extend(data)
            if len(data) < 250:
                break
            page += 1
        return results

    def load_all(self) -> None:
        """Fetch all existing Kimai data once upfront. All lookups use these caches."""
        import logging
        log = logging.getLogger(__name__)
        log.info("Loading existing Kimai data...")
        self._customers = self._get_all("customers")
        self._projects = self._get_all("projects")
        self._activities = self._get_all("activities")
        log.info(
            "Loaded %d customers, %d projects, %d activities from Kimai",
            len(self._customers), len(self._projects), len(self._activities),
        )

    # ------------------------------------------------------------------ #
    # Customer (= Notion Client)                                           #
    # ------------------------------------------------------------------ #

    def find_customer_by_notion_id(self, notion_id: str) -> dict | None:
        for c in self._customers:
            if _extract_notion_id(c.get("comment")) == notion_id:
                return c
        return None

    def create_customer(self, name: str, notion_id: str) -> dict:
        payload = {
            "name": _safe_name(name),
            "comment": _embed_notion_id(None, notion_id),
            "visible": True,
            "country": "US",
            "currency": "USD",
            "timezone": "America/New_York",
        }
        resp = self._request("POST", "customers", json=payload)
        if not resp.ok:
            raise RuntimeError(f"Kimai create_customer failed {resp.status_code}: {resp.text}")
        created = resp.json()
        self._customers.append(created)
        return created

    def update_customer(self, kimai_id: int, name: str, notion_id: str, existing_comment: str | None = None) -> dict:
        payload = {
            "name": _safe_name(name),
            "comment": _embed_notion_id(existing_comment, notion_id),
        }
        resp = self._request("PATCH", f"customers/{kimai_id}", json=payload)
        resp.raise_for_status()
        updated = resp.json()
        self._customers = [updated if c["id"] == kimai_id else c for c in self._customers]
        return updated

    # ------------------------------------------------------------------ #
    # Project (= Notion Project)                                           #
    # ------------------------------------------------------------------ #

    def find_project_by_notion_id(self, notion_id: str) -> dict | None:
        for p in self._projects:
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
            "name": _safe_name(name),
            "comment": _embed_notion_id(None, notion_id),
            "customer": customer_id,
            "visible": visible,
        }
        if start_date:
            payload["start"] = start_date
        if end_date:
            payload["end"] = end_date
        resp = self._request("POST", "projects", json=payload)
        resp.raise_for_status()
        created = resp.json()
        self._projects.append(created)
        return created

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
            "name": _safe_name(name),
            "comment": _embed_notion_id(existing_comment, notion_id),
            "customer": customer_id,
            "visible": visible,
        }
        if start_date:
            payload["start"] = start_date
        if end_date:
            payload["end"] = end_date
        resp = self._request("PATCH", f"projects/{kimai_id}", json=payload)
        resp.raise_for_status()
        updated = resp.json()
        self._projects = [updated if p["id"] == kimai_id else p for p in self._projects]
        return updated

    # ------------------------------------------------------------------ #
    # Activity (= Notion Task)                                             #
    # ------------------------------------------------------------------ #

    def find_activity_by_notion_id(self, notion_id: str) -> dict | None:
        for a in self._activities:
            if _extract_notion_id(a.get("comment")) == notion_id:
                return a
        return None

    def create_activity(self, name: str, notion_id: str, project_id: int) -> dict:
        payload = {
            "name": _safe_name(name),
            "comment": _embed_notion_id(None, notion_id),
            "project": project_id,
            "visible": True,
        }
        resp = self._request("POST", "activities", json=payload)
        resp.raise_for_status()
        created = resp.json()
        self._activities.append(created)
        return created

    def update_activity(
        self,
        kimai_id: int,
        name: str,
        notion_id: str,
        project_id: int,
        existing_comment: str | None = None,
    ) -> dict:
        payload = {
            "name": _safe_name(name),
            "comment": _embed_notion_id(existing_comment, notion_id),
            "project": project_id,
        }
        resp = self._request("PATCH", f"activities/{kimai_id}", json=payload)
        resp.raise_for_status()
        updated = resp.json()
        self._activities = [updated if a["id"] == kimai_id else a for a in self._activities]
        return updated


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
