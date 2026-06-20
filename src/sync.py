"""
Main sync script: Notion → Kimai

Run order: Clients → Projects → Tasks
Each entity type is idempotent — re-running with no Notion changes produces
zero Kimai writes (or harmless identical-value patches).
"""

import os
import sys
import logging
from dotenv import load_dotenv

from notion_client import NotionClient
from kimai_client import KimaiClient, status_to_visible

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger(__name__)


def sync_clients(notion: NotionClient, kimai: KimaiClient, clients_db_id: str) -> dict[str, int]:
    """
    Sync Notion Clients → Kimai Customers.
    Returns mapping: notion_id → kimai_customer_id
    """
    log.info("=== Syncing Clients → Customers ===")
    notion_clients = notion.get_clients(clients_db_id)
    log.info("Found %d Notion clients", len(notion_clients))

    notion_id_to_kimai_id: dict[str, int] = {}

    for client in notion_clients:
        notion_id = client["notion_id"]
        name = client["name"]
        if not name:
            log.warning("Skipping client with empty name (notion_id=%s)", notion_id)
            continue

        existing = kimai.find_customer_by_notion_id(notion_id)
        if existing:
            kimai_id = existing["id"]
            if existing.get("name") != name:
                log.info("Updating customer id=%d name=%r", kimai_id, name)
                kimai.update_customer(kimai_id, name, notion_id, existing.get("comment"))
            else:
                log.debug("Customer id=%d up to date", kimai_id)
        else:
            log.info("Creating customer name=%r", name)
            created = kimai.create_customer(name, notion_id)
            kimai_id = created["id"]

        notion_id_to_kimai_id[notion_id] = kimai_id

    log.info("Clients done. %d mapped.", len(notion_id_to_kimai_id))
    return notion_id_to_kimai_id


def sync_projects(
    notion: NotionClient,
    kimai: KimaiClient,
    projects_db_id: str,
    customer_map: dict[str, int],
) -> dict[str, int]:
    """
    Sync Notion Projects → Kimai Projects.
    Returns mapping: notion_id → kimai_project_id
    """
    log.info("=== Syncing Projects ===")
    notion_projects = notion.get_projects(projects_db_id)
    log.info("Found %d Notion projects", len(notion_projects))

    notion_id_to_kimai_id: dict[str, int] = {}

    for project in notion_projects:
        notion_id = project["notion_id"]
        name = project["name"]
        if not name:
            log.warning("Skipping project with empty name (notion_id=%s)", notion_id)
            continue

        # Resolve customer
        client_notion_ids = project.get("client_notion_ids", [])
        customer_id: int | None = None
        for cid in client_notion_ids:
            if cid in customer_map:
                customer_id = customer_map[cid]
                break

        if customer_id is None:
            log.warning(
                "Project %r (notion_id=%s) has no resolvable customer — skipping",
                name,
                notion_id,
            )
            continue

        visible = status_to_visible(project.get("status"))
        start_date = project.get("start_date")
        end_date = project.get("end_date")

        existing = kimai.find_project_by_notion_id(notion_id)
        if existing:
            kimai_id = existing["id"]
            needs_update = (
                existing.get("name") != name
                or existing.get("customer", {}).get("id") != customer_id
                or existing.get("visible") != visible
                or existing.get("start") != start_date
                or existing.get("end") != end_date
            )
            if needs_update:
                log.info("Updating project id=%d name=%r", kimai_id, name)
                kimai.update_project(
                    kimai_id,
                    name,
                    notion_id,
                    customer_id,
                    start_date=start_date,
                    end_date=end_date,
                    visible=visible,
                    existing_comment=existing.get("comment"),
                )
            else:
                log.debug("Project id=%d up to date", kimai_id)
        else:
            log.info("Creating project name=%r", name)
            created = kimai.create_project(
                name,
                notion_id,
                customer_id,
                start_date=start_date,
                end_date=end_date,
                visible=visible,
            )
            kimai_id = created["id"]

        notion_id_to_kimai_id[notion_id] = kimai_id

    log.info("Projects done. %d mapped.", len(notion_id_to_kimai_id))
    return notion_id_to_kimai_id


def sync_tasks(
    notion: NotionClient,
    kimai: KimaiClient,
    tasks_db_id: str,
    project_map: dict[str, int],
) -> None:
    """Sync Notion Tasks → Kimai Activities (project-scoped)."""
    log.info("=== Syncing Tasks → Activities ===")
    notion_tasks = notion.get_tasks(tasks_db_id)
    log.info("Found %d Notion tasks", len(notion_tasks))

    created = updated = skipped = 0

    for task in notion_tasks:
        notion_id = task["notion_id"]
        name = task["name"]
        if not name:
            log.warning("Skipping task with empty name (notion_id=%s)", notion_id)
            skipped += 1
            continue

        project_notion_ids = task.get("project_notion_ids", [])
        project_id: int | None = None
        for pid in project_notion_ids:
            if pid in project_map:
                project_id = project_map[pid]
                break

        if project_id is None:
            log.warning(
                "Task %r (notion_id=%s) has no resolvable project — skipping",
                name,
                notion_id,
            )
            skipped += 1
            continue

        existing = kimai.find_activity_by_notion_id(notion_id)
        if existing:
            kimai_id = existing["id"]
            needs_update = (
                existing.get("name") != name
                or (existing.get("project") or {}).get("id") != project_id
            )
            if needs_update:
                log.info("Updating activity id=%d name=%r", kimai_id, name)
                kimai.update_activity(
                    kimai_id,
                    name,
                    notion_id,
                    project_id,
                    existing_comment=existing.get("comment"),
                )
                updated += 1
            else:
                log.debug("Activity id=%d up to date", kimai_id)
        else:
            log.info("Creating activity name=%r under project_id=%d", name, project_id)
            kimai.create_activity(name, notion_id, project_id)
            created += 1

    log.info("Tasks done. created=%d updated=%d skipped=%d", created, updated, skipped)


def main() -> None:
    required = [
        "NOTION_TOKEN",
        "NOTION_CLIENTS_DB_ID",
        "NOTION_PROJECTS_DB_ID",
        "NOTION_TASKS_DB_ID",
        "KIMAI_BASE_URL",
        "KIMAI_API_TOKEN",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        log.error("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)

    notion = NotionClient()
    kimai = KimaiClient()
    kimai.load_all()

    clients_db_id = os.environ["NOTION_CLIENTS_DB_ID"]
    projects_db_id = os.environ["NOTION_PROJECTS_DB_ID"]
    tasks_db_id = os.environ["NOTION_TASKS_DB_ID"]

    customer_map = sync_clients(notion, kimai, clients_db_id)
    project_map = sync_projects(notion, kimai, projects_db_id, customer_map)
    sync_tasks(notion, kimai, tasks_db_id, project_map)

    log.info("Sync complete.")


if __name__ == "__main__":
    main()
