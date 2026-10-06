# Security policy

Ayurnidaan handles health data, so security reports get priority.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through
[GitHub private vulnerability reporting](https://github.com/Worldisbinary/ayurnidaan/security/advisories/new).
Include the affected endpoint or file, steps to reproduce, and the impact you expect.

| Step | Target |
|---|---|
| Acknowledgement | within 3 days |
| Assessment and severity (CVSS) | within 7 days |
| Fix for critical / high | within 14 days |
| Public advisory and credit | after the fix ships, if you want credit |

Testing in good faith is welcome **against a local copy** (`start-local.ps1`, or
`docker run`). Do not test against the production deployment: it may hold real patients'
health data. Never access, change or keep data that is not yours.

## Supported versions

Only the latest release on `main` gets security fixes.

## How the project protects data

| Area | Control |
|---|---|
| Identity | scrypt password hashing; short-lived JWT access tokens plus revocable refresh tokens (`token_version`) |
| Access | role-based (patient / practitioner / admin); practitioners must be verified by an admin; every case view is audit-logged |
| Consent | per purpose (care, location, research, identity), append-only ledger, DPDP Act 2023 export and erasure |
| Data minimisation | coordinates rounded to ~11 km; DigiLocker gives only DOB, sex, state and district, never the Aadhaar number; no request bodies in logs |
| Transport | HSTS, CSP, frame denial, no-sniff, strict CORS allow-list, per-IP rate limits |
| Outbound calls | one helper (`ayurnidaan/http.py`), HTTPS only, mandatory timeouts; XML parsed with `defusedxml` |
| Configuration | production refuses to start with development secrets or SQLite |
| Supply chain | see below |

## Pipeline (DevSecOps)

Every change passes these gates before it can reach production. Details are in
[docs/PIPELINE.md](docs/PIPELINE.md).

- **Secrets:** gitleaks over the full git history, and a pre-commit hook.
- **SAST:** CodeQL (Python, TypeScript, Actions) and Bandit.
- **SCA:** pip-audit, an npm audit gate with an expiring allow-list, dependency review on PRs, and weekly Dependabot updates.
- **IaC / container:** Hadolint, Trivy config scans, and a Trivy image scan that fails on fixable HIGH/CRITICAL findings.
- **DAST:** an active OWASP ZAP API scan against a throwaway container in CI, plus a passive ZAP baseline after each deploy.
- **Release integrity:** digest-pinned base image and SHA-pinned actions. The image carries a Sigstore keyless signature, SLSA provenance and an SPDX SBOM.

Accepted risks are documented, never silently ignored: npm advisories in
`mobile/audit-allowlist.json` and container CVEs in `.trivyignore`, each with a reason and a
re-review date.

## Clinical safety

This is a screening and decision-support tool, not a diagnostic device. If the engine
produces a dangerous output (for example, it misses a red flag or suggests something unsafe
to a patient), report it the same way and mark it **clinical safety**.
