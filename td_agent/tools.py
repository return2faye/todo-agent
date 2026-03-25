import os
import subprocess
from datetime import datetime
from notion_client import Client
from langchain_core.tools import tool

# Pin to a stable Notion API version to avoid unexpected endpoint/schema changes.
# (notion-client v3 defaults to a very new date, which may cause 400s for some endpoints.)
notion = Client(
    auth=os.environ["NOTION_API_KEY"],
    notion_version="2022-06-28",
)
DATABASE_ID = os.environ["NOTION_DATABASE_ID"]


# ── Utility ─────────────────────────────────────────────────────────────────

def _priority_order(p: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(p, 4)


# ── Time ─────────────────────────────────────────────────────────────────────

@tool
def get_current_datetime() -> str:
    """Get the current date and time as an ISO string.
    Always call this first before any deadline reasoning."""
    return datetime.now().isoformat()


# ── Notion: read ─────────────────────────────────────────────────────────────

@tool
def get_all_tasks() -> str:
    """Fetch all pending tasks (status: todo or in_progress) from Notion.
    Returns a JSON-like string with id, title, deadline, priority,
    urgency_score, depends_on, and notes for each task."""
    # notion-client v3.0.0 does not expose `databases.query()`.
    # Use the underlying Notion API endpoint:
    # POST /v1/databases/{database_id}/query
    tasks: list[dict] = []
    start_cursor: str | None = None
    allowed_statuses = {"todo", "in_progress"}

    while True:
        body: dict = {
            "page_size": 100,
        }
        if start_cursor:
            body["start_cursor"] = start_cursor

        try:
            response = notion.request(
                path=f"databases/{DATABASE_ID}/query",
                method="POST",
                body=body,
            )
        except Exception as e:
            # Surface Notion error details to help debugging quickly.
            raw_body = getattr(e, "body", None)
            if isinstance(raw_body, str) and len(raw_body) > 500:
                raw_body = raw_body[:500] + "..."
            return (
                "Notion query failed.\n"
                f"type={type(e).__name__}\n"
                f"error={str(e)}\n"
                f"code={getattr(e, 'code', None)}\n"
                f"status={getattr(e, 'status', None)}\n"
                f"body={raw_body}"
            )

        for page in response.get("results", []):
            props = page["properties"]

            title_parts = props.get("Name", {}).get("title", [])
            title = title_parts[0]["plain_text"] if title_parts else "Untitled"

            deadline_obj = props.get("Deadline", {}).get("date")
            deadline = deadline_obj["start"] if deadline_obj else None

            priority_obj = props.get("Priority", {}).get("select")
            priority = priority_obj["name"] if priority_obj else "medium"

            score_obj = props.get("Urgency Score", {}).get("number")
            score = score_obj if score_obj is not None else 0

            depends_parts = props.get("Depends On", {}).get("rich_text", [])
            depends_on = (
                depends_parts[0]["plain_text"] if depends_parts else ""
            )

            notes_parts = props.get("Notes", {}).get("rich_text", [])
            notes = notes_parts[0]["plain_text"] if notes_parts else ""

            status_obj = props.get("Status", {}).get("select")
            status = None
            # Status may be configured as "select" or "status" depending on your Notion DB.
            if status_obj:
                status = status_obj.get("name")
            if not status:
                status_obj = props.get("Status", {}).get("status")
                status = status_obj.get("name") if status_obj else None
            if not status:
                ms = props.get("Status", {}).get("multi_select")
                if ms and isinstance(ms, list) and ms:
                    # If multi-select is used, pick the first matching status.
                    status = next(
                        (x.get("name") for x in ms if x.get("name") in allowed_statuses),
                        None,
                    )

            if status not in allowed_statuses:
                continue

            tasks.append(
                {
                    "id": page["id"],
                    "title": title,
                    "deadline": deadline,
                    "priority": priority,
                    "urgency_score": score,
                    "depends_on": depends_on,
                    "notes": notes,
                    "status": status,
                }
            )
        if not response.get("has_more"):
            break
        start_cursor = response.get("next_cursor")
        if not start_cursor:
            break

    if not tasks:
        return "No pending tasks found."

    lines = [f"Found {len(tasks)} pending task(s):\n"]
    for t in tasks:
        lines.append(
            f"  id={t['id']}\n"
            f"  title={t['title']}\n"
            f"  deadline={t['deadline'] or 'none'}\n"
            f"  priority={t['priority']}\n"
            f"  urgency_score={t['urgency_score']}\n"
            f"  depends_on={t['depends_on'] or 'none'}\n"
            f"  status={t['status']}\n"
            f"  notes={t['notes'] or 'none'}\n"
        )
    return "\n".join(lines)


# ── Notion: write ────────────────────────────────────────────────────────────

@tool
def add_task_to_notion(
    title: str,
    priority: str,
    deadline: str = "",
    depends_on: str = "",
    notes: str = "",
) -> str:
    """Add a new task to the Notion database.

    Args:
        title: Short task description.
        priority: One of 'critical', 'high', 'medium', 'low'.
        deadline: ISO date string like '2026-03-28'. Leave empty if none.
        depends_on: Title(s) of tasks that must be completed first.
        notes: Any extra context.
    """
    props: dict = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Status": {"select": {"name": "todo"}},
        "Priority": {"select": {"name": priority}},
    }
    if deadline:
        props["Deadline"] = {"date": {"start": deadline}}
    if depends_on:
        props["Depends On"] = {"rich_text": [{"text": {"content": depends_on}}]}
    if notes:
        props["Notes"] = {"rich_text": [{"text": {"content": notes}}]}

    notion.pages.create(parent={"database_id": DATABASE_ID}, properties=props)
    return f"Task added to Notion: '{title}' [{priority}]" + (
        f" due {deadline}" if deadline else ""
    )


@tool
def update_urgency_score(task_id: str, score: int) -> str:
    """Update the urgency score of a task in Notion.

    Args:
        task_id: The Notion page ID of the task.
        score: Integer 0-100. Higher means more urgent.
    """
    notion.pages.update(
        page_id=task_id,
        properties={"Urgency Score": {"number": score}},
    )
    return f"Updated urgency score to {score} for task {task_id}"


@tool
def complete_task_in_notion(task_id: str) -> str:
    """Mark a task as done in Notion by its page ID.

    Args:
        task_id: The Notion page ID of the task to complete.
    """
    notion.pages.update(
        page_id=task_id,
        properties={"Status": {"select": {"name": "done"}}},
    )
    return f"Task {task_id} marked as done in Notion."


@tool
def update_task_in_notion(
    task_id: str,
    title: str = "",
    deadline: str = "",
    priority: str = "",
    status: str = "",
) -> str:
    """Update fields of a task in Notion by its page ID.

    Empty strings mean "leave unchanged".

    Args:
        task_id: The Notion page ID of the task to update.
        title: Update the task title (Name property).
        deadline: Update the Deadline property using ISO date string (e.g. 2026-03-28).
        priority: Update the Priority property. One of critical/high/medium/low.
        status: Update the Status property. One of todo/in_progress/done.
    """
    props: dict = {}

    if title:
        props["Name"] = {"title": [{"text": {"content": title}}]}
    if deadline:
        props["Deadline"] = {"date": {"start": deadline}}
    if priority:
        props["Priority"] = {"select": {"name": priority}}
    if status:
        props["Status"] = {"select": {"name": status}}

    if not props:
        return f"No fields to update for task {task_id}."

    notion.pages.update(page_id=task_id, properties=props)
    return f"Task {task_id} updated."


# ── Pipeline reasoning ───────────────────────────────────────────────────────

@tool
def compute_pipeline(tasks_json: str, current_datetime: str) -> str:
    """Given the raw task list and current datetime, reason about urgency and
    produce a ranked execution pipeline with explanations.

    This tool is a reasoning prompt — you (the LLM) should:
    1. Parse each task's deadline relative to current_datetime.
    2. Score urgency: deadline proximity + dependency chain + explicit signals.
    3. Return tasks ordered from most to least urgent, each with a 1-line reason.
    4. Flag any tasks that are blocked (depends_on a task not yet done).

    Args:
        tasks_json: The raw output from get_all_tasks.
        current_datetime: ISO string of right now.
    """
    # Always use the tool runtime clock.
    # The agent may sometimes pass a stale `current_datetime` from prior context;
    # using `datetime.now()` here makes the reasoning prompt consistent.
    tool_now = datetime.now().isoformat()

    # This tool is intentionally a pass-through prompt injection —
    # the LLM does the reasoning when it receives this tool's result.
    return (
        f"Current time: {tool_now}\n\n"
        f"Tasks to analyse:\n{tasks_json}\n\n"
        "Now rank these tasks by urgency. For each task compute a score 0-100 "
        "based on: deadline proximity, how many other tasks depend on it, and "
        "explicit urgency signals. Then call update_urgency_score for each task "
        "and return the final ranked pipeline with one-line reasons."
    )


# ── macOS output ─────────────────────────────────────────────────────────────

@tool
def create_sticky(content: str) -> str:
    """Create a sticky note on the Mac desktop showing the pipeline.

    Args:
        content: The text to display in the sticky note.
    """
    # Escape special characters for AppleScript string literal.
    # (Backslash must be escaped before others.)
    safe = content.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    script = (
        'tell application "Stickies"\n'
        "activate\n"
        f'make new note with properties {{text:"{safe}"}}\n'
        "end tell"
    )

    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if len(err) > 500:
            err = err[:500] + "..."
        return f"Sticky creation failed (osascript rc={proc.returncode}). {err}"

    return "Sticky note created."


@tool
def send_notification(title: str, message: str) -> str:
    """Send a macOS system notification banner.

    Args:
        title: Bold header of the notification.
        message: Body text — keep under 100 chars.
    """
    script = f'display notification "{message}" with title "{title}"'
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if len(err) > 500:
            err = err[:500] + "..."
        return f"Notification failed (osascript rc={proc.returncode}). {err}"
    return f"Notification sent: {title}"


# ── Export ───────────────────────────────────────────────────────────────────

tools = [
    get_current_datetime,
    get_all_tasks,
    add_task_to_notion,
    update_urgency_score,
    complete_task_in_notion,
    compute_pipeline,
    update_task_in_notion,
    send_notification,
]
