# Shell Scripting Simplification Reference

Load this file when the code being simplified is shell script — Bash, POSIX sh, Zsh, or Csh/Tcsh. Shell scripts accumulate cruft fast: copy-pasted blocks, cargo-culted quoting, unnecessary subshells, and fragile parsing. Simplification here means making scripts robust, portable, and readable — not just shorter.

**Important:** Always check the shebang (`#!/bin/bash`, `#!/bin/sh`, `#!/bin/zsh`) before applying Bash-specific features. If the script targets POSIX `sh` or runs on systems where `/bin/sh` is dash/ash (Debian, Ubuntu, Alpine), stick to POSIX-only constructs. Bashisms in a POSIX script are bugs, not simplifications.

## Table of Contents
1. Quoting & Variable Expansion
2. Conditionals & Test Expressions
3. Control Flow
4. String & Path Manipulation
5. Process & Command Patterns
6. Functions
7. Arrays (Bash/Zsh)
8. Portability Notes
9. Common Anti-Patterns → Fixes

---

## 1. Quoting & Variable Expansion

Quoting errors are the #1 source of shell bugs. When in doubt, quote it.

### Always double-quote variable expansions

```bash
# Before — breaks on filenames with spaces, glob characters
cp $file $dest
for f in $files; do

# After
cp "$file" "$dest"
for f in $files; do  # still wrong if $files has spaces — see arrays
```

The only places you intentionally omit quotes: inside `[[ ]]` on the left side (already safe), arithmetic `$(( ))`, and when you deliberately want word splitting (rare — document why).

### Use `${var:-default}` instead of external checks

```bash
# Before
if [ -z "$TIMEOUT" ]; then
    TIMEOUT=30
fi

# After
TIMEOUT="${TIMEOUT:-30}"
```

Related expansions worth knowing:

| Syntax | Meaning |
|---|---|
| `${var:-default}` | Use default if var is unset or empty |
| `${var:=default}` | Assign default if var is unset or empty |
| `${var:+alternate}` | Use alternate if var IS set and non-empty |
| `${var:?error msg}` | Exit with error if var is unset or empty |

### Prefer `$( )` over backticks

```bash
# Before — hard to nest, easy to confuse with single quotes
result=`grep -c "error" \`find /var/log -name "*.log"\``

# After — nests cleanly, visually distinct
result=$(grep -c "error" $(find /var/log -name "*.log"))
```

Backticks are POSIX-compatible but `$()` is also POSIX and universally preferred.

---

## 2. Conditionals & Test Expressions

### Use `[[ ]]` over `[ ]` in Bash/Zsh

`[[ ]]` is a Bash/Zsh keyword (not a command), so it handles quoting, pattern matching, and logical operators more safely:

```bash
# Before — fragile, needs careful quoting
if [ -n "$var" ] && [ "$var" != "none" ]; then

# After (Bash/Zsh) — no word splitting inside [[ ]]
if [[ -n $var && $var != "none" ]]; then
```

Key `[[ ]]` advantages: no word splitting on variables, `&&`/`||` work directly, `=~` for regex, `==` with glob patterns.

**POSIX sh:** Stick with `[ ]` and explicit quoting. Use `-a`/`-o` sparingly (deprecated in some shells) — prefer chained `[ ] && [ ]`.

### Use arithmetic `(( ))` for numeric comparisons

```bash
# Before
if [ "$count" -gt 10 ] && [ "$count" -lt 100 ]; then

# After (Bash/Zsh)
if (( count > 10 && count < 100 )); then
```

Inside `(( ))`, variables don't need `$` prefix, and you get C-like operators (`>`, `<`, `>=`, `==`, `!=`, `%`).

### Simplify flag checking

```bash
# Before
if [ "$verbose" = "true" ] || [ "$verbose" = "yes" ] || [ "$verbose" = "1" ]; then

# After (Bash/Zsh) — case-insensitive pattern matching
if [[ ${verbose,,} =~ ^(true|yes|1)$ ]]; then

# POSIX alternative
case "$verbose" in
    [Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|1) do_verbose=1 ;;
    *) do_verbose=0 ;;
esac
```

---

## 3. Control Flow

### Guard clauses — exit early from functions and scripts

```bash
# Before
process_file() {
    if [ -f "$1" ]; then
        if [ -r "$1" ]; then
            if [ -s "$1" ]; then
                # actual logic 3 levels deep
                ...
            else
                echo "File is empty" >&2
            fi
        else
            echo "File not readable" >&2
        fi
    else
        echo "File not found" >&2
    fi
}

# After
process_file() {
    local file="$1"

    if [[ ! -f $file ]]; then
        echo "File not found: $file" >&2
        return 1
    fi
    if [[ ! -r $file ]]; then
        echo "File not readable: $file" >&2
        return 1
    fi
    if [[ ! -s $file ]]; then
        echo "File is empty: $file" >&2
        return 1
    fi

    # actual logic at top level
    ...
}
```

### Use `case` over if/elif chains for string matching

```bash
# Before
if [ "$action" = "start" ]; then
    start_service
elif [ "$action" = "stop" ]; then
    stop_service
elif [ "$action" = "restart" ]; then
    stop_service
    start_service
elif [ "$action" = "status" ]; then
    show_status
else
    echo "Unknown action: $action" >&2
    exit 1
fi

# After
case "$action" in
    start)   start_service ;;
    stop)    stop_service ;;
    restart) stop_service; start_service ;;
    status)  show_status ;;
    *)
        echo "Unknown action: $action" >&2
        exit 1
        ;;
esac
```

`case` is POSIX, supports glob patterns (`*.txt)`), and is cleaner for multi-branch string dispatch.

### Use `||` and `&&` for simple one-liners

```bash
# Before
if ! mkdir -p "$output_dir"; then
    echo "Failed to create directory" >&2
    exit 1
fi

# After — for simple guard actions
mkdir -p "$output_dir" || { echo "Failed to create directory" >&2; exit 1; }
```

Only use this for one-line consequences. For multi-line error handling, stick with `if`.

---

## 4. String & Path Manipulation

### Use parameter expansion instead of external tools

```bash
# Before — spawns a subshell + process for each operation
filename=$(basename "$path")
extension=$(echo "$filename" | sed 's/.*\.//')
dirname=$(dirname "$path")
name_only=$(echo "$filename" | sed 's/\.[^.]*$//')

# After — pure shell, no subprocesses
filename="${path##*/}"
extension="${filename##*.}"
dirname="${path%/*}"
name_only="${filename%.*}"
```

Key parameter expansion operators:

| Syntax | Result for `path="/home/user/file.tar.gz"` |
|---|---|
| `${path##*/}` | `file.tar.gz` (remove longest prefix match up to `/`) |
| `${path%/*}` | `/home/user` (remove shortest suffix match from `/`) |
| `${path%.gz}` | `/home/user/file.tar` (remove shortest suffix `.gz`) |
| `${path%%.*}` | `/home/user/file` (remove longest suffix from `.`) |
| `${path#*.}` | `tar.gz` (remove shortest prefix up to `.`) |

### String replacement (Bash/Zsh)

```bash
# Before
new_path=$(echo "$path" | sed 's/old/new/g')

# After (Bash/Zsh)
new_path="${path//old/new}"    # global replace
first="${path/old/new}"        # first occurrence only
```

### Uppercase/lowercase (Bash 4+/Zsh)

```bash
# Before
lower=$(echo "$input" | tr '[:upper:]' '[:lower:]')

# After (Bash 4+)
lower="${input,,}"    # all lowercase
upper="${input^^}"    # all uppercase
first="${input^}"     # capitalize first char
```

---

## 5. Process & Command Patterns

### Use `set -euo pipefail` at the top of scripts

```bash
#!/bin/bash
set -euo pipefail

# -e: exit on error (any command returning non-zero)
# -u: treat unset variables as errors
# -o pipefail: a pipeline fails if ANY command in it fails, not just the last
```

This catches entire classes of silent failures. Add `set -x` during debugging (or run with `bash -x script.sh`).

**Caveat:** `set -e` has edge cases (commands in `if` conditions, `||`/`&&` chains, subshells). For critical error handling, still use explicit checks.

### Avoid useless `cat`

```bash
# Before — Useless Use of Cat
cat "$file" | grep "pattern"
cat "$file" | wc -l
cat "$file" | head -20

# After — input redirection or direct argument
grep "pattern" "$file"
wc -l < "$file"
head -20 "$file"
```

### Avoid useless `echo | pipe`

```bash
# Before
echo "$var" | grep -q "pattern"
echo "$var" | cut -d: -f2

# After (Bash/Zsh)
[[ $var == *pattern* ]]    # for simple glob matching
# or
grep -q "pattern" <<< "$var"    # for regex (Bash here-string)
cut -d: -f2 <<< "$var"
```

### Use `command -v` over `which`

```bash
# Before — 'which' is not POSIX, behaves differently across systems
if which docker > /dev/null 2>&1; then

# After — POSIX standard
if command -v docker > /dev/null 2>&1; then
```

### Prefer `find ... -exec` or `-print0 | xargs -0` over `for` loops on find output

```bash
# Before — breaks on filenames with spaces, newlines, or glob characters
for f in $(find /data -name "*.csv"); do
    process "$f"
done

# After (option 1) — built-in exec
find /data -name "*.csv" -exec process {} \;

# After (option 2) — parallel-safe with xargs
find /data -name "*.csv" -print0 | xargs -0 -I{} process {}

# After (option 3, Bash 4+) — globstar
shopt -s globstar nullglob
for f in /data/**/*.csv; do
    process "$f"
done
```

### Use process substitution to avoid subshell variable scoping issues

```bash
# Before — $count is always 0 because pipe creates a subshell
count=0
cat "$file" | while read -r line; do
    (( count++ ))
done
echo "$count"   # prints 0!

# After (Bash/Zsh) — no subshell, variable persists
count=0
while read -r line; do
    (( count++ ))
done < "$file"
echo "$count"   # prints correct count
```

---

## 6. Functions

### Use `local` for all function variables

```bash
# Before — leaks variables into global scope
process() {
    result=""
    temp_file="/tmp/proc.$$"
    # ...
}

# After
process() {
    local result=""
    local temp_file="/tmp/proc.$$"
    # ...
}
```

### Name function arguments immediately

```bash
# Before — positional args are unreadable
deploy() {
    scp "$3" "$1@$2:/opt/app/"
    ssh "$1@$2" "systemctl restart $4"
}

# After
deploy() {
    local user="$1"
    local host="$2"
    local artifact="$3"
    local service="$4"

    scp "$artifact" "${user}@${host}:/opt/app/"
    ssh "${user}@${host}" "systemctl restart ${service}"
}
```

### Return values via stdout, not global variables

```bash
# Before — hidden state coupling
get_version() {
    VERSION=$(cat VERSION)   # sets a global
}
get_version
echo "$VERSION"

# After
get_version() {
    cat VERSION
}
version=$(get_version)
echo "$version"
```

For returning multiple values, use structured output and parse it, or use nameref variables (`local -n` in Bash 4.3+).

---

## 7. Arrays (Bash/Zsh)

Arrays are the correct way to handle lists of items with potential spaces. They are NOT available in POSIX sh.

### Use arrays instead of space-separated strings for lists

```bash
# Before — breaks on items with spaces
files="file one.txt file two.txt file three.txt"
for f in $files; do
    echo "$f"    # prints 6 items, not 3
done

# After
files=("file one.txt" "file two.txt" "file three.txt")
for f in "${files[@]}"; do
    echo "$f"    # prints 3 items correctly
done
```

### Build command arguments with arrays

```bash
# Before — quoting nightmare
cmd="rsync -avz"
if [ "$verbose" = true ]; then cmd="$cmd --progress"; fi
if [ -n "$exclude" ]; then cmd="$cmd --exclude=$exclude"; fi
$cmd "$src" "$dest"   # breaks on paths with spaces

# After
cmd=(rsync -avz)
if [[ $verbose == true ]]; then cmd+=(--progress); fi
if [[ -n $exclude ]]; then cmd+=(--exclude="$exclude"); fi
"${cmd[@]}" "$src" "$dest"
```

### Read file lines into an array

```bash
# Before
IFS=$'\n' lines=($(cat "$file"))   # breaks on glob characters

# After (Bash 4+)
mapfile -t lines < "$file"

# Or (more portable)
lines=()
while IFS= read -r line; do
    lines+=("$line")
done < "$file"
```

---

## 8. Portability Notes

When simplifying, be aware of what's available where:

| Feature | POSIX sh | Bash | Zsh | Csh/Tcsh |
|---|---|---|---|---|
| `[[ ]]` | No | Yes | Yes | No |
| `(( ))` arithmetic | No | Yes | Yes | No (use `@`) |
| Arrays | No | Yes | Yes (1-indexed!) | Yes (syntax differs) |
| `${var,,}` lowercase | No | 4.0+ | Yes | No |
| `local` keyword | Varies | Yes | Yes | No |
| `<<<` here-string | No | Yes | Yes | No |
| Process substitution `<()` | No | Yes | Yes | No |
| `set -o pipefail` | No | Yes | Yes | No |
| `mapfile`/`readarray` | No | 4.0+ | No (use different syntax) | No |

**Zsh gotcha:** Arrays are 1-indexed by default (`$arr[1]` is the first element, not `$arr[0]`). If porting between Bash and Zsh, this is the most common source of off-by-one bugs.

**Csh/Tcsh note:** The Csh family has fundamentally different syntax (no functions, different variable assignment `set var = value`, different control flow). If you encounter Csh scripts, the best simplification is often to rewrite in Bash/POSIX sh — Csh is widely considered unsuitable for scripting (see "Csh Programming Considered Harmful"). Only suggest this rewrite if the user is open to it.

---

## 9. Common Anti-Patterns → Fixes

| Anti-Pattern | Why It's Bad | Fix |
|---|---|---|
| Unquoted `$variable` | Word splitting + glob expansion | Always `"$variable"` |
| `for f in $(find ...)` | Breaks on spaces/newlines in filenames | `find -exec`, `find -print0 \| xargs -0`, or `globstar` |
| `cat file \| grep` | Useless process — grep reads files directly | `grep pattern file` |
| `echo "$var" \| command` | Unnecessary subprocess | `command <<< "$var"` (Bash) or `printf '%s' "$var" \| command` |
| `[ $? -eq 0 ]` after a command | Redundant — `if` already checks exit status | `if command; then` |
| Parsing `ls` output | Breaks on special characters in filenames | Use globs or `find` |
| `grep ... \| wc -l` to check existence | Scans entire file | `grep -q` (exits on first match) or `grep -c` |
| `cd dir && command && cd ..` | Fragile if command fails — you're stuck in `dir` | Use subshell: `(cd dir && command)` or `pushd`/`popd` |
| `eval "$user_input"` | Code injection vulnerability | Avoid `eval` entirely; if unavoidable, sanitize rigorously |
| No `set -e` or error checking | Silent failures cascade | `set -euo pipefail` or explicit `\|\| exit 1` checks |
| `#!/bin/bash` on a POSIX-only script | Unnecessary Bash dependency | Use `#!/bin/sh` if no Bashisms are used |
| Hardcoded `/tmp/myfile` | Race condition, predictable temp names | `mktemp` for temp files/dirs |
| Testing `-z`/`-n` without quotes in `[ ]` | Breaks if variable contains spaces or is empty | `[ -z "$var" ]` or switch to `[[ ]]` |
