---
name: pr-comments
description: "Use when you need to display GitHub PR review comments in the code review UI, or inspect review feedback on the current branch before deciding how to respond."
---

# Fetch PR Comments

Fetch all review comments from the current branch's GitHub PR and display them via `insert_code_review_comments`.

## Quick Reference

- Verify auth: `gh auth status`
- Fetch the JSON payload: `python3 <skill_dir>/scripts/fetch_github_review_comments.py`
- Render the comments: call `insert_code_review_comments` with the script output
- Act on the feedback afterward: use `gh-address-comments`

## Procedure

1. Verify `gh` is authenticated before making API calls.
   ```bash
   gh auth status
   ```
   If this fails, ask the user to run `gh auth login` before continuing.

2. Run the bundled script (must be inside a git repo with an open PR on the current branch).
   Use `do_not_summarize_output: true` when running this shell command so the JSON output is not truncated.
   ```bash
   python3 <skill_dir>/scripts/fetch_github_review_comments.py
   ```
   The script prints JSON to stdout.
   If the script fails to fetch comments, run the fallback `gh` commands instead.

3. Call `insert_code_review_comments` with the three top-level fields from the JSON output:
   - `local_repository_path`
   - `base_branch`
   - `comments`

4. Stop and wait for the user. After displaying each batch of comments, you MUST ask the user how they would like to proceed. Do NOT take any further action until the user provides explicit instructions unless the user explicitly asks you to.
Do NOT make code changes in response to the fetched comments unless the user tells you to. Do NOT impersonate the user by submitting review responses.
Your role when fetching and displaying comments is purely informational — present the comments and wait for direction. If the user wants to address the feedback, transition to `gh-address-comments`.

## What the Script Handles

- Fetches issue comments, diff comments, and reviews via `gh api --paginate`
- Trims large diff hunks to a window around the commented line
- Sets `reply_metadata` on reply comments
- Sets `location_metadata` on top-level diff comments (filepath, trimmed diff hunk, line, side)
- PR-level comments (issue comments and reviews) have neither location nor reply metadata

## Script fallback commands

If the script fails to fetch comments, follow these steps to fetch comments directly from the GitHub API:

1. Use `gh pr view --json number,headRepository,headRepositoryOwner,baseRefName` to resolve the PR number, owner, repo, and base branch.
2. Fetch PR-level comments from `/issues/{pr_number}/comments`.
3. Fetch file- and line-level review comments from `/pulls/{pr_number}/comments`, removing location metadata from thread replies.
4. Fetch review bodies from `/pulls/{pr_number}/reviews`.
5. Invoke `insert_code_review_comments` with all PR-, review-, file-, and line-level comments. If there are no comments, send an empty list rather than reading them out manually.
6. After displaying comments, follow step 4 of the Procedure above: stop and ask the user how they want to proceed.

Clear `GH_PAGER` before any `gh` fallback command so pagers do not interfere with command execution.

## Requirements

- `gh` CLI authenticated with repo access
- Current branch has an open pull request
