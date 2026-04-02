# Rust Simplification Reference

Load this file when the code being simplified is Rust. Rust's ownership system and type system already enforce correctness — simplification here means leveraging the compiler more, reducing boilerplate, and using the standard library idioms.

## Table of Contents
1. Error Handling & The `?` Operator
2. Pattern Matching & Enums
3. Iterator Patterns
4. Ownership & Borrowing
5. Structs & Traits
6. Common Anti-Patterns → Fixes

---

## 1. Error Handling & The `?` Operator

### Replace `match` on Result/Option with `?`

```rust
// Before
fn read_config(path: &str) -> Result<Config, Box<dyn Error>> {
    let content = match fs::read_to_string(path) {
        Ok(c) => c,
        Err(e) => return Err(Box::new(e)),
    };
    let config = match serde_json::from_str(&content) {
        Ok(c) => c,
        Err(e) => return Err(Box::new(e)),
    };
    Ok(config)
}

// After
fn read_config(path: &str) -> Result<Config, Box<dyn Error>> {
    let content = fs::read_to_string(path)?;
    let config = serde_json::from_str(&content)?;
    Ok(config)
}
```

### Use `map_err` or `context` (anyhow) for adding context

```rust
// Before
let file = File::open(path).map_err(|e| {
    MyError::Io(format!("opening {}: {}", path, e))
})?;

// After (with anyhow)
use anyhow::Context;
let file = File::open(path)
    .with_context(|| format!("opening {path}"))?;
```

### Chain `Option` methods instead of nested `match`

```rust
// Before
fn get_username(user: Option<&User>) -> String {
    match user {
        Some(u) => match &u.profile {
            Some(p) => p.name.clone(),
            None => "anonymous".to_string(),
        },
        None => "anonymous".to_string(),
    }
}

// After
fn get_username(user: Option<&User>) -> String {
    user.and_then(|u| u.profile.as_ref())
        .map(|p| p.name.clone())
        .unwrap_or_else(|| "anonymous".to_string())
}
```

---

## 2. Pattern Matching & Enums

### Use `if let` / `let else` for single-variant matching

```rust
// Before
match maybe_value {
    Some(val) => {
        process(val);
    }
    None => {}
}

// After
if let Some(val) = maybe_value {
    process(val);
}
```

### Use `let...else` for early exit (Rust 1.65+)

```rust
// Before
fn process(input: Option<&str>) -> Result<(), Error> {
    let input = match input {
        Some(s) => s,
        None => return Err(Error::MissingInput),
    };
    // use input...
    Ok(())
}

// After
fn process(input: Option<&str>) -> Result<(), Error> {
    let Some(input) = input else {
        return Err(Error::MissingInput);
    };
    // use input...
    Ok(())
}
```

### Use discriminated enums over stringly-typed values

```rust
// Before
struct Event {
    event_type: String,   // "click", "keypress", "scroll"
    data: String,         // JSON blob, shape depends on event_type
}

// After
enum Event {
    Click { x: f64, y: f64 },
    Keypress { key: char, modifiers: Modifiers },
    Scroll { delta: f64 },
}
```

The compiler enforces exhaustive handling of all variants.

### Add `#[non_exhaustive]` on public enums

If the enum might grow in future versions, this forces downstream callers to include a wildcard arm, preventing breakage.

---

## 3. Iterator Patterns

### Prefer iterators over manual index loops

```rust
// Before
let mut result = Vec::new();
for i in 0..items.len() {
    if items[i].is_active() {
        result.push(items[i].name().to_string());
    }
}

// After
let result: Vec<String> = items.iter()
    .filter(|item| item.is_active())
    .map(|item| item.name().to_string())
    .collect();
```

### Use `collect` with turbofish for type-driven collection

```rust
// Collect into different types by changing the annotation
let names: Vec<_> = items.iter().map(|i| i.name()).collect();
let name_set: HashSet<_> = items.iter().map(|i| i.name()).collect();
let lookup: HashMap<_, _> = items.iter().map(|i| (i.id(), i)).collect();
```

### Use `Iterator::fold` or `sum`/`product` for accumulation

```rust
// Before
let mut total = 0;
for item in &items {
    total += item.price;
}

// After
let total: u64 = items.iter().map(|item| item.price).sum();
```

### Use `chunks` / `windows` for grouped processing

```rust
// Before
for i in 0..data.len() - 1 {
    process_pair(data[i], data[i + 1]);
}

// After
for pair in data.windows(2) {
    process_pair(pair[0], pair[1]);
}
```

---

## 4. Ownership & Borrowing

### Take `&str` instead of `String` in function parameters

```rust
// Before — forces caller to own a String
fn greet(name: String) {
    println!("Hello, {name}");
}

// After — accepts both &str and &String
fn greet(name: &str) {
    println!("Hello, {name}");
}
```

General rule: borrow in parameters unless the function needs ownership (storing in a struct, moving to another thread).

### Use `Cow<str>` when you sometimes need to own

```rust
use std::borrow::Cow;

fn normalize(input: &str) -> Cow<str> {
    if input.contains(' ') {
        Cow::Owned(input.replace(' ', "_"))
    } else {
        Cow::Borrowed(input)
    }
}
```

Avoids allocation when no modification is needed.

### Use `impl Trait` for return types when the concrete type is complex

```rust
// Before — exposes implementation detail
fn active_users(users: &[User]) -> std::iter::Filter<std::slice::Iter<'_, User>, fn(&&User) -> bool> {
    users.iter().filter(|u| u.is_active())
}

// After
fn active_users(users: &[User]) -> impl Iterator<Item = &User> {
    users.iter().filter(|u| u.is_active())
}
```

---

## 5. Structs & Traits

### Use `#[derive]` generously

```rust
// Don't manually implement what derive gives you for free
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct UserId(u64);

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
struct Config {
    timeout_ms: u64,
    max_retries: u32,
    verbose: bool,
}
```

### Use the builder pattern or `Default` + struct update for complex construction

```rust
// Before — long constructors with positional args
let config = Config::new(5000, 3, true, false, "info", None, Some(path));

// After — Default + struct update
let config = Config {
    timeout_ms: 5000,
    max_retries: 3,
    verbose: true,
    ..Config::default()
};
```

### Use `From`/`Into` for type conversions instead of custom methods

```rust
// Before
impl UserId {
    fn from_u64(val: u64) -> Self {
        UserId(val)
    }
    fn to_u64(&self) -> u64 {
        self.0
    }
}

// After
impl From<u64> for UserId {
    fn from(val: u64) -> Self {
        UserId(val)
    }
}
// Now you get Into<UserId> for u64 for free, plus .into() ergonomics
```

---

## 6. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It's Bad | Fix |
|---|---|---|
| `.unwrap()` everywhere | Panics in production | Use `?`, `.unwrap_or()`, `.unwrap_or_default()`, or `expect("reason")` |
| `.clone()` to satisfy the borrow checker | Hides performance costs, often unnecessary | Restructure lifetimes, use references, or `Rc`/`Arc` if shared ownership is needed |
| `&String` as parameter type | Strictly less flexible than `&str` | Use `&str` — it accepts both `&String` and string slices |
| `&Vec<T>` as parameter type | Same issue | Use `&[T]` — it accepts any contiguous sequence |
| `Box<dyn Error>` for all errors | Loses type information | Use `thiserror` for library errors, `anyhow` for application errors |
| `match` on `bool` | Over-engineered | Use `if/else` |
| Manual `Drop` implementation for cleanup | Often unnecessary complexity | Leverage RAII — let the type system handle cleanup |
| `pub` on everything | Exposes too much surface area | Default to private; expose only what's needed |
| `to_string()` on string literals | Unnecessary allocation | Use `&str` or `String::from()` at construction, avoid repeated conversion |
| Nested `match` on multiple Options | Deep nesting | Combine with `zip`, tuple matching, or `let...else` chains |
