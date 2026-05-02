# PR Comments

Fetch and display GitHub PR review comments for the current branch in the code review UI.

## Purpose

This skill enables inspection of PR feedback before deciding how to respond. It fetches all review comments (issue comments, diff comments, and review bodies) from the current branch's open GitHub PR and renders them in the code review interface.

## Key Capabilities

- Verifies `gh` CLI authentication before making any API calls
- Fetches issue comments, diff comments, and reviews via the GitHub API with pagination support
- Trims large diff hunks to a focused window around commented lines
- Supports both script-based fetching and manual fallback commands
- Renders comments via `insert_code_review_comments` with proper location and reply metadata

## Requirements

- `gh` CLI authenticated with repo access
- Current branch has an open pull request

## Scripts

| Script | Purpose |
|---|---|
| `scripts/fetch_github_review_comments.py` | Fetch all PR review comments and output JSON |
| `scripts/trim_diff_hunk.py` | Trim diff hunks to a window around target lines |
| `scripts/test_fetch_comments.py` | Tests for the fetch script |
| `scripts/test_trim_diff_hunk.py` | Tests for the diff hunk trimmer |

## Workflow

1. Verify `gh` authentication
2. Run `python3 scripts/fetch_github_review_comments.py`
3. Render the JSON output via `insert_code_review_comments`
4. Review the displayed comments and wait for user direction

After displaying comments, the agent must stop and ask the user how to proceed — it does not take further action unless explicitly instructed.
