# TypeScript / JavaScript Simplification Reference

Load this file when the code being simplified is TypeScript or JavaScript (including React, Node.js, Deno, Bun).

## Table of Contents
1. Modern Syntax Upgrades
2. Type System Leverage (TS only)
3. Control Flow Patterns
4. Async Patterns
5. React-Specific Patterns
6. Node.js / Server Patterns
7. Common Anti-Patterns → Fixes

---

## 1. Modern Syntax Upgrades

These are safe, mechanical transforms. Apply them unless the project targets an environment without support.

### Optional chaining and nullish coalescing

```typescript
// Before
const city = user && user.address && user.address.city;
const name = options.name !== null && options.name !== undefined ? options.name : 'default';

// After
const city = user?.address?.city;
const name = options.name ?? 'default';
```

Note: `??` is NOT the same as `||`. `||` treats `0`, `''`, and `false` as falsy. `??` only treats `null` and `undefined` as nullish. Don't blindly replace `||` with `??` — check whether the code intentionally treats falsy values as "missing."

### Destructuring where it reduces repetition

```typescript
// Before
const name = props.name;
const age = props.age;
const isActive = props.isActive;

// After
const { name, age, isActive } = props;
```

Don't destructure when it would create ambiguous variable names pulled from deep nesting, or when only one property is used.

### Template literals over concatenation

```typescript
// Before
const msg = 'Hello ' + user.name + ', you have ' + count + ' items.';

// After
const msg = `Hello ${user.name}, you have ${count} items.`;
```

### Object shorthand

```typescript
// Before
return { name: name, age: age, isActive: isActive };

// After
return { name, age, isActive };
```

---

## 2. Type System Leverage (TypeScript)

### Replace runtime type checks with compile-time types

```typescript
// Before — runtime defensive coding because types are vague
function process(input: any) {
  if (typeof input !== 'string') throw new Error('Expected string');
  return input.trim();
}

// After — let the type system do the work
function process(input: string): string {
  return input.trim();
}
```

Only apply this when you're confident the caller is also typed. If the function sits at a boundary (API handler, event listener, user input), runtime validation is still needed.

### Use discriminated unions over stringly-typed flags

```typescript
// Before
type Event = {
  type: string;
  payload: any;
};

// After
type Event =
  | { type: 'click'; x: number; y: number }
  | { type: 'keypress'; key: string }
  | { type: 'scroll'; delta: number };
```

This gives you exhaustiveness checking in `switch` statements for free.

### Prefer `satisfies` over `as` for type assertion

```typescript
// Before — silently allows wrong shapes
const config = { port: 3000, host: 'localhost' } as ServerConfig;

// After — validates shape at compile time, preserves literal types
const config = { port: 3000, host: 'localhost' } satisfies ServerConfig;
```

### Use `readonly` and `as const` to signal intent

```typescript
// When a value should never change
const ALLOWED_ROLES = ['admin', 'editor', 'viewer'] as const;
type Role = (typeof ALLOWED_ROLES)[number]; // 'admin' | 'editor' | 'viewer'
```

---

## 3. Control Flow Patterns

### Early returns over nested conditionals

This is the single most impactful simplification pattern. See the main SKILL.md for the general principle — here's the TS-specific flavor:

```typescript
// Before
function getDiscount(user: User): number {
  if (user) {
    if (user.membership) {
      if (user.membership.isActive) {
        if (user.membership.tier === 'premium') {
          return 0.2;
        } else {
          return 0.1;
        }
      }
    }
  }
  return 0;
}

// After
function getDiscount(user: User): number {
  if (!user?.membership?.isActive) return 0;
  return user.membership.tier === 'premium' ? 0.2 : 0.1;
}
```

### Switch over if-else chains for 3+ branches

```typescript
// Before
if (status === 'pending') {
  handlePending();
} else if (status === 'active') {
  handleActive();
} else if (status === 'suspended') {
  handleSuspended();
} else if (status === 'cancelled') {
  handleCancelled();
} else {
  handleUnknown();
}

// After
switch (status) {
  case 'pending':    return handlePending();
  case 'active':     return handleActive();
  case 'suspended':  return handleSuspended();
  case 'cancelled':  return handleCancelled();
  default:           return handleUnknown();
}
```

### Lookup objects over switch for pure mappings

When a switch/if-chain just maps values to values with no logic:

```typescript
// Before
function getStatusColor(status: string): string {
  switch (status) {
    case 'success': return 'green';
    case 'warning': return 'yellow';
    case 'error':   return 'red';
    default:        return 'gray';
  }
}

// After
const STATUS_COLORS: Record<string, string> = {
  success: 'green',
  warning: 'yellow',
  error: 'red',
};

function getStatusColor(status: string): string {
  return STATUS_COLORS[status] ?? 'gray';
}
```

---

## 4. Async Patterns

### Avoid `.then()` chains — use async/await

```typescript
// Before
function fetchUser(id: string) {
  return fetch(`/api/users/${id}`)
    .then(res => {
      if (!res.ok) throw new Error('Failed');
      return res.json();
    })
    .then(data => data.user)
    .catch(err => {
      console.error(err);
      return null;
    });
}

// After
async function fetchUser(id: string): Promise<User | null> {
  try {
    const res = await fetch(`/api/users/${id}`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();
    return data.user;
  } catch (err) {
    console.error(err);
    return null;
  }
}
```

### Use `Promise.all` for independent async operations

```typescript
// Before — sequential when it doesn't need to be
const users = await fetchUsers();
const orders = await fetchOrders();
const products = await fetchProducts();

// After — parallel
const [users, orders, products] = await Promise.all([
  fetchUsers(),
  fetchOrders(),
  fetchProducts(),
]);
```

Only do this when the calls are genuinely independent. If `fetchOrders` depends on `users`, keep it sequential.

### Avoid `async` on functions that don't `await`

```typescript
// Before — misleading, wraps return in an extra Promise
async function getDefaultConfig() {
  return { timeout: 5000 };
}

// After
function getDefaultConfig() {
  return { timeout: 5000 };
}
```

---

## 5. React-Specific Patterns

### Extract complex conditions from JSX

```typescript
// Before
return (
  <div>
    {user && user.isActive && user.permissions.includes('edit') && !isReadOnly && (
      <EditButton onClick={handleEdit} />
    )}
  </div>
);

// After
const canEdit = user?.isActive
  && user.permissions.includes('edit')
  && !isReadOnly;

return (
  <div>
    {canEdit && <EditButton onClick={handleEdit} />}
  </div>
);
```

### Avoid inline object/array literals in JSX props

These create new references every render, breaking `React.memo` and `useMemo` dependencies:

```typescript
// Before — new object every render
<Chart options={{ animate: true, color: 'blue' }} />

// After — stable reference
const chartOptions = useMemo(() => ({ animate: true, color: 'blue' }), []);
<Chart options={chartOptions} />
```

Only flag this when the component is known to be expensive or wrapped in `memo`. Don't prematurely optimize every prop.

### Simplify state that derives from other state

```typescript
// Before — redundant state that can get out of sync
const [items, setItems] = useState<Item[]>([]);
const [itemCount, setItemCount] = useState(0);

useEffect(() => {
  setItemCount(items.length);
}, [items]);

// After — derived value, always in sync
const [items, setItems] = useState<Item[]>([]);
const itemCount = items.length;
```

### Prefer explicit Props types

```typescript
// Before
function UserCard({ name, age, isActive }: { name: string; age: number; isActive: boolean }) {

// After
interface UserCardProps {
  name: string;
  age: number;
  isActive: boolean;
}

function UserCard({ name, age, isActive }: UserCardProps) {
```

This is especially important when props are reused across components or the list exceeds 3 properties.

---

## 6. Node.js / Server Patterns

### Use `URL` over string manipulation for URLs

```typescript
// Before
const url = baseUrl + '/api/v2/' + resource + '?page=' + page + '&limit=' + limit;

// After
const url = new URL(`/api/v2/${resource}`, baseUrl);
url.searchParams.set('page', String(page));
url.searchParams.set('limit', String(limit));
```

### Prefer `using` (explicit resource management) in TS 5.2+

```typescript
// Before
const file = await open('data.txt');
try {
  const content = await file.readFile('utf-8');
  return content;
} finally {
  await file.close();
}

// After (TS 5.2+ / Node 22+)
await using file = await open('data.txt');
const content = await file.readFile('utf-8');
return content;
```

Only apply if the project's TS version supports it.

---

## 7. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It's Bad | Fix |
|---|---|---|
| `arr.filter(...).length > 0` | Iterates entire array just to check existence | `arr.some(...)` |
| `arr.filter(...)[0]` | Iterates entire array to find first match | `arr.find(...)` |
| `JSON.parse(JSON.stringify(obj))` for cloning | Loses functions, dates, undefined; slow | `structuredClone(obj)` (modern) |
| `!!(condition)` for boolean coercion | Obscure, just saves a few chars | `Boolean(condition)` or explicit check |
| `arr.reduce(...)` for building arrays/objects | Hard to read for non-trivial logic | Use a `for...of` loop with explicit accumulation |
| `new Promise((resolve) => { ... resolve(value) })` wrapping an already-async operation | Unnecessary Promise constructor | Just return/await the async operation directly |
| `catch (e) { throw e; }` | Pointless — does nothing | Remove the try/catch entirely |
| `if (x === true)` / `if (x === false)` | Redundant comparison for boolean values | `if (x)` / `if (!x)` |
