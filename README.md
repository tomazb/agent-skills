# Agent Skills

A collection of reusable skills for AI coding agents. Each skill is a self-contained package that enhances an agent's capabilities in a specific domain.

## Available Skills

### [Production Resilience Reviewer](production-resilience-reviewer/)

Senior-level production resilience and failure-mode review for code, services, and system designs. Acts as a hybrid Staff SRE, Principal Engineer, and Incident Commander — finding every way code can fail in production and providing actionable fixes with priority rankings.

**Key capabilities:**

- Reviews code through **eight failure lenses**: dependency failure, load & concurrency, network & latency, data freshness & consistency, retry & backpressure, debuggability, observability & alerting, and change management & rollback safety
- Calibrates severity using impact, likelihood, blast radius, and detectability
- Provides two review modes: **Quick** (top risks, fast pass) and **Full** (deep analysis with validation and monitoring plans)
- Includes specialized detection of common AI-generated code blind spots
- Ships with reference checklists for dependency patterns, data consistency, observability, change management, severity calibration, and validation/monitoring patterns

## Skill Structure

Each skill follows a consistent package layout:

```
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

## License

See individual skill directories for license information.
