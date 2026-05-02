# Changelog

## 0.1.0

- Fetch and display GitHub PR review comments for the current branch.
- Verify `gh` CLI authentication before making API calls.
- Trim large diff hunks to a focused window around commented lines.
- Support both script-based fetching and manual fallback commands.
- Render comments via `insert_code_review_comments` with proper location and reply metadata.
