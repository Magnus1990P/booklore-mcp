"""Shelf read/write tools: listing, membership, and shelf lifecycle."""

from __future__ import annotations

from typing import Any

from .. import runtime
from ..app import mcp
from ..helpers import _summarize_book
from ..models import BookSummary


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "List shelves"})
async def list_shelves() -> list[dict]:
    """List all shelves (id, name, icon, public flag). Use get_shelf_books to see
    the books on a given shelf."""
    return await runtime.client.get("/api/v1/shelves") or []


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Get books on a shelf"}
)
async def get_shelf_books(shelf_id: int) -> list[BookSummary]:
    """List the books on a shelf, as trimmed summaries. Get shelf IDs from
    list_shelves."""
    books = await runtime.client.get(f"/api/v1/shelves/{shelf_id}/books") or []
    return [_summarize_book(b) for b in books]


@mcp.tool(annotations={"idempotentHint": True, "title": "Assign / unassign shelves"})
async def assign_shelves(
    book_ids: list[int],
    add_shelf_ids: list[int] | None = None,
    remove_shelf_ids: list[int] | None = None,
) -> list[dict]:
    """Add and/or remove books from shelves in one call. Get shelf IDs from
    list_shelves and book IDs from list_books. Returns the affected books."""
    return await runtime.client.post(
        "/api/v1/books/shelves",
        json={
            "bookIds": book_ids,
            "shelvesToAssign": add_shelf_ids or [],
            "shelvesToUnassign": remove_shelf_ids or [],
        },
    )


@mcp.tool(annotations={"title": "Create shelf"})
async def create_shelf(name: str, icon: str | None = None, public_shelf: bool = False) -> dict:
    """Create a new shelf. Returns the created shelf including its new ID."""
    body: dict[str, Any] = {"name": name, "publicShelf": public_shelf}
    if icon:
        body["icon"] = icon
    return await runtime.client.post("/api/v1/shelves", json=body)


@mcp.tool(annotations={"destructiveHint": True, "idempotentHint": True, "title": "Delete shelf"})
async def delete_shelf(shelf_id: int) -> str:
    """Delete a shelf by ID. Does NOT delete the books on it. This cannot be
    undone — confirm the shelf ID with list_shelves first."""
    await runtime.client.delete(f"/api/v1/shelves/{shelf_id}")
    return f"Deleted shelf {shelf_id}."


@mcp.tool(annotations={"idempotentHint": True, "title": "Add books to shelves"})
async def add_to_shelves(book_ids: list[int], shelf_ids: list[int]) -> list[dict]:
    """Append books to shelves without disturbing their other shelves (idempotent).
    The additive counterpart to assign_shelves. Returns the affected books."""
    return await runtime.client.post(
        "/api/v1/books/shelves",
        json={"bookIds": book_ids, "shelvesToAssign": shelf_ids, "shelvesToUnassign": []},
    )


@mcp.tool(annotations={"idempotentHint": True, "title": "Remove books from shelves"})
async def remove_from_shelves(book_ids: list[int], shelf_ids: list[int]) -> list[dict]:
    """Remove books from shelves without disturbing their other shelves (idempotent).
    Returns the affected books."""
    return await runtime.client.post(
        "/api/v1/books/shelves",
        json={"bookIds": book_ids, "shelvesToAssign": [], "shelvesToUnassign": shelf_ids},
    )
