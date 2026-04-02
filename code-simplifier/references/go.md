# Go Simplification Reference

Load this file when the code being simplified is Go. Go has a strong culture of simplicity and explicit code — the language itself resists over-abstraction. Simplification in Go means leaning into this philosophy, not fighting it.

## Table of Contents
1. Idiomatic Go Patterns
2. Error Handling
3. Control Flow
4. Structs & Interfaces
5. Concurrency
6. Common Anti-Patterns → Fixes

---

## 1. Idiomatic Go Patterns

### Use short variable declarations (`:=`) inside functions

```go
// Before
var user User
user = getUser(id)

var err error
_, err = fmt.Println("hello")

// After
user := getUser(id)
_, err := fmt.Println("hello")
```

Reserve `var` for package-level declarations, zero-value initialization where `:=` won't work, or when the type isn't obvious from context.

### Use `fmt.Errorf` with `%w` for error wrapping (Go 1.13+)

```go
// Before
if err != nil {
    return fmt.Errorf("failed to load config: " + err.Error())
}

// After — preserves the error chain for errors.Is/As
if err != nil {
    return fmt.Errorf("loading config: %w", err)
}
```

Convention: error messages start lowercase, no trailing punctuation. The wrapping message adds context about *what was being attempted*, not a generic "failed to".

### Don't stutter in names

```go
// Before — redundant package prefix in names
package user

type UserService struct { ... }
func NewUserService() *UserService { ... }

// After — the package name already provides context
package user

type Service struct { ... }
func NewService() *Service { ... }
```

Callers write `user.NewService()` — the `User` prefix is redundant.

### Prefer `var` block for multiple related declarations

```go
// Before
var ErrNotFound = errors.New("not found")
var ErrUnauthorized = errors.New("unauthorized")
var ErrTimeout = errors.New("timeout")

// After
var (
    ErrNotFound     = errors.New("not found")
    ErrUnauthorized = errors.New("unauthorized")
    ErrTimeout      = errors.New("timeout")
)
```

---

## 2. Error Handling

Error handling is the #1 area where Go code gets noisy. Simplify the noise without hiding errors.

### Don't add context that doesn't help

```go
// Before — the wrap adds nothing useful
data, err := os.ReadFile(path)
if err != nil {
    return nil, fmt.Errorf("error reading file: %w", err)
}

// After — the os error already says "open /path/to/file: no such file or directory"
data, err := os.ReadFile(path)
if err != nil {
    return nil, err
}
```

Wrap errors when you're adding context the caller wouldn't otherwise have (what operation, what entity, what parameters). Don't wrap just to wrap.

### Use `errors.Is` and `errors.As` instead of type assertions

```go
// Before
if err, ok := err.(*os.PathError); ok {
    // handle path error
}

// After — works through wrapped error chains
var pathErr *os.PathError
if errors.As(err, &pathErr) {
    // handle path error
}
```

### Consolidate repetitive error checks when safe

```go
// Before — repetitive pattern in sequential operations
name, err := readName(r)
if err != nil {
    return err
}
age, err := readAge(r)
if err != nil {
    return err
}
email, err := readEmail(r)
if err != nil {
    return err
}

// After — use a scanner/reader pattern if the operations share error handling
type fieldReader struct {
    r   io.Reader
    err error
}

func (fr *fieldReader) readString() string {
    if fr.err != nil {
        return ""
    }
    var s string
    s, fr.err = readString(fr.r)
    return s
}
```

This pattern (used by `bufio.Scanner`, `encoding/binary`) consolidates error checks. Only use it when the operations are truly sequential and share error handling logic.

---

## 3. Control Flow

### Early return — the core Go pattern

```go
// Before
func processOrder(order *Order) error {
    if order != nil {
        if order.IsValid() {
            if order.HasItems() {
                // actual logic here
                return nil
            }
            return errors.New("no items")
        }
        return errors.New("invalid order")
    }
    return errors.New("nil order")
}

// After
func processOrder(order *Order) error {
    if order == nil {
        return errors.New("nil order")
    }
    if !order.IsValid() {
        return errors.New("invalid order")
    }
    if !order.HasItems() {
        return errors.New("no items")
    }
    // actual logic here
    return nil
}
```

### Use `switch` with no condition for complex if/else chains

```go
// Before
if score >= 90 {
    grade = "A"
} else if score >= 80 {
    grade = "B"
} else if score >= 70 {
    grade = "C"
} else {
    grade = "F"
}

// After
switch {
case score >= 90:
    grade = "A"
case score >= 80:
    grade = "B"
case score >= 70:
    grade = "C"
default:
    grade = "F"
}
```

### Use `if` with initializer to limit variable scope

```go
// Before
err := doSomething()
if err != nil {
    return err
}
// err is still in scope here, polluting the namespace

// After
if err := doSomething(); err != nil {
    return err
}
```

---

## 4. Structs & Interfaces

### Keep interfaces small — the Go way

```go
// Before — God interface
type DataStore interface {
    Get(key string) ([]byte, error)
    Set(key string, value []byte) error
    Delete(key string) error
    List(prefix string) ([]string, error)
    Watch(key string) <-chan Event
    Backup(path string) error
    Restore(path string) error
    Stats() StoreStats
}

// After — compose from small interfaces
type Reader interface {
    Get(key string) ([]byte, error)
}

type Writer interface {
    Set(key string, value []byte) error
    Delete(key string) error
}

type ReadWriter interface {
    Reader
    Writer
}
```

Accept interfaces, return structs. Define interfaces where they're consumed, not where they're implemented.

### Use functional options for complex constructors

```go
// Before — boolean/config explosion
func NewServer(addr string, port int, tls bool, timeout time.Duration, maxConn int) *Server

// After
type Option func(*Server)

func WithTLS() Option              { return func(s *Server) { s.tls = true } }
func WithTimeout(d time.Duration) Option { return func(s *Server) { s.timeout = d } }
func WithMaxConn(n int) Option     { return func(s *Server) { s.maxConn = n } }

func NewServer(addr string, port int, opts ...Option) *Server {
    s := &Server{addr: addr, port: port, timeout: 30 * time.Second, maxConn: 100}
    for _, opt := range opts {
        opt(s)
    }
    return s
}
```

### Use struct embedding for composition, not inheritance

```go
// Before — manual delegation
type AuthenticatedClient struct {
    client *http.Client
    token  string
}

func (ac *AuthenticatedClient) Do(req *http.Request) (*http.Response, error) {
    req.Header.Set("Authorization", "Bearer "+ac.token)
    return ac.client.Do(req)
}

func (ac *AuthenticatedClient) Get(url string) (*http.Response, error) {
    return ac.client.Get(url) // oops, forgot auth header
}
```

For this pattern, consider embedding `http.Client` directly or using a `RoundTripper` — which is the idiomatic way to add middleware to HTTP clients in Go.

---

## 5. Concurrency

### Don't start goroutines without a shutdown plan

```go
// Before — goroutine leak
func startWorker(ch <-chan Job) {
    go func() {
        for job := range ch {
            process(job)
        }
    }()
}

// After — context-aware with WaitGroup
func startWorker(ctx context.Context, ch <-chan Job, wg *sync.WaitGroup) {
    wg.Add(1)
    go func() {
        defer wg.Done()
        for {
            select {
            case <-ctx.Done():
                return
            case job, ok := <-ch:
                if !ok {
                    return
                }
                process(job)
            }
        }
    }()
}
```

### Use `errgroup` for concurrent tasks with error propagation

```go
// Before — manual goroutine + error handling
var wg sync.WaitGroup
errs := make(chan error, 3)
wg.Add(3)
go func() { defer wg.Done(); errs <- fetchUsers(ctx) }()
go func() { defer wg.Done(); errs <- fetchOrders(ctx) }()
go func() { defer wg.Done(); errs <- fetchProducts(ctx) }()
wg.Wait()
close(errs)
for err := range errs {
    if err != nil {
        return err
    }
}

// After
g, ctx := errgroup.WithContext(ctx)
g.Go(func() error { return fetchUsers(ctx) })
g.Go(func() error { return fetchOrders(ctx) })
g.Go(func() error { return fetchProducts(ctx) })
if err := g.Wait(); err != nil {
    return err
}
```

---

## 6. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It's Bad | Fix |
|---|---|---|
| `if err != nil { return err }` after every line | Noisy but sometimes necessary | Consolidate with helper patterns where feasible; otherwise accept it — it's idiomatic Go |
| `interface{}` / `any` everywhere | Loses type safety | Use generics (Go 1.18+) or concrete types |
| `init()` functions with side effects | Hidden execution order, hard to test | Explicit initialization in `main()` |
| Channels for simple mutual exclusion | Overcomplication | Use `sync.Mutex` |
| Named returns for non-trivial functions | Confusing scope, accidental naked returns | Use named returns only for short functions or `defer` error wrapping |
| `panic` for expected errors | Crashes the program | Return `error` — reserve `panic` for truly unrecoverable states |
| `strings.Contains` chain for parsing | Fragile, incomplete | Use proper parsing (regex, `strings.Cut`, or a real parser) |
| Global `sync.Mutex` protecting a map | Hidden coupling | Encapsulate in a struct with methods |
