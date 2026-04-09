# Pytest Guidance

- Name tests as `test_<unit>_<scenario>_<expected_outcome>`.
- Prefer fixtures for setup reuse; avoid global mutable state.
- Use parametrization for data-shape variants.
- Keep assertions precise and behavior-focused.
- Avoid sleeps; use bounded polling for async convergence.
- Isolate external boundaries with fakes/mocks where needed.
