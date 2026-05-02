# Agent Skills

A collection of reusable skills for AI coding agents. Each skill is a self-contained package that enhances an agent's capabilities in a specific domain.

## Available Skills

### [Code Simplifier](code-simplifier/)

Behavior-preserving code simplification and readability-focused refactoring for
day-to-day coding work. Helps turn dense, nested, or inconsistent code into
clearer local code without broadening scope or inventing unnecessary abstractions.

**Key capabilities:**

- Supports both review-only and direct-edit workflows for cleanup tasks
- Prioritizes high-value readability wins such as flattening nesting, removing dead
  code, clarifying naming, and reducing needless indirection
- Loads language-specific guidance for TypeScript/JavaScript, PHP, Python, Go,
  Rust, and shell scripting from `references/`
- Treats behavior preservation, scope discipline, and validation status as explicit
  parts of the skill contract

### [How to Speak — Winston Framework](how-to-speak-winston-framework/)

Apply Patrick Winston's MIT presentation framework to craft compelling talks, audit slides, make ideas memorable, structure persuasive presentations, and design teaching props and stories.

**Key capabilities:**

- Implements Winston's complete framework across 10 frameworks and 3 operating modes (Build, Audit, Coach)
- Covers empowerment promises, Star framework, four heuristics, board vs. slides, slide crime audits, props & stories, and how to stop
- Provides structured talk planning, slide auditing with 10 slide crimes, and delivery coaching
- Includes misinterpretation guards for commonly misquoted Winston advice

### [OpenShift Cluster Health Check](openshift-cluster-health-check/)

Platform-aware OpenShift cluster health diagnostics for control plane, operators, nodes, MCPs, and key platform subsystems across bare metal, virtualized, cloud, and SNO environments. Emphasizes read-only investigation and evidence-based severity classification.

**Key capabilities:**

- Performs structured health checks across cluster version, operators, nodes, MCPs, etcd, authentication, ingress, DNS, networking, storage, monitoring, registry, console, and certificates
- Detects platform topology and infrastructure type (for example BareMetal, VSphere, AWS, Azure, GCP, SNO) and adapts checks accordingly
- Classifies findings into **Healthy**, **Warning**, and **Critical** with explicit blast-radius and impact guidance
- Distinguishes quota/app issues from platform-level failures for pending/crashing pods to avoid false escalation
- Produces actionable output with executive summary, evidence, priority actions, and uncertainty notes

### [PR Comments](pr-comments/)

Fetch and display GitHub PR review comments for the current branch in the code review UI, enabling inspection of feedback before deciding how to respond.

**Key capabilities:**

- Verifies `gh` CLI authentication before making API calls
- Fetches issue comments, diff comments, and reviews via the GitHub API with pagination support
- Trims large diff hunks to a focused window around commented lines
- Supports both script-based fetching and manual fallback commands
- Renders comments via `insert_code_review_comments` with proper location and reply metadata

### [OpenShift Versions](openshift-versions/)

Version-discovery and upgrade-path skill for OpenShift releases using Red Hat APIs. Supports unauthenticated public upgrade graph queries and authenticated metadata queries for detailed lifecycle and managed-service availability information.

**Key capabilities:**

- Discovers currently active OpenShift minor and latest patch versions dynamically (without hardcoded release assumptions)
- Queries channel-specific release availability (`stable`, `fast`, `candidate`, `eus`) across architectures
- Computes valid one-hop upgrade targets from a given current version using the public upgrade graph
- Supports authenticated `clusters_mgmt` lookups for ROSA/HCP enablement flags and end-of-life metadata
- Provides script-based and raw API workflows for both human-readable and JSON-parseable outputs

### [Production Resilience Reviewer](production-resilience-reviewer/)

Senior-level production resilience and failure-mode review for code, services, and system designs. Acts as a hybrid Staff SRE, Principal Engineer, and Incident Commander — finding every way code can fail in production and providing actionable fixes with priority rankings.

**Key capabilities:**

- Reviews code through **eleven failure lenses**: dependency failure, load & concurrency, network & latency, data freshness & consistency, retry & backpressure, debuggability, observability & alerting, change management & rollback safety, fault domains & disaster recovery, security & abuse as reliability, and quota & limit exhaustion
- Calibrates severity using impact, likelihood, blast radius, and detectability
- Provides two review modes: **Quick** (top risks, fast pass) and **Full** (deep analysis with validation and monitoring plans)
- Includes specialized detection of common AI-generated code blind spots
- Ships with reference checklists for dependency patterns, data consistency, observability, change management, disaster recovery, security/abuse resilience, quota exhaustion, severity calibration, and validation/monitoring patterns

### [QA Agent](qa-agent/)

Risk-first QA skill for requirement tracing, test planning, defect reproduction, regression control, and evidence-based release decisions.

**Key capabilities:**

- Six operating modes: review, test-plan, execute, regression, bug-hunt, and mode-selection with explicit rules
- Builds risk-based test plans organized by category (happy path, boundary, negative, error handling, concurrency, security, state transitions, data integrity, compatibility, performance)
- Exploratory testing guidance for unexpected inputs, realistic data volumes, adversarial payloads, and UI states
- Structured bug reports with severity calibration, reproduction steps, and evidence
- Test quality standards covering determinism, speed, readability, isolation, maintainability, and trustworthiness
- Special considerations for AI-generated code with 11 blind-spot signals

## Skill Structure

Each skill follows a consistent package layout:

```text
skill-name/
├── SKILL.md          # Skill definition (frontmatter + instructions)
├── package.json      # Name, version, description, keywords
├── VERSION           # Current version
├── CHANGELOG.md      # Version history
├── references/       # Deep-dive reference materials
└── tools/            # Validation and utility scripts
```

## Validation

Skills include validation tooling to check package integrity:

```bash
cd production-resilience-reviewer
bash tools/validate_skill_package.sh
```

For a lightweight repo-wide validation pass across all skill directories:

```bash
python3 scripts/validate_skill_collection.py
```

## Packaging

Generated `.skill` bundles are treated as build artifacts, not source files.
Build them locally into `dist/` with:

```bash
python3 scripts/build_skill_artifacts.py
```

CI also builds these bundles and publishes them as workflow artifacts. Tagged
`v*` releases attach the generated `.skill` files to the GitHub release.

## License

See individual skill directories for license information.
