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

### [Challenging Decisions](challenging-decisions/)

Pressure-testing skill for product, architecture, scope, and sequencing
decisions before reassurance. Helps an agent challenge plausible ideas first and
endorse them only after the choice survives scrutiny.

**Key capabilities:**

- Challenges before agreement instead of leading with reassurance
- Uses named decision lenses to test evidence, scope, timing, complexity,
  reversibility, and opportunity cost
- Surfaces the strongest counterarguments first and states what evidence,
  trigger, or constraint would change the call
- Ends with a forcing question and gives explicit follow-up guidance after the
  user responds

### [How to Speak — Winston Framework](how-to-speak-winston-framework/)

Apply Patrick Winston's MIT presentation framework to craft compelling talks, audit slides, make ideas memorable, structure persuasive presentations, and design teaching props and stories.

**Key capabilities:**

- Implements Winston's complete framework across 10 frameworks and 3 operating modes (Build, Audit, Coach)
- Covers empowerment promises, Star framework, four heuristics, board vs. slides, slide crime audits, props & stories, and how to stop
- Provides structured talk planning, slide auditing with 10 slide crimes, and delivery coaching
- Includes misinterpretation guards for commonly misquoted Winston advice

### [OpenShift Rook](openshift-rook/)

Upstream Rook Ceph lifecycle router for OpenShift/OKD on SNO and multi-node clusters. Starts with a product-ownership gate so ODF-managed clusters hand off to `openshift-odf` instead of mixing raw Rook manifests with OLM-managed state.

**Key capabilities:**

- Routes across install/preflight, OSD disk prep, RBD block, CephFS, RGW/S3 object, expand/shrink, upgrade, backup/DR, maintenance/uninstall, and validation runbooks
- Enforces destructive-disk safety gates (explicit confirmation, `readlink -f`/`lsblk -f`/`wipefs -n` evidence, stable `/dev/disk/by-id/*` paths)
- Covers CDI/KubeVirt VM storage defaults and StorageProfile configuration
- Separates SNO single-replica settings from multi-node production topology

### [OpenShift ODF](openshift-odf/)

Red Hat OpenShift Data Foundation lifecycle skill for internal and external modes on SNO, compact, and multi-node clusters. Manages storage through the `odf-operator`/`ocs-operator` and the `StorageCluster` CR, never raw upstream Rook manifests.

**Key capabilities:**

- Routes across install/preflight, Local Storage Operator disk prep, ceph-rbd block, cephfs filesystem, MCG/NooBaa and RGW object, expansion, upgrade, backup/DR, maintenance, and validation runbooks
- Mirrors the Rook ownership gate in reverse (unmanaged Rook hands off to `openshift-rook`) and forbids hand-editing ODF-owned Rook CRs except the version-scoped SNO workaround
- Captures ODF 4.20/4.22 SNO single-OSD regression evidence and remediation rendering via `scripts/render_sno_remediation.py`
- Enforces OLM-only install/upgrade, SNO replica-count discovery, and single-default-StorageClass safety

### [OpenShift Longhorn](openshift-longhorn/)

Longhorn lifecycle router for OpenShift/OKD covering V1 filesystem and V2 block/SPDK data engines on SNO and multi-node clusters.

**Key capabilities:**

- Routes across install/preflight, V1 filesystem disks, V2 block/SPDK setup, V1↔V2 migration, upgrade, backup/restore/DR, maintenance/uninstall, and validation runbooks
- Enforces destructive-action confirmation, stable `/dev/disk/by-id/*` targeting, and temporary privileged SCC only for SPDK preflight
- Treats StorageClass parameters as effectively immutable (recreate instead of editing) and keeps SNO single-replica defaults out of multi-node plans
- Records observed OpenShift 4.22 SNO / Longhorn v1.12.0 V2 evidence without turning host-specific values into defaults

### [OpenShift LVM Storage](openshift-lvm-storage/)

LVM Storage (LVMS) and TopoLVM lifecycle skill for SNO and multi-node clusters, from volume-group provisioning through filesystem and raw-block volumes.

**Key capabilities:**

- Routes across install/preflight, volume-group/thin-pool provisioning, filesystem and block volumes, expand/shrink, upgrade, backup/DR, maintenance/uninstall, and validation runbooks
- Requires explicit destructive confirmation plus `pvs`/`vgs`/`lvs` evidence for PV/VG/LV operations
- Enforces `volumeBindingMode: WaitForFirstConsumer` for TopoLVM and guards against thin-pool over-provisioning
- Keeps SNO single-node defaults separate from multi-node production plans

### [OpenShift Cluster Health Check](openshift-cluster-health-check/)

Platform-aware OpenShift cluster health diagnostics for control plane, operators, nodes, MCPs, and key platform subsystems across bare metal, virtualized, cloud, and SNO environments. Emphasizes read-only investigation and evidence-based severity classification.

**Key capabilities:**

- Performs structured health checks across cluster version, operators, nodes, MCPs, etcd, authentication, ingress, DNS, networking, storage, monitoring, registry, console, and certificates
- Detects platform topology and infrastructure type (for example BareMetal, VSphere, AWS, Azure, GCP, SNO) and adapts checks accordingly
- Classifies findings into **Healthy**, **Warning**, and **Critical** with explicit blast-radius and impact guidance
- Distinguishes quota/app issues from platform-level failures for pending/crashing pods to avoid false escalation
- Produces actionable output with executive summary, evidence, priority actions, and uncertainty notes

### [OpenShift cert-manager](openshift-cert-manager/)

Red Hat cert-manager Operator and Let's Encrypt lifecycle skill for OpenShift/OKD on SNO and multi-node clusters, from OperatorHub install through platform certificate replacement.

**Key capabilities:**

- Routes across install/preflight, ACME HTTP-01 proof (staging then production), DNS-01 issuers for wildcards and API certs, platform ingress/API cert replacement, validation/troubleshooting, and maintenance/uninstall runbooks
- Enforces staging-before-production issuance, `Ready=True` from the production issuer before touching platform certs, and public TCP `:80` preflight for HTTP-01
- Encodes DNS-01 requirements (`*.apps` wildcards and API serving certs must use DNS-01) and keeps `router-certs-default` for rollback
- Ships discovery helpers (`scripts/discover_tls.py`, `scripts/check_http01_reachability.py`) with unit-tested timeout and JSON-parsing guards

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

Senior-level production resilience and failure-mode review for code, services, and system designs. Acts as a hybrid Staff SRE, Principal Engineer, and Incident Commander — finding material production failure modes and providing evidence-calibrated fixes with priority rankings.

**Key capabilities:**

- Reviews code through **twelve failure lenses**: dependency failure, load & concurrency, network & latency, data freshness & consistency, retry & backpressure, debuggability, observability & alerting, change management & rollback safety, fault domains & disaster recovery, security & abuse as reliability, quota & limit exhaustion, and complexity tax & architecture fit
- Calibrates severity using impact, likelihood, blast radius, detectability, recoverability, and existing controls
- Provides two review modes: **Quick** (top risks, fast pass) and **Full** (deep analysis with validation and monitoring plans)
- Applies heightened resilience scrutiny when code is identified as AI-generated without inferring authorship from code smells
- Ships with reference checklists for all twelve lenses, severity calibration, and validation/monitoring patterns

### [QA Agent](qa-agent/)

Risk-first QA skill for requirement tracing, test planning, defect reproduction, regression control, and evidence-based release decisions.

**Key capabilities:**

- Six operating modes: review, test-plan, execute, regression, bug-hunt, and mode-selection with explicit rules
- Builds risk-based test plans organized by category (happy path, boundary, negative, error handling, concurrency, security, state transitions, data integrity, compatibility, performance)
- Exploratory testing guidance for unexpected inputs, realistic data volumes, adversarial payloads, and UI states
- Structured bug reports with severity calibration, reproduction steps, and evidence
- Test quality standards covering determinism, speed, readability, isolation, maintainability, and trustworthiness
- Special considerations for AI-generated code with 11 blind-spot signals

### [Skill Authoring](skill-authoring/)

Meta-skill for creating and maintaining skills in this collection with in-sync packaging, versioning, and validation.

**Key capabilities:**

- Defines required vs optional package layout (`SKILL.md`, `package.json`, `VERSION`, `CHANGELOG.md`, per-skill `README.md`, plus `references/`, `tools/`, `scripts/`, `assets/`, `tests/`)
- Enforces `Use when...` frontmatter without the legacy `tools` field and concise `SKILL.md` with detail pushed into references or scripts
- Encodes semantic version sync across `VERSION`, `package.json`, `CHANGELOG.md`, and the README version line
- Names the collection validator, isolated test runner, per-skill package check, and the root `README.md` + `AGENTS.md` index sync

## Skill Structure

Each skill follows a consistent package layout:

```text
skill-name/
├── SKILL.md          # Skill definition (frontmatter + instructions)
├── package.json      # Name, version, description, keywords
├── VERSION           # Current version
├── CHANGELOG.md      # Version history
├── README.md         # Per-skill readme with version line
├── references/       # Optional deep-dive reference materials
├── tools/            # Optional validation and utility scripts
├── scripts/          # Optional runtime helper scripts
├── assets/           # Optional static assets
└── tests/            # Adjacent validation/tests
```

## Validation

Install the development/CI dependencies, then run the repository validator and all root/per-skill tests:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_skill_collection.py
python3 scripts/run_test_suite.py
```

The collection validator uses the official `skills-ref` library for Agent Skills frontmatter and
naming validation, then applies repository-specific Markdown and script checks. The test runner
executes each top-level suite in a separate pytest process because independently packaged skills
can intentionally reuse helper module names.

For a package-specific validation pass:

```bash
cd production-resilience-reviewer
bash tools/validate_skill_package.sh
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
