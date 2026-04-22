#!/usr/bin/env python3
"""Fetch GitHub PR review comments and output JSON for insert_code_review_comments.

Requires: gh CLI (authenticated), git.
Must be run from within a git repository whose current branch has an open PR.

Prints JSON to stdout matching the insert_code_review_comments tool schema.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Sequence

from trim_diff_hunk import last_reachable_line, line_in_hunk, trim_diff_hunk


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_command(args: Sequence[str], error_msg: str = "Command failed") -> str:
    """Run a command and return stdout. Exits on failure."""
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "GH_PAGER": ""},
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout
        print(f"{error_msg}: {detail}".rstrip(": "), file=sys.stderr)
        raise SystemExit(1)
    return result.stdout


def ensure_gh_authenticated() -> None:
    """Fail fast when the GitHub CLI is not authenticated."""
    run_command(
        ["gh", "auth", "status"],
        "gh auth status failed; run `gh auth login` and retry",
    )


def run_gh_api(endpoint: str) -> list[dict[str, Any]]:
    """Run ``gh api --paginate`` and return a list of JSON objects.

    Handles the case where ``gh`` outputs multiple concatenated JSON arrays
    (one per page).
    """
    text = run_command(
        ["gh", "api", endpoint, "--paginate"],
        error_msg=f"gh api {endpoint} failed",
    ).strip()
    if not text:
        return []

    items: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    pos = 0
    try:
        while pos < len(text):
            while pos < len(text) and text[pos] in " \t\n\r":
                pos += 1
            if pos >= len(text):
                break
            obj, end = decoder.raw_decode(text, pos)
            items.extend(obj if isinstance(obj, list) else [obj])
            pos = end
    except json.JSONDecodeError as exc:
        print(f"Failed to parse API response: {exc}", file=sys.stderr)
        raise SystemExit(1)
    return items


# ---------------------------------------------------------------------------
# Comment building
# ---------------------------------------------------------------------------

def _comment(
    cid: str,
    author: str,
    ts: str,
    body: str,
    url: str,
    location: dict[str, Any] | None = None,
    reply_to: str | None = None,
) -> dict[str, Any]:
    """Build a dict matching the insert_code_review_comments comment schema."""
    comment = {
        "comment_id": cid,
        "author": author,
        "last_modified_timestamp": ts,
        "comment_body": body,
        "html_url": url,
    }
    if reply_to:
        comment["reply_metadata"] = {"parent_comment_id": reply_to}
    elif location:
        comment["location_metadata"] = location
    return comment


def _resolve_line(
    hunk: str,
    line: int | None,
    original_line: int | None,
    side: str,
) -> int | None:
    """Pick the first line number that is reachable in the hunk on *side*.

    Tries *line* first (current diff position), then *original_line*
    (position when the comment was placed). If neither is reachable,
    falls back to the last reachable line in the hunk on *side*.

    Returns the resolved line number, or ``None`` if nothing is reachable.
    """
    if line and line_in_hunk(hunk, line, side):
        return line
    if original_line and line_in_hunk(hunk, original_line, side):
        return original_line
    return last_reachable_line(hunk, side)


def _resolve_comment_line(
    comment: dict[str, Any],
    hunk: str,
) -> tuple[int, int | None, str] | None:
    """Resolve validated (end_line, start_line, side) for a diff comment.

    Uses ``side`` from the GitHub API as the authoritative diff side.
    Returns ``(end_line, start_line | None, side)`` or ``None`` when the
    comment cannot be attached to any line in the hunk.
    """
    side = comment.get("side") or "RIGHT"

    end_line = _resolve_line(
        hunk,
        comment.get("line"),
        comment.get("original_line"),
        side,
    )
    if end_line is None:
        return None

    raw_start = comment.get("start_line")
    raw_original_start = comment.get("original_start_line")
    if raw_start or raw_original_start:
        start_line = _resolve_line(hunk, raw_start, raw_original_start, side)
        if start_line is not None and start_line > end_line:
            start_line = None
    else:
        start_line = None

    return (end_line, start_line, side)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ensure_gh_authenticated()

    repo_root = run_command(
        ["git", "rev-parse", "--show-toplevel"],
        "Not a git repository",
    ).strip()

    pr = json.loads(
        run_command(
            [
                "gh",
                "pr",
                "view",
                "--json",
                "number,headRepository,headRepositoryOwner,baseRefName",
            ],
            "Failed to get PR info (is there an open PR on this branch?)",
        )
    )
    number = pr["number"]
    owner = pr["headRepositoryOwner"]["login"]
    repo = pr["headRepository"]["name"]
    base = pr["baseRefName"]

    api = f"/repos/{owner}/{repo}"

    issue_comments = run_gh_api(f"{api}/issues/{number}/comments")
    diff_comments = run_gh_api(f"{api}/pulls/{number}/comments")
    reviews = run_gh_api(f"{api}/pulls/{number}/reviews")

    comments: list[dict[str, Any]] = []

    # -- Issue comments (PR-level, no location or reply metadata) -----------
    for comment in issue_comments:
        comments.append(
            _comment(
                str(comment["id"]),
                comment["user"]["login"] if comment.get("user") else "[deleted]",
                comment["updated_at"],
                comment["body"],
                comment["html_url"],
            )
        )

    # -- Diff comments (line-level, with location or reply) -----------------
    for comment in diff_comments:
        cid = str(comment["id"])
        author = comment["user"]["login"] if comment.get("user") else "[deleted]"
        ts = comment["updated_at"]
        body = comment["body"]
        url = comment["html_url"]

        reply_to_id = comment.get("in_reply_to_id")
        if reply_to_id:
            comments.append(
                _comment(cid, author, ts, body, url, reply_to=str(reply_to_id))
            )
            continue

        hunk = comment.get("diff_hunk", "")
        resolved = _resolve_comment_line(comment, hunk)

        location: dict[str, Any] = {"filepath": comment["path"]}
        if resolved:
            end_line, start_line, side = resolved
            if hunk:
                location["diff_hunk"] = trim_diff_hunk(
                    hunk,
                    end_line,
                    side=side,
                    start_line=start_line,
                )
            location["end_line"] = end_line
            if start_line:
                location["start_line"] = start_line
            location["side"] = side

        comments.append(_comment(cid, author, ts, body, url, location=location))

    # -- Reviews (PR-level, no location) ------------------------------------
    for review in reviews:
        if not review.get("body"):
            continue
        comments.append(
            _comment(
                str(review["id"]),
                review["user"]["login"] if review.get("user") else "[deleted]",
                review.get("submitted_at", ""),
                review["body"],
                review["html_url"],
            )
        )

    result = {
        "local_repository_path": repo_root,
        "base_branch": base,
        "comments": comments,
    }
    json.dump(result, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
