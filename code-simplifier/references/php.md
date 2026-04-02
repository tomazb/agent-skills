# PHP Simplification Reference

Load this file when the code being simplified is PHP, including Composer-based
applications and common ecosystems such as Laravel, Symfony, and WordPress.
Simplification in PHP should reduce branching, indirection, and magic without
rewriting framework conventions or changing runtime behavior.

## Table of Contents
1. Control Flow & Null Handling
2. Conditionals & Data Access
3. Arrays, Collections, and Local Data Shaping
4. Functions, Methods, and Local Helpers
5. Exceptions & Error Handling
6. Framework-Aware Cautions
7. Common Anti-Patterns -> Fixes

---

## 1. Control Flow & Null Handling

### Prefer guard clauses over nested positive checks

```php
// Before
function sendReceipt(?User $user, Order $order): void
{
    if ($user !== null) {
        if ($user->email !== null) {
            if ($order->isPaid()) {
                $this->mailer->send($user->email, $order);
            }
        }
    }
}

// After
function sendReceipt(?User $user, Order $order): void
{
    if ($user === null || $user->email === null) {
        return;
    }
    if (! $order->isPaid()) {
        return;
    }

    $this->mailer->send($user->email, $order);
}
```

This is usually the highest-value PHP simplification. It reduces indentation and
keeps the main path visible.

### Use the nullsafe operator when it actually matches the semantics

```php
// Before
$city = null;
if ($user !== null && $user->profile !== null) {
    $city = $user->profile->city;
}

// After
$city = $user?->profile?->city;
```

Do not replace explicit null checks when the original code also performs logging,
fallback assignment, mutation, or validation side effects.

### Use `??` and `??=` only for null-or-missing fallbacks

```php
// Before
$timezone = isset($settings['timezone']) ? $settings['timezone'] : 'UTC';
if (! isset($config['retry_limit'])) {
    $config['retry_limit'] = 3;
}

// After
$timezone = $settings['timezone'] ?? 'UTC';
$config['retry_limit'] ??= 3;
```

As in JavaScript, `??` is not the same as `?:` or `||`. Keep the original logic
when `''`, `0`, or `false` are intentionally treated as missing.

### Use `match` for value-based branching, not for side-effect mazes

```php
// Before
switch ($status) {
    case 'draft':
        $label = 'Draft';
        break;
    case 'published':
        $label = 'Published';
        break;
    default:
        $label = 'Unknown';
        break;
}

// After
$label = match ($status) {
    'draft' => 'Draft',
    'published' => 'Published',
    default => 'Unknown',
};
```

`match` is useful when each branch computes one value. If each branch performs
multiple statements, a normal `if`/`elseif` or `switch` is often clearer.

---

## 2. Conditionals & Data Access

### Name complex booleans before branching on them

```php
// Before
if (
    $user !== null
    && $user->isActive()
    && ! $user->isBanned()
    && $request->hasValidSignature()
) {
    // ...
}

// After
$canProcessRequest = $user !== null
    && $user->isActive()
    && ! $user->isBanned()
    && $request->hasValidSignature();

if ($canProcessRequest) {
    // ...
}
```

Do this when the boolean expression has real business meaning, not for every
two-term conditional.

### Collapse repeated array lookups when the value is conceptually one thing

```php
// Before
if (! isset($payload['customer']['email'])) {
    return null;
}

$email = trim($payload['customer']['email']);

// After
$email = $payload['customer']['email'] ?? null;
if ($email === null) {
    return null;
}

$email = trim($email);
```

This reduces repeated indexing and makes the validation path easier to follow.

### Keep boundary validation explicit

```php
// Before
$name = $payload['name'] ?? '';
return trim($name);
```

```php
// Better when this is an input boundary
if (! array_key_exists('name', $payload) || ! is_string($payload['name'])) {
    throw new InvalidArgumentException('Missing required name.');
}

return trim($payload['name']);
```

Do not simplify away validation that protects an external contract, even if it
makes the happy path look shorter.

---

## 3. Arrays, Collections, and Local Data Shaping

### Prefer built-ins for direct transforms, but stop before it becomes puzzle code

```php
// Before
$names = [];
foreach ($users as $user) {
    if (! $user->isArchived()) {
        $names[] = $user->name;
    }
}

// After
$activeUsers = array_filter($users, static fn (User $user): bool => ! $user->isArchived());
$names = array_map(static fn (User $user): string => $user->name, $activeUsers);
```

This is clearer when each step has one obvious purpose. For multi-step filtering,
normal loops are often easier to read and debug.

### Keep associative-array reshaping obvious

```php
// Before
$response = [];
$response['id'] = $order->id;
$response['status'] = $order->status;
$response['total'] = $order->totalAmount();

// After
$response = [
    'id' => $order->id,
    'status' => $order->status,
    'total' => $order->totalAmount(),
];
```

### Use local variables when nested data access obscures intent

```php
// Before
return [
    'country' => $payload['shipping_address']['country'] ?? null,
    'postal_code' => $payload['shipping_address']['postal_code'] ?? null,
];

// After
$shippingAddress = $payload['shipping_address'] ?? [];

return [
    'country' => $shippingAddress['country'] ?? null,
    'postal_code' => $shippingAddress['postal_code'] ?? null,
];
```

### Avoid clever one-liners for mixed filtering and mutation

```php
// Before
$result = array_map(
    static fn (array $item): array => ['id' => $item['id'], 'name' => trim($item['name'])],
    array_filter($items, static fn (array $item): bool => isset($item['id'], $item['name']))
);
```

```php
// After
$result = [];
foreach ($items as $item) {
    if (! isset($item['id'], $item['name'])) {
        continue;
    }

    $result[] = [
        'id' => $item['id'],
        'name' => trim($item['name']),
    ];
}
```

In PHP, loop-based code is often the simpler option once the transformation does
more than one thing.

---

## 4. Functions, Methods, and Local Helpers

### Extract a helper only when it creates a real nameable concept

```php
// Before
public function handle(array $payload): void
{
    $userId = isset($payload['user_id']) ? (int) $payload['user_id'] : 0;
    if ($userId <= 0) {
        throw new InvalidArgumentException('Invalid user id.');
    }

    $email = isset($payload['email']) ? trim((string) $payload['email']) : '';
    if ($email === '') {
        throw new InvalidArgumentException('Invalid email.');
    }

    // ...
}
```

```php
// After
public function handle(array $payload): void
{
    $userId = $this->requirePositiveInt($payload, 'user_id');
    $email = $this->requireTrimmedString($payload, 'email');

    // ...
}
```

Good extraction reduces noise in the caller. Bad extraction just moves two lines
into a helper with a vague name like `processData()`.

### Remove pass-through wrappers that add no meaning

```php
// Before
public function findUserById(int $id): ?User
{
    return $this->userRepository->find($id);
}

// After
// Inline the repository call at the only call site when this wrapper adds no
// policy, validation, caching, or business meaning.
```

Do not remove wrappers that exist for transaction boundaries, authorization,
telemetry, caching, or compatibility with older call sites.

### Prefer dependency-local clarity over static helper sprawl

```php
// Before
$name = StringHelper::normalize(UserHelper::displayName($user));

// After
$displayName = $user->displayName();
$name = $this->nameNormalizer->normalize($displayName);
```

If the codebase already uses facades or static helpers heavily, simplify within
that style unless the user explicitly asked for a deeper architectural cleanup.

---

## 5. Exceptions & Error Handling

### Catch only when you are adding useful context or branching behavior

```php
// Before
try {
    return $client->request($request);
} catch (Throwable $e) {
    throw $e;
}

// After
return $client->request($request);
```

### Add context when the caller would otherwise lose the operation being attempted

```php
// Before
try {
    $contents = $filesystem->read($path);
} catch (FilesystemException $e) {
    throw $e;
}

// After
try {
    $contents = $filesystem->read($path);
} catch (FilesystemException $e) {
    throw new RuntimeException(sprintf('Reading config file failed: %s', $path), 0, $e);
}
```

Keep exception types consistent with the surrounding codebase. In Symfony, Laravel,
or framework code, project-specific exception conventions usually matter more than
personal style.

### Preserve behavior around `finally`, logging, and retry logic

```php
// Before
try {
    $job->run();
} catch (Throwable $e) {
    $logger->error('Job failed', ['job' => $job->id(), 'exception' => $e]);
    throw $e;
} finally {
    $lock->release();
}
```

Do not "simplify" this into a bare `$job->run()` call unless you have confirmed the
logging and lock release are redundant elsewhere.

---

## 6. Framework-Aware Cautions

### Respect the framework's normal extension points

- In Laravel, do not replace Eloquent scopes, form requests, policies, container
  injection, or collection pipelines with ad hoc helpers just because plain PHP
  could express the same behavior.
- In Symfony, keep service boundaries, DTOs, event subscribers, serializer rules,
  and configuration-driven wiring intact unless the user asked for a broader refactor.
- In WordPress, preserve hook names, callback signatures, escaping/sanitization,
  and compatibility shims for older core/plugin contracts.

### Be careful with magic that carries framework semantics

Examples:

- Eloquent attribute accessors/mutators
- Symfony parameter conversion or serializer groups
- WordPress filters and action priorities
- Doctrine lazy-loading or lifecycle hooks

These can look indirect or repetitive, but they often encode behavior outside the
local file. Simplify around them, not through them, unless you can verify the full
contract.

### Prefer codebase conventions over generic PHP advice

If a project consistently uses collections, value objects, readonly DTOs, request
objects, or specific exception hierarchies, simplify within those conventions
instead of normalizing everything to plain arrays and utility functions.

---

## 7. Common Anti-Patterns -> Fixes

| Anti-pattern | Why it hurts readability | Preferred simplification |
|---|---|---|
| Deeply nested `if` trees | Hides the main path | Use guard clauses and early returns |
| Repeated `isset($a['b']['c']) ? ... : ...` patterns | Repeats structure and intent | Pull the sub-array or use `??` when semantics match |
| `switch` used only to assign one value | Verbose boilerplate | Use `match` |
| Over-chained array helpers for multi-step transforms | Hard to debug and mentally parse | Use a `foreach` loop with explicit steps |
| Static helper chains with vague names | Hides where behavior lives | Use clear locals or named collaborators |
| `catch` / `throw` with no added value | Adds noise, hides useful flow | Remove the catch block |
| Boundary validation collapsed into defaults | Changes semantics or hides bad input | Keep validation explicit |

## PHP Simplification Checklist

Before finalizing a PHP simplification:

- Confirm whether null, missing, empty string, `0`, and `false` are intentionally
  distinct in this code path.
- Check whether framework magic, hooks, scopes, or accessors are carrying hidden
  behavior.
- Prefer local clarity over clever chained helpers.
- Keep boundary validation, sanitization, escaping, and authorization logic
  explicit.
- Preserve exception type, logging, and cleanup behavior unless the user asked for
  a semantic change.
