# Jest Guidance

- Group by behavior using `describe` blocks.
- Keep each `it` focused on one observable behavior.
- Prefer user-visible output assertions over implementation details.
- Avoid over-mocking internals; mock true boundaries only.
- Use fake timers only when timing control is required.
- Reset state between tests to keep suites deterministic.
