"""Pydantic response models returned by the MCP tools."""

from __future__ import annotations

from pydantic import BaseModel


class BookSummary(BaseModel):
    """Trimmed view of a Book, returned by the list-style read tools."""

    id: int | None = None
    title: str | None = None
    authors: list[str] | None = None
    series: str | None = None
    readStatus: str | None = None
    personalRating: float | None = None
    shelves: list[str] = []


class SearchResult(BaseModel):
    """Paginated result envelope for search_books / books_by_author."""

    total: int
    limit: int
    offset: int
    books: list[BookSummary]
