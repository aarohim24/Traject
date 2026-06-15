# Axon Project Governance

This document describes how the Axon project is governed, how decisions are
made, and how contributors can participate in shaping its direction.

---

## Maintainer Responsibilities

Maintainers are trusted contributors who have demonstrated consistent,
high-quality contributions and a thorough understanding of Axon's architecture
and goals. Their responsibilities include:

- **Code review**: Reviewing pull requests for correctness, adherence to
  [coding standards](../standards.md), and alignment with the product vision.
- **Release management**: Cutting releases, updating changelogs, and publishing
  packages to PyPI.
- **Issue triage**: Labelling, prioritizing, and closing issues in a timely manner.
- **RFC facilitation**: Guiding RFC discussions to consensus and ensuring the
  RFC template is followed.
- **Community health**: Enforcing the Code of Conduct and fostering a welcoming
  environment for contributors of all experience levels.
- **Architecture stewardship**: Ensuring Architecture Decision Records (ADRs) are
  respected and updated when decisions change.

Current maintainers are listed in [MAINTAINERS.md](../MAINTAINERS.md).

---

## Decision-Making Process

Axon uses a **consensus-seeking** model with a defined escalation path.

### Day-to-day decisions

Routine changes (bug fixes, documentation improvements, small features that fit
clearly within the existing architecture) are decided by any two maintainers
approving a pull request. No formal process is needed.

### Significant changes

Changes that affect public API contracts, the ADR set, dependency policy, or the
Phase roadmap require a **Request for Comments (RFC)**.  See [RFC Process](#rfc-process)
below.

### Tie-breaking

If consensus cannot be reached, the lead maintainer has final say.  This power
should be used sparingly and with a written explanation committed to the RFC
document.

---

## RFC Process

An RFC (Request for Comments) is required for any proposal that:

- Adds or removes a public API surface.
- Changes the module dependency direction defined in `architecture.md`.
- Introduces a new runtime dependency.
- Alters the Phase roadmap in a material way.
- Changes the telemetry collection policy.

### Submitting an RFC

1. Copy [`RFC_TEMPLATE.md`](RFC_TEMPLATE.md) to `community/rfcs/NNNN-short-title.md`
   (use the next sequential number).
2. Fill in all sections completely.  Incomplete RFCs will not be reviewed.
3. Open a pull request with the RFC document as the only change.
4. Add the `rfc` label to the PR.
5. Announce the RFC in the project's discussion forum (GitHub Discussions).

### RFC lifecycle

| Stage | Description |
|---|---|
| **Draft** | PR opened; community feedback period (minimum 7 days). |
| **Final Comment Period (FCP)** | Maintainer calls FCP; 5-day final review window. |
| **Accepted** | RFC merged; implementation may begin. |
| **Rejected** | RFC closed with written rationale. |
| **Superseded** | A later RFC replaces this one; linked in both documents. |

Implementation PRs must reference the accepted RFC number in their description.

---

## Code of Conduct

All participants in the Axon community are expected to follow the
[Contributor Covenant Code of Conduct](../CODE_OF_CONDUCT.md).

Reports of unacceptable behavior should be directed to the maintainers listed
in [MAINTAINERS.md](../MAINTAINERS.md).  All reports will be handled
confidentially and investigated promptly.

---

## Release Cadence

Axon follows **semantic versioning** (`MAJOR.MINOR.PATCH`).

| Stream | Cadence | Notes |
|---|---|---|
| **Patch** releases | As needed | Bug fixes and security patches only |
| **Minor** releases | End of each Phase | New features, backwards-compatible changes |
| **Major** releases | When breaking changes are unavoidable | Discussed via RFC; migration guide required |

Each release is accompanied by:

- An entry in `CHANGELOG.md` following the [Keep a Changelog](https://keepachangelog.com/) format.
- A signed git tag (`vMAJOR.MINOR.PATCH`).
- A PyPI publish triggered by the `publish.yml` CI workflow.
- A GitHub Release with the changelog entry as the body.

Pre-release versions (`alpha`, `beta`, `rc`) may be published for Phase transitions
when early adopter feedback is needed before a stable release.
