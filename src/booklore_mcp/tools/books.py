"""Read tools for individual books and recommendations."""

from __future__ import annotations

from .. import runtime
from ..app import mcp
from ..helpers import _summarize_book
from ..models import BookSummary


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "title": "List / search books"}
)
async def list_books(query: str = "", limit: int = 25) -> list[BookSummary]:
    """List books in the library, optionally filtered by a keyword.

    `query` is matched (case-insensitive substring) against title and author
    names client-side; leave empty to list everything. Returns trimmed summaries
    (id, title, authors, series, readStatus, personalRating, shelves) capped at
    `limit`. Call get_book for full details on one book.
    """
    books = await runtime.client.get("/api/v1/books", params={"withDescription": "false"}) or []
    summaries = [_summarize_book(b) for b in books]
    if query:
        q = query.lower()

        def matches(s: BookSummary) -> bool:
            hay = " ".join(str(x) for x in [s.title, *(s.authors or [])] if x).lower()
            return q in hay

        summaries = [s for s in summaries if matches(s)]
    return summaries[:limit]


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Get book details"})
async def get_book(book_id: int, with_description: bool = True) -> dict:
    """Fetch a single book's full record by ID, including its metadata.

    Use list_books first if you don't know the ID. Set with_description=False to
    omit the (potentially long) description field.
    """
    return await runtime.client.get(
        f"/api/v1/books/{book_id}",
        params={"withDescription": str(with_description).lower()},
    )


@mcp.tool(
    annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Get recommendations"}
)
async def get_recommendations(book_id: int, limit: int = 10) -> list[dict]:
    """Get books recommended as similar to the given book (max 25)."""
    return (
        await runtime.client.get(
            f"/api/v1/books/{book_id}/recommendations",
            params={"limit": max(1, min(limit, 25))},
        )
        or []
    )
