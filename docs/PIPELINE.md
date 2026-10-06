# CI/CD and DevSecOps pipeline

Nothing reaches production unless it passes every gate below. Deploys are never
triggered by a plain push: Render's auto-deploy is off and Vercel's production
Git deploys are off, so `cd.yml` is the only path to production.

```
 developer ── pre-commit: ruff · bandit · gitleaks · no raw data
     │
     ▼  push / pull request
 ┌───────────────────────── ci.yml ─────────────────────────┐   ┌──────── security.yml ────────┐
 │ backend   ruff · alembic drift · pytest (3.12/3.13/3.14) │   │ gitleaks (full history)      │
 │           coverage ≥ 85 %                                │   │ Bandit (SAST)  → Security tab │
 │ mobile    tsc · eslint · web export                      │   │ pip-audit · npm audit gate   │
 │ container hadolint · build · Trivy image scan (gate)     │   │ Trivy config / IaC scan      │
 │           smoke test · OWASP ZAP active API scan (DAST)  │   │ dependency review (PRs)      │
 └──────────────────────────────────────────────────────────┘   └──────────────────────────────┘
     │ codeql.yml (Python · TypeScript · Actions)     scorecard.yml (repo supply-chain grade)
     ▼  ci passed on main
 ┌───────────────────────────────── cd.yml ─────────────────────────────────┐
 │ image   build once → GHCR · Trivy gate · cosign keyless signature        │
 │         SLSA provenance · SPDX SBOM                                      │
 │ deploy  API → Render (deploy hook)       web → Vercel (prebuilt)         │
 │ verify  wait for the new commit to be live · smoke test · ZAP baseline  │
 │ tag v*  Android App Bundle on EAS → Play internal track · GitHub Release │
 └──────────────────────────────────────────────────────────────────────────┘
```

## What each gate catches

| Gate | Tool | Fails the build when |
|---|---|---|
| Lint / format | ruff, ESLint, tsc | style, type or import errors |
| Schema drift | `alembic check` | models changed without a migration |
| Tests | pytest + coverage | any test fails, or coverage < 85 % |
| Secrets | gitleaks | a key or token appears anywhere in git history |
| SAST | Bandit, CodeQL | medium+ Bandit issue; CodeQL alerts show in the Security tab |
| SCA (Python) | pip-audit (OSV) | any known-vulnerable installed package |
| SCA (npm) | `scripts/audit-gate.mjs` | a **new** high/critical advisory, or an allow-list entry that expired or is no longer needed |
| New dependencies | dependency-review | a PR adds a dependency with a high+ advisory |
| Dockerfile | Hadolint | warning-level issues |
| IaC config | Trivy config | HIGH/CRITICAL misconfiguration |
| Container | Trivy image | a HIGH/CRITICAL CVE **that has a fix** |
| Runtime | `scripts/smoke.py` | health, database, headers, auth, CORS or docs-off checks fail |
| DAST | OWASP ZAP API scan | SQLi, XSS, command injection, XXE, SSRF, path traversal, SSTI (`.zap/rules.tsv`) |

Supply-chain hardening: every third-party action is pinned to a commit SHA, the base image
is pinned by digest, workflows default to read-only tokens, and checkout never persists
credentials. Dependabot updates all four ecosystems (pip, npm, Actions, Docker) weekly.

## One-time setup (GitHub → Settings)

**Secrets and variables → Actions.** Each deploy step is skipped with a notice until its
secret exists, so you can add these one at a time.

| Name | Kind | Where to get it |
|---|---|---|
| `RENDER_DEPLOY_HOOK_URL` | secret | Render → service → Settings → Deploy Hook |
| `VERCEL_TOKEN` | secret | vercel.com → Account → Tokens |
| `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | secret | `mobile/.vercel/project.json` after running `npx vercel link` once |
| `EXPO_TOKEN` | secret | expo.dev → Account → Access tokens (needed only for Android releases) |
| `API_URL`, `WEB_URL` | variable | your live URLs, if they differ from the defaults |

**Environments.** Create `production` and `production-web`. Optionally add yourself as a
required reviewer, so each deploy waits for one click.

**Branch protection → `main`.** Require status checks: `backend (py3.12)`, `mobile`,
`container (build · scan · smoke · DAST)`, `secret scan (gitleaks, full history)`, `SAST (Bandit)`,
`SCA (pip-audit)`, `SCA (npm audit gate)`, and the `codeql` jobs. Block force pushes.
Requiring a pull request is recommended; as a solo maintainer, leave "required approvals"
at 0, because GitHub does not let you approve your own PR.

**Code security.** Turn on private vulnerability reporting, Dependabot alerts, and secret
scanning with push protection. All are free on public repositories.

## Releasing

```bash
git tag v1.3.0 && git push origin v1.3.0
```

Tagging runs the full CD pipeline and then:

- builds the Android App Bundle on EAS and submits it to the Play internal track (needs
  `EXPO_TOKEN` and a Play service account configured in EAS);
- publishes a GitHub Release with the SBOM attached.

To verify a released image:

```bash
cosign verify ghcr.io/worldisbinary/ayurnidaan-api@sha256:<digest> \
  --certificate-identity-regexp 'https://github.com/Worldisbinary/ayurnidaan/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
gh attestation verify oci://ghcr.io/worldisbinary/ayurnidaan-api@sha256:<digest> -R Worldisbinary/ayurnidaan
```

## When a gate fails

- **New npm advisory:** first try `npm update <pkg>` or an `overrides` entry. If there is no
  fix and the package is build-time only, add it to `mobile/audit-allowlist.json` with a
  reason and an expiry date of no more than 3 months.
- **Trivy image CVE:** a Dependabot base-image bump usually fixes it. Otherwise add the ID to
  `.trivyignore` with a reason and a re-review date.
- **Bandit:** fix the code. Use `# nosec BXXX` only with a comment on the line above saying why
  it is safe.
- **ZAP FAIL:** download the `zap-api-scan` artifact. The HTML report shows the request that
  triggered the alert.

## Running the checks locally

```bash
pip install -e ".[all]" && pre-commit install          # hooks on every commit
bandit -c pyproject.toml -r src -ll                     # SAST
pip-audit --skip-editable                               # Python dependencies
cd mobile && npm run audit:gate                         # npm dependencies
python scripts/smoke.py --api http://localhost:8000     # against a running API
```
