# Java Simplification Reference

Load this file when the code being simplified is Java (especially Java 17+ projects using Spring, Jakarta EE, Micronaut, Quarkus, or plain JVM services/libraries).

## Table of Contents
1. Modern Java Idioms
2. Common Anti-Patterns → Fixes
3. When NOT to Simplify

---

## 1. Modern Java Idioms

### Streams for collection transforms (with restraint)

Use streams for straightforward map/filter/group operations where the intent stays obvious.

```java
// Before
List<String> activeUsernames = new ArrayList<>();
for (User user : users) {
    if (user.isActive()) {
        activeUsernames.add(user.getUsername());
    }
}

// After
List<String> activeUsernames = users.stream()
    .filter(User::isActive)
    .map(User::getUsername)
    .toList();
```

Prefer loops when stream chains become hard to read (nested streams, side effects, or heavy branching).

### Optional for explicit absence at API boundaries

Use `Optional<T>` primarily for return values where a value may legitimately be missing.

```java
// Before
User user = repository.findById(id);
if (user != null) {
    return user.getEmail();
}
return null;

// After
return repository.findById(id)
    .map(User::getEmail)
    .orElse(null);
```

Avoid `Optional` as a field type in entities/DTOs unless framework conventions explicitly support it.

### Records for immutable data carriers

Replace boilerplate DTOs/value objects with records when behavior is mostly data-centric.

```java
// Before
public final class PriceQuote {
    private final String sku;
    private final BigDecimal amount;
    private final String currency;
    // constructor + getters + equals/hashCode + toString
}

// After
public record PriceQuote(String sku, BigDecimal amount, String currency) {}
```

### Pattern matching for type-based branching

Use pattern matching (`instanceof`, switch patterns) to reduce casting noise.

```java
// Before
if (event instanceof PaymentFailedEvent) {
    PaymentFailedEvent failed = (PaymentFailedEvent) event;
    audit(failed.orderId(), failed.reason());
}

// After
if (event instanceof PaymentFailedEvent failed) {
    audit(failed.orderId(), failed.reason());
}
```

---

## 2. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It Hurts | Simplification Direction |
|---|---|---|
| Excessive null checks scattered through call chains | Buries core intent and duplicates guard logic | Validate early, use guard clauses, centralize null handling at boundaries, prefer `Optional` for explicit absence |
| Stringly-typed APIs (`Map<String, Object>`, status strings everywhere) | Weak contracts, runtime errors, unclear behavior | Introduce typed request/response objects, enums, and domain-specific value types |
| Verbose builders for tiny objects | Boilerplate obscures what matters | Use constructors/factory methods for small types, or records for immutable carriers |

---

## 3. When NOT to Simplify

Hold back when simplification would fight the platform or remove intentional constraints:

- **Framework conventions**: JPA entity patterns, Jackson/Spring binding expectations, framework-required no-arg constructors, annotation-driven lifecycle hooks.
- **Generated code**: Lombok-generated segments, protobuf/openapi outputs, codegen clients — edit source schemas/templates instead of generated files.
- **Compatibility contracts**: Serialization forms, reflection-dependent naming, API signatures consumed by external clients.
