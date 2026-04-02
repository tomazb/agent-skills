# Python Simplification Reference

Load this file when the code being simplified is Python (including Django, FastAPI, Flask, data science, CLI tools).

## Table of Contents
1. Pythonic Idioms
2. Data Structures & Types
3. Control Flow
4. Functions & Callables
5. Error Handling
6. File & Resource Management
7. Async Patterns
8. Common Anti-Patterns → Fixes

---

## 1. Pythonic Idioms

Python has a strong culture of idiomatic code. Using built-in constructs makes code shorter AND clearer — a rare win-win.

### Comprehensions over manual loops for simple transforms

```python
# Before
result = []
for item in items:
    if item.is_active:
        result.append(item.name)

# After
result = [item.name for item in items if item.is_active]
```

**When NOT to use comprehensions:** If the body has side effects, multiple conditions, nested loops, or exceeds ~80 chars. A 3-line comprehension with nested `for` and `if` is worse than a 6-line loop.

```python
# Too complex for a comprehension — use a loop
result = []
for group in groups:
    for member in group.members:
        if member.is_active and member.role in allowed_roles:
            result.append(transform(member))
```

### Tuple unpacking

```python
# Before
point = get_coordinates()
x = point[0]
y = point[1]

# After
x, y = get_coordinates()
```

### Use `enumerate` over manual index tracking

```python
# Before
i = 0
for item in items:
    print(f"{i}: {item}")
    i += 1

# After
for i, item in enumerate(items):
    print(f"{i}: {item}")
```

### Use `zip` for parallel iteration

```python
# Before
for i in range(len(names)):
    print(f"{names[i]}: {scores[i]}")

# After
for name, score in zip(names, scores, strict=True):
    print(f"{name}: {score}")
```

`strict=True` (Python 3.10+) catches length mismatches. Use it unless intentionally truncating.

### f-strings over `.format()` and `%`

```python
# Before
msg = "Hello {}, you have {} items".format(name, count)
msg = "Hello %s, you have %d items" % (name, count)

# After
msg = f"Hello {name}, you have {count} items"
```

### `any()` and `all()` for boolean aggregation

```python
# Before
has_error = False
for item in items:
    if item.status == 'error':
        has_error = True
        break

# After
has_error = any(item.status == 'error' for item in items)
```

---

## 2. Data Structures & Types

### `dataclass` over manual `__init__` for data containers

```python
# Before
class User:
    def __init__(self, name: str, age: int, email: str):
        self.name = name
        self.age = age
        self.email = email

    def __repr__(self):
        return f"User(name={self.name!r}, age={self.age}, email={self.email!r})"

# After
from dataclasses import dataclass

@dataclass
class User:
    name: str
    age: int
    email: str
```

You get `__init__`, `__repr__`, `__eq__` for free. Use `frozen=True` for immutable data. For simple cases with no methods, `NamedTuple` also works well.

### `TypedDict` for dictionary shapes at API boundaries

```python
# Before — no shape information
def process_response(data: dict) -> str:
    return data["user"]["name"]

# After
from typing import TypedDict

class UserData(TypedDict):
    name: str
    email: str

class ApiResponse(TypedDict):
    user: UserData
    status: int

def process_response(data: ApiResponse) -> str:
    return data["user"]["name"]
```

### `defaultdict` over manual key-existence checks

```python
# Before
counts = {}
for word in words:
    if word not in counts:
        counts[word] = 0
    counts[word] += 1

# After
from collections import Counter
counts = Counter(words)
```

For general grouping:

```python
# Before
groups = {}
for item in items:
    key = item.category
    if key not in groups:
        groups[key] = []
    groups[key].append(item)

# After
from collections import defaultdict
groups = defaultdict(list)
for item in items:
    groups[item.category].append(item)
```

### `pathlib` over `os.path`

```python
# Before
import os
config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'settings.yaml')
if os.path.exists(config_path):
    with open(config_path, 'r') as f:
        data = f.read()

# After
from pathlib import Path
config_path = Path(__file__).parent.parent / 'config' / 'settings.yaml'
if config_path.exists():
    data = config_path.read_text()
```

---

## 3. Control Flow

### Guard clauses — same principle as every language, but pythonic flavor

```python
# Before
def send_notification(user):
    if user is not None:
        if user.email:
            if user.preferences.notifications_enabled:
                # actual logic
                ...

# After
def send_notification(user):
    if user is None or not user.email:
        return
    if not user.preferences.notifications_enabled:
        return
    # actual logic
    ...
```

### `match` statement (Python 3.10+) for structural pattern matching

```python
# Before
if isinstance(event, ClickEvent):
    handle_click(event.x, event.y)
elif isinstance(event, KeyEvent):
    handle_key(event.key)
elif isinstance(event, ScrollEvent):
    handle_scroll(event.delta)
else:
    handle_unknown(event)

# After
match event:
    case ClickEvent(x=x, y=y):
        handle_click(x, y)
    case KeyEvent(key=key):
        handle_key(key)
    case ScrollEvent(delta=delta):
        handle_scroll(delta)
    case _:
        handle_unknown(event)
```

Use `match` when you're dispatching on type or structure. For simple value matching, `if/elif` or a dict lookup is fine.

### Avoid boolean traps in function arguments

```python
# Before — what does True mean here?
render_chart(data, True, False, True)

# After — explicit keyword arguments
render_chart(data, show_legend=True, animate=False, include_title=True)
```

---

## 4. Functions & Callables

### Single-responsibility extraction

```python
# Before — one function doing three things
def process_report(data):
    # validate
    if not data or 'entries' not in data:
        raise ValueError("Invalid data")
    for entry in data['entries']:
        if entry['amount'] < 0:
            raise ValueError(f"Negative amount: {entry['amount']}")

    # transform
    totals = {}
    for entry in data['entries']:
        cat = entry['category']
        totals[cat] = totals.get(cat, 0) + entry['amount']

    # format
    lines = []
    for cat, total in sorted(totals.items()):
        lines.append(f"{cat}: ${total:,.2f}")
    return '\n'.join(lines)

# After
def validate_report(data: dict) -> None:
    if not data or 'entries' not in data:
        raise ValueError("Invalid data")
    for entry in data['entries']:
        if entry['amount'] < 0:
            raise ValueError(f"Negative amount: {entry['amount']}")

def aggregate_by_category(entries: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for entry in entries:
        totals[entry['category']] += entry['amount']
    return dict(totals)

def format_totals(totals: dict[str, float]) -> str:
    return '\n'.join(
        f"{cat}: ${total:,.2f}"
        for cat, total in sorted(totals.items())
    )

def process_report(data: dict) -> str:
    validate_report(data)
    totals = aggregate_by_category(data['entries'])
    return format_totals(totals)
```

### Use `functools` utilities where appropriate

```python
# Caching expensive pure functions
from functools import lru_cache

@lru_cache(maxsize=128)
def get_config(env: str) -> Config:
    return load_config_from_disk(env)
```

---

## 5. Error Handling

### Catch specific exceptions, never bare `except:`

```python
# Before — catches KeyboardInterrupt, SystemExit, everything
try:
    result = process(data)
except:
    log.error("Something failed")

# After
try:
    result = process(data)
except (ValueError, KeyError) as exc:
    log.error("Processing failed: %s", exc)
```

### Avoid try/except for flow control

```python
# Before — using exceptions as if/else
try:
    value = my_dict[key]
except KeyError:
    value = default_value

# After
value = my_dict.get(key, default_value)
```

### Use `contextlib.suppress` for intentional ignoring

```python
# Before
try:
    os.remove(tmp_file)
except FileNotFoundError:
    pass

# After
from contextlib import suppress
with suppress(FileNotFoundError):
    os.remove(tmp_file)
```

---

## 6. File & Resource Management

### Always use context managers for resources

```python
# Before — resource leak if exception occurs between open and close
f = open('data.txt')
data = f.read()
f.close()

# After
with open('data.txt') as f:
    data = f.read()

# Or for simple reads
data = Path('data.txt').read_text()
```

### Custom context managers with `contextlib`

```python
# Before — manual setup/teardown class
class Timer:
    def __enter__(self):
        self.start = time.monotonic()
        return self
    def __exit__(self, *args):
        self.elapsed = time.monotonic() - self.start

# After (for simple cases)
from contextlib import contextmanager

@contextmanager
def timer():
    start = time.monotonic()
    yield
    elapsed = time.monotonic() - start
    print(f"Elapsed: {elapsed:.3f}s")
```

---

## 7. Async Patterns

### Use `asyncio.gather` for concurrent independent tasks

```python
# Before — sequential
users = await fetch_users()
orders = await fetch_orders()
products = await fetch_products()

# After — concurrent
users, orders, products = await asyncio.gather(
    fetch_users(),
    fetch_orders(),
    fetch_products(),
)
```

### Use `async for` and `async with` properly

```python
# Before
session = await create_session()
try:
    async for msg in session.stream():
        process(msg)
finally:
    await session.close()

# After
async with create_session() as session:
    async for msg in session.stream():
        process(msg)
```

---

## 8. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It's Bad | Fix |
|---|---|---|
| `len(lst) == 0` / `len(lst) > 0` | Verbose, non-pythonic | `not lst` / `lst` (truthy check) |
| `if x == True:` / `if x == False:` | Redundant comparison | `if x:` / `if not x:` |
| `for i in range(len(lst)):` | Manual indexing | `for item in lst:` or `enumerate()` |
| `dict.keys()` in iteration | Unnecessary — dicts iterate keys by default | `for key in my_dict:` |
| `type(x) == SomeType` | Doesn't handle subclasses | `isinstance(x, SomeType)` |
| `lambda x: func(x)` | Pointless wrapper | Just pass `func` directly |
| Mutable default args `def f(lst=[]):` | Shared state across calls — classic bug | `def f(lst=None): lst = lst or []` |
| `global` variables for state | Hidden coupling, untestable | Pass state explicitly or use a class |
| `import *` | Namespace pollution, unclear origins | Explicit imports |
| String building with `+=` in a loop | O(n²) string allocation | `''.join(parts)` or list accumulation |
