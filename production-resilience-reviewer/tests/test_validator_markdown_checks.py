from __future__ import annotations


def test_fence_count_even_odd(validator):
    assert validator.fence_count_ok("```txt\nhello\n```\n")
    assert not validator.fence_count_ok("```txt\nhello\n")


def test_find_leaked_toc_titles_detects_consecutive_entries(validator):
    text = """## 6. Review

7. Dependencies
8. Networking
9. Data Integrity
"""
    issues = validator.find_leaked_toc_titles(text)
    assert len(issues) == 3
    assert "7. Dependencies" in issues[0]
    assert "8. Networking" in issues[1]
    assert "9. Data Integrity" in issues[2]


def test_find_leaked_toc_titles_ignores_content_inside_code_fences(validator):
    text = """## 6. Review

```md
7. Dependencies
8. Networking
```
"""
    assert validator.find_leaked_toc_titles(text) == []


def test_find_leaked_toc_titles_ignores_regular_step_lists(validator):
    text = """## 1. Setup

1. Install dependencies
2. Run validation
"""
    assert validator.find_leaked_toc_titles(text) == []
