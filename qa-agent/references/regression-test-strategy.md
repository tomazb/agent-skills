# Regression Test Strategy

Goal: prevent reintroduction of known defects and protect critical paths.

## Baseline

- Run targeted tests for changed modules first.
- Run nearest integration suite second.
- Run broader suite when blast radius is medium or high.

## Prioritization

- Prioritize business-critical workflows and destructive paths.
- Prioritize contracts consumed by multiple clients.
- Prioritize areas with recent defect history.

## Closure Rule

A defect is only closed when:
- a failing reproduction exists,
- the fix is verified,
- and a regression guard exists (automated test or documented reason).
