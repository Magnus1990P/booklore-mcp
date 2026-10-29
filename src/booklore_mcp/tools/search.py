"""Search & discovery tools: full-library search, title and genre search, author
indexes, duplicate finding."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from .. import runtime
from ..app import mcp
from ..client import BookLoreError
from ..helpers import (
    _MISSING_FULL_ONLY,
    BookKind,
    _all_books,
    _author_names,
    _categories,
    _matches_filters,
    _matches_kind,
    _matches_query,
    _meta,
    _summarize_book,
)
from ..models import SearchResult

_SORT_KEYS = {
    "title": lambda b: (b.get("title") or (b.get("metadata") or {}).get("title") or "").lower(),
    "addedOn": lambda b: b.get("addedOn") or "",
    "rating": lambda b: b["personalRating"] if b.get("personalRating") is not None else -1,
    "readStatus": lambda b: b.get("readStatus") or "",
}

# Duplicate-detection signal presets (BookLore exposes no presets server-side).
_DUP_SIGNALS = (
    "matchByIsbn",
    "matchByExternalId",
    "matchByTitleAuthor",
    "matchByDirectory",
    "matchByFilename",
)
_DUP_PRESETS = {
    "strict": {"matchByIsbn", "matchByExternalId"},
    "balanced": {"matchByIsbn", "matchByExternalId", "matchByTitleAuthor"},
    "aggressive": set(_DUP_SIGNALS),
}


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Search books"})
async def search_books(
    query: str = "",
    filters: dict | None = None,
    sort: Literal["title", "addedOn", "rating", "readStatus"] = "title",
    order: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> SearchResult:
    """Search and filter the library server-side-style, returning a paginated page.

    `query` is a case-insensitive substring over title/subtitle/isbn/author names.
    `filters` is an optional object:
      - tags: [str], tags_mode: "any"|"all" (default "any")
      - categories: [str] (any), authors: [str] (any, substring)
      - shelf_ids: [int], library_ids: [int]
      - kind: "book"|"comic"|"audiobook" — by primary file type (comics are CBX)
      - read_status: "UNSET"|"READING"|"READ"|"UNREAD"|… (sparse upstream)
      - missing: subset of ["tags","categories","authors","description","isbn",
        "isbn10","isbn13","series","cover","asin","goodreadsId","googleId",
        "hardcoverId","amazonRating","goodreadsRating","publisher","language",
        "pageCount"] — fields to treat as empty.
      - missing_mode: "all" (default) keeps books where ALL listed fields are
        empty; "any" keeps books missing AT LEAST ONE — better for enrichment
        sweeps ("anything still lacking an id/rating").
    Returns {total, limit, offset, books:[summaries]}. `limit` is capped at 200.
    """
    filters = filters or {}
    missing = filters.get("missing") or []
    # Identifier fields (asin/goodreadsId/…), description and subtitle are stripped from
    # the plain list response — fetch full metadata when the query depends on one of them
    # (a text `query` matches subtitles, so it always needs the full records).
    need_desc = bool(query) or any(f in _MISSING_FULL_ONLY for f in missing)
    books = await _all_books(with_description=need_desc)

    if query:
        ql = query.lower()
        books = [b for b in books if _matches_query(b, ql)]
    if filters:
        books = [b for b in books if _matches_filters(b, filters)]

    books.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["title"]), reverse=(order == "desc"))

    total = len(books)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = books[offset : offset + limit]
    return SearchResult(
        total=total, limit=limit, offset=offset, books=[_summarize_book(b) for b in page]
    )


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "List authors"})
async def list_authors(query: str = "", limit: int = 100, offset: int = 0) -> dict:
    """List authors (from BookLore's authors index) with per-author book counts.
    Optionally filter by a case-insensitive substring `query`."""
    authors = await runtime.client.get("/api/v1/authors") or []
    if query:
        ql = query.lower()
        authors = [a for a in authors if ql in (a.get("name") or "").lower()]
    authors.sort(key=lambda a: (a.get("name") or "").lower())
    page = authors[max(0, offset) : max(0, offset) + max(1, limit)]
    return {
        "total": len(authors),
        "authors": [
            {"id": a.get("id"), "name": a.get("name"), "book_count": a.get("bookCount")}
            for a in page
        ],
    }


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Books by author"})
async def books_by_author(author: str, limit: int = 50, offset: int = 0) -> SearchResult:
    """List books by an author (case-insensitive exact match on the author name)."""
    al = author.lower()
    matched = [
        b
        for b in await _all_books()
        if any(al == n.lower() for n in _author_names(b.get("metadata") or {}))
    ]
    total = len(matched)
    limit = max(1, limit)
    offset = max(0, offset)
    page = matched[offset : offset + limit]
    return SearchResult(
        total=total, limit=limit, offset=offset, books=[_summarize_book(b) for b in page]
    )


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Search titles"})
async def search_titles(
    query: str,
    in_subtitle: bool = True,
    kind: BookKind = "all",
    limit: int = 50,
    offset: int = 0,
) -> SearchResult:
    """Find books whose title (and, by default, subtitle) contains `query`.

    Case-insensitive substring match on the title text only — unlike search_books it
    ignores authors and ISBNs, so "war" finds "The Art of War" but not a book by an author
    named Warren. Set in_subtitle=False to match titles alone. `kind` narrows to
    "book", "comic" (CBX) or "audiobook". Sorted by title; `limit` is capped at 200.
    Returns {total, limit, offset, books:[summaries]}.
    """
    ql = query.strip().lower()
    if not ql:
        raise BookLoreError("Provide a non-empty `query`.")

    def hit(b: dict) -> bool:
        parts = [b.get("title") or _meta(b).get("title")]
        if in_subtitle:
            parts.append(_meta(b).get("subtitle"))
        return any(ql in str(p).lower() for p in parts if p)

    # Subtitles are stripped from the plain list response, so fetch full records.
    books = [
        b for b in await _all_books(with_description=True) if _matches_kind(b, kind) and hit(b)
    ]
    books.sort(key=_SORT_KEYS["title"])
    return _page(books, limit, offset)


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "List genres"})
async def list_genres(query: str = "", limit: int = 100, offset: int = 0) -> dict:
    """List the library's genres (BookLore categories) with per-genre book counts.

    Genres are collected from every book's categories, merged case-insensitively (the
    first spelling seen is kept). Optionally filter by a case-insensitive substring
    `query`. Use books_by_genre to list the books in one. Returns {total, genres:[{name,
    book_count}]}.
    """
    names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for b in await _all_books():
        # De-duplicate per book first so a book tagged "SciFi" and "scifi" counts once.
        for key, name in {c.lower(): c for c in _categories(b)}.items():
            names.setdefault(key, name)
            counts[key] += 1
    keys = sorted(names, key=lambda k: names[k].lower())
    if query:
        ql = query.lower()
        keys = [k for k in keys if ql in k]
    page = keys[max(0, offset) : max(0, offset) + max(1, limit)]
    return {
        "total": len(keys),
        "genres": [{"name": names[k], "book_count": counts[k]} for k in page],
    }


@mcp.tool(annotations={"readOnlyHint": True, "idempotentHint": True, "title": "Books by genre"})
async def books_by_genre(
    genre: str, kind: BookKind = "all", limit: int = 50, offset: int = 0
) -> SearchResult:
    """List books in a genre (case-insensitive exact match on a BookLore category). Get
    genre names from list_genres. `kind` narrows to "book", "comic" or "audiobook".
    Sorted by title. Returns {total, limit, offset, books:[summaries]}."""
    gl = genre.lower()
    matched = [
        b
        for b in await _all_books()
        if _matches_kind(b, kind) and any(gl == c.lower() for c in _categories(b))
    ]
    matched.sort(key=_SORT_KEYS["title"])
    return _page(matched, limit, offset)


def _page(books: list[dict], limit: int, offset: int) -> SearchResult:
    """Paginate sorted raw records into a SearchResult (limit capped at 200)."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return SearchResult(
        total=len(books),
        limit=limit,
        offset=offset,
        books=[_summarize_book(b) for b in books[offset : offset + limit]],
    )


@mcp.tool(annotations={"readOnlyHint": True, "title": "Find duplicates"})
async def find_duplicates(
    library_id: int | None = None,
    preset: Literal["strict", "balanced", "aggressive"] = "balanced",
    signals: dict | None = None,
) -> dict:
    """Find duplicate books using BookLore's native detection — read-only, merges nothing.

    Detection is per-library; omit `library_id` to scan every library. `preset` picks
    the signal set: strict (ISBN + external id), balanced (+ title/author), aggressive
    (+ same-directory + filename). `signals` overrides individual flags, e.g.
    {"matchByFilename": true}. Each group reports the suggested merge target, the match
    reason, the books, and `distinct_isbns` (true ⇒ the books carry different ISBNs, so
    likely separate editions rather than true duplicates).
    Returns {libraries_scanned, group_count, groups}.
    """
    flags = {s: (s in _DUP_PRESETS[preset]) for s in _DUP_SIGNALS}
    if signals:
        bad = sorted(set(signals) - set(_DUP_SIGNALS))
        if bad:
            raise BookLoreError(
                f"Unknown duplicate signal(s): {', '.join(bad)}. Valid: {', '.join(_DUP_SIGNALS)}."
            )
        flags.update({k: bool(v) for k, v in signals.items()})

    if library_id is not None:
        library_ids: list[int] = [library_id]
    else:
        libs = await runtime.client.get("/api/v1/libraries") or []
        library_ids = [
            lib["id"] for lib in libs if isinstance(lib, dict) and lib.get("id") is not None
        ]

    groups: list[dict] = []
    for lib_id in library_ids:
        result = (
            await runtime.client.post(
                "/api/v1/books/duplicates", json={"libraryId": lib_id, **flags}
            )
            or []
        )
        for grp in result:
            books = grp.get("books") or []
            isbns = {(_meta(b).get("isbn13") or _meta(b).get("isbn10")) for b in books}
            isbns.discard(None)
            groups.append(
                {
                    "library_id": lib_id,
                    "match_reason": grp.get("matchReason"),
                    "suggested_target_book_id": grp.get("suggestedTargetBookId"),
                    "distinct_isbns": len(isbns) > 1,
                    "books": [
                        {
                            "id": b.get("id"),
                            "title": b.get("title") or _meta(b).get("title"),
                            "authors": _author_names(_meta(b)),
                            "isbn13": _meta(b).get("isbn13"),
                            "isbn10": _meta(b).get("isbn10"),
                        }
                        for b in books
                    ],
                }
            )
    return {"libraries_scanned": len(library_ids), "group_count": len(groups), "groups": groups}
