# -*- coding: utf-8 -*-
# Copyright 2026 蜜蜂 & CoApis Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
File preview endpoint for chat media URLs.

`/files/preview/{filepath:path}` serves files by absolute path.  Used by the
frontend's `toDisplayUrl` → `filePreviewUrl` chain to render file attachments
in chat messages, and by the answer-side deliverable cards (a chat answer can
now link straight to a produced file).

The frontend constructs URLs like:
    /api/files/preview/media/xxx.ppm?token=xxx
    /api/files/preview/{WORKSPACES_DIR}/admin/files/media/xxx.ppm?token=xxx

SCOPED ACCESS (added 2026-10-21, gate B0 of the resource-experience plan).
Before this gate the endpoint resolved *any* path on the machine and served
it — measured on dev: `GET /api/files/preview/etc/passwd` answered **200**
with the real `/etc/passwd`, and a cross-user `agent.json` answered **200**.
Once answer bodies carry clickable links, that endpoint is an arbitrary
file-read entry point, so scope is enforced here first:

    caller's own workspace  →  allowed
    global chat media dir   →  allowed (chat attachments land there)
    admin                   →  all workspaces (audit)
    anything else           →  403

Response modes (so the preview drawer can render text inline instead of
forcing a download):
    mode=inline    md/txt/json/… served as text/plain; images & PDF inline
    mode=download  always `Content-Disposition: attachment`
    default        inline for text-ish/media types, attachment for the rest
`?v=<updated_at>` participates in the cache key, so a same-name overwrite
(`files/x.md` written twice) never serves a stale cached copy.
"""

import logging
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import FileResponse, Response

from ...constant import DEFAULT_MEDIA_DIR, WORKING_DIR, WORKSPACES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["file-preview"])

#: Files bigger than this are not previewed in the browser.
MAX_PREVIEW_BYTES = 20 * 1024 * 1024

#: Extensions served as plain text for in-drawer rendering.  Everything not
#: in this set and not an image/PDF goes back as an attachment.
TEXT_PREVIEW_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".text",
        ".log",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".csv",
        ".tsv",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".html",
        ".htm",
        ".css",
        ".sql",
        ".sh",
        ".bash",
        ".xml",
        ".rst",
    }
)

INLINE_MEDIA_PREFIXES = ("image/", "audio/", "video/")
INLINE_MEDIA_TYPES = frozenset({"application/pdf"})


def _normalize_requested(raw: str) -> str:
    """Percent-decode and fix the Windows `/C:/...` shape."""
    normalized = unquote(raw)
    if (
        len(normalized) >= 4
        and normalized[0] == "/"
        and normalized[2] == ":"
        and normalized[1].isalpha()
    ):
        normalized = normalized[1:]
    return normalized


def _resolve_requested(normalized: str) -> Path:
    """Resolve the request to a real filesystem path.

    `resolve()` collapses `..` and follows symlinks, so the scope check below
    always sees the final location — a symlink pointing outside the workspace
    is rejected by the same check that rejects `/etc/passwd`.
    """
    path = Path(normalized)
    if not path.is_absolute():
        path = Path("/" + normalized)
    return path.resolve()


def _allowed_roots(username: str, role: str) -> list[Path]:
    """Directories the caller may read through this endpoint.

    - own workspace: the normal case for a user's own files and attachments
    - global chat media dir: chat attachments land in `WORKING_DIR/media`,
      not in the user's workspace, and must stay renderable
    - admin: every workspace (audit duty) — deliberately *not* the whole
      filesystem; `/etc/passwd` is 403 for admins too.
    """
    roots: list[Path] = []
    if username and username != "anonymous":
        roots.append((WORKSPACES_DIR / username).resolve())
    roots.append(Path(DEFAULT_MEDIA_DIR).resolve())
    if role == "admin":
        roots.append(Path(WORKSPACES_DIR).resolve())
        roots.append(Path(WORKING_DIR).resolve())
    return roots


def _in_scope(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _content_disposition(mode: str, name: str) -> dict:
    if mode == "inline":
        # No Content-Disposition at all → the browser renders the resource
        # (images/PDF in an <img>/<iframe>, text in the drawer).
        return {}
    return {"Content-Disposition": f'attachment; filename="{name}"'}


def _cache_headers(v: str | None) -> dict:
    if v:
        # `?v=<updated_at>` makes the URL unique per file revision, so the
        # browser may cache it without serving a stale same-name overwrite.
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "no-cache"}


def _text_response(path: Path, mode: str, v: str | None) -> Response:
    headers = {**_cache_headers(v), **_content_disposition(mode, path.name)}
    return FileResponse(
        path,
        media_type="text/plain",
        headers=headers,
        filename=None,
    )


def _inline_media_response(path: Path, v: str | None) -> Response:
    import mimetypes

    mime, _ = mimetypes.guess_type(path.name)
    headers = {**_cache_headers(v), **_content_disposition("inline", path.name)}
    return FileResponse(
        path,
        media_type=mime or "application/octet-stream",
        headers=headers,
        filename=None,
    )


def _attachment_response(path: Path, v: str | None) -> Response:
    headers = {**_cache_headers(v), **_content_disposition("download", path.name)}
    return FileResponse(path, filename=path.name, headers=headers)


@router.api_route(
    "/preview/{filepath:path}",
    methods=["GET", "HEAD"],
    summary="Preview file by path (scoped to the caller)",
)
async def preview_file(
    filepath: str,
    request: Request,
    mode: str = Query("auto", description="auto | inline | download"),
    v: str | None = Query(None, description="Revision stamp (cache key)"),
):
    """Serve a file by path, restricted to the caller's scope.

    Accepts absolute paths only (the frontend's `toDisplayUrl` sends the real
    absolute path for anything under `/workspaces/`); relative-looking inputs
    are resolved against `/` exactly as before so existing media URLs keep
    working.

    Auth: the auth middleware fills `request.state` from the `Authorization`
    header **or** the `?token=` query parameter (query params are how `<img>`
    and `<a>` URLs authenticate).  An anonymous context (no token) can only
    read the global chat media directory.
    """
    normalized = _normalize_requested(filepath)
    path = _resolve_requested(normalized)

    # 作用域先判、存在性后判：反过来等于给越权调用方开了「存在性探针」——
    # `/etc/passwd` 回 403、`/etc/shadow` 回 404，哪些文件在机器上就泄露了。
    username = getattr(request.state, "username", "") or ""
    role = getattr(request.state, "role", "user") or "user"
    roots = _allowed_roots(username, role)

    if not _in_scope(path, roots):
        logger.warning(
            "preview scope denied: user=%s role=%s requested=%s resolved=%s",
            username or "-",
            role,
            filepath,
            path,
        )
        raise HTTPException(
            status_code=403,
            detail="Path is outside your workspace scope",
        )

    if not path.is_file():
        logger.debug("File not found: %s (requested: %s)", path, filepath)
        raise HTTPException(status_code=404, detail="Not found")

    if path.stat().st_size > MAX_PREVIEW_BYTES:
        raise HTTPException(status_code=413, detail="File too large to preview")

    mode = (mode or "auto").lower()
    if mode not in ("auto", "inline", "download"):
        mode = "auto"

    suffix = path.suffix.lower()
    import mimetypes

    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"

    # 1) Text-ish files: inline text for the preview drawer.
    if suffix in TEXT_PREVIEW_SUFFIXES:
        if mode == "download":
            return _attachment_response(path, v)
        return _text_response(path, "inline", v)

    # 2) Images / audio / video / PDF: inline so <img>/<iframe> render them.
    if mime.startswith(INLINE_MEDIA_PREFIXES) or mime in INLINE_MEDIA_TYPES:
        if mode == "download":
            return _attachment_response(path, v)
        return _inline_media_response(path, v)

    # 3) Everything else (docx/xlsx/zip/…): download only.
    return _attachment_response(path, v)
