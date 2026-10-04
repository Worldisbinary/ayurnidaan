# Ayurnidaan

An Ayurvedic screening and clinical decision-support platform. **Patients** do an intake
on their phone or the web: an emergency checklist, symptoms, what makes them worse or
better, digestion, constitution and location. The engine reasons the way an Ayurvedic
assessment does and ranks possible conditions with the evidence behind each one.
**Practitioners** review the case in a dense workspace, record examination findings,
and confirm or revise the diagnosis. Confirmed cases, where the patient has consented,
feed a learning loop that updates the model only when it measurably improves.

> It is a screening and decision-support tool, not a diagnostic device. A qualified
> practitioner confirms every diagnosis. See [DEPLOYMENT.md](DEPLOYMENT.md) §5 before any
> real-patient use.

| Part | Stack |
|---|---|
| Clinical engine | Python: Bayesian differential with Ayurvedic priors, adaptive questioning |
| API | FastAPI · SQLAlchemy 2 · Alembic · Postgres (SQLite locally) · JWT · scrypt |
| App (Android + web) | Expo SDK 57 · React Native · Expo Router · React Query · TypeScript |
| Data pipeline | pandas · scikit-learn · DuckDB warehouse · checksum-pinned sources |
| Deploy | Docker → Render · Neon Postgres · Vercel (web) · EAS → Google Play |

## How the engine reasons

```
intake ─▶ 1 Triage      12-item emergency checklist (stroke, ACS, sepsis, obstetric,
                        paediatric, self-harm). Any "yes" stops everything: call 112 / 108.
       ─▶ 2 Prakriti    constitution from 9 questions (reduced from 25, same accuracy)
       ─▶ 3 Vikriti     current imbalance from symptom-level dosha likelihood ratios
                        + Ashtavidha pariksha (pulse, tongue, stool, urine, voice, touch,
                        eyes, build) + Upashaya / Anupashaya + Agni, sqrt(n)-tempered
       ─▶ 4 Agni · Ama  digestive pattern and Ama load
       ─▶ 5 Kala · Desha  Ritu from the date (chaya/prakopa/prashama cycle);
                        Desha from one year of local climate (Open-Meteo ERA5)
       ─▶ 6 Differential  naive-Bayes over 1,400+ condition profiles × priors:
                        prevalence (Orphanet, India-aware) · regional relevance
                        (Europe PMC) · age · sex · dosha agreement · season
       ─▶ 7 Next questions  maximum expected information gain over the differential
```

Every ranked condition carries its evidence: which reported symptoms support it, which
typical symptoms the patient denied, what has not been asked, and the log-odds of each
prior. Practitioners also see the NAMC code, the classical treatment principles,
herbs and tests from the knowledge bases, and the most-cited Ayurveda papers on it.

## Data sources

| Source | Used for | Licence / access |
|---|---|---|
| Kaggle: classical Ayurvedic knowledge base (1,000 conditions) | condition profiles, dosha, body system, age/sex, treatment principles | Kaggle |
| Kaggle: AyurGenixAI (446 diseases) | modern profiles, herbs, tests, diet/yoga guidance | Kaggle |
| Kaggle: Prakriti assessments (5,000) | constitution model | Kaggle |
| Kaggle: lifestyle intake survey (3,563) | diabetes risk analytics | Kaggle (contains names, scrubbed on ingest) |
| Ministry of AYUSH NAMC codes (2,893) | standard morbidity coding | Kaggle mirror |
| **Orphanet** prevalence + names | rare-disease priors (India / Asia / Worldwide only) | CC-BY-4.0 |
| **Europe PMC** (PubMed + PMC) | literature per condition, regional relevance | free REST API |
| **Open-Meteo** ERA5 archive + geocoding | Desha from local climate | free API |

Google Scholar has no API and its terms forbid scraping, so Europe PMC is the
literature source. Three Kaggle datasets were **rejected by the quality gate**: one is
91.7% duplicate rows, one pads 100 real rows with random columns, and one reuses 29
symptom strings across 925 "diseases".

## Results

**Differential engine** — simulated patients, 500 per configuration, on a seed not used
for tuning (`ayur benchmark`). Each patient volunteers 2 textbook symptoms, plus a
noise symptom 30% of the time, then answers 5 adaptive questions with realistic noise:

| Configuration | Top-1, 2 symptoms | Top-5, 2 symptoms | **Top-1 after 5 questions** | **Top-5 after 5 questions** |
|---|---|---|---|---|
| Full engine | 48.6% | 84.0% | **72.0%** | **95.0%** |
| Without dosha prior | 49.8% | 84.0% | 72.6% | 93.8% |
| Without age / sex | 46.4% | 83.8% | 69.6% | 93.6% |
| Without prevalence prior | 49.6% | 84.0% | 72.6% | 96.0% |
| Symptoms only | 46.2% | 81.8% | 71.8% | 94.0% |

The adaptive interview is the largest gain. Age and sex add about 2.4 points of top-1,
and the dosha prior about 1.2 points of top-5. The prevalence prior costs about 1 point
in this simulation *by design*, because the simulation picks diseases uniformly; what
it buys is real-world base rates. Before it was added, a child with loose motions got
Ebola ranked first; now the result is gastroenteritis, Visucika and food poisoning.
These numbers measure internal consistency on textbook presentations, **not accuracy on
real patients**. That needs a supervised pilot.

**Analytics pipeline** (the original internship project, rebuilt on public data):

| Area | Result |
|---|---|
| Symptom canonicalisation | 2,843 raw strings → **215 canonical symptoms**; 1,211 / 1,446 conditions clustered |
| Symptom clusters | 24 clusters, modularity 0.69; recover body systems at NMI 0.288 vs 0.078 chance (p = 0.005) |
| Clusters vs dosha theory | built *without* dosha labels, yet **10 cluster–dosha enrichments at FDR < 0.05**, all matching the classical texts |
| Questionnaire reduction | **9 of 25 Prakriti items** give 84.6% CV accuracy vs 83.1% with all 25 |
| Predictive variables | 22 candidates → 3 confirmed (age, family history, sleep hours) + 3 supported |
| Diabetes triage model | holdout AUC 0.789 (95% CI 0.758–0.821), calibration slope 0.96 |

## Privacy, safety and security

- **Consent by purpose** (care / location / research), in an append-only ledger. Data
  export and account erasure are built in, per the DPDP Act 2023.
- **Location** is coarse only: Android requests `ACCESS_COARSE_LOCATION`, and the server
  rounds coordinates to about 11 km and never stores exact ones.
- **Learning** uses only practitioner-confirmed cases from patients who consented to
  research. A new model is promoted only if it is not worse on a time-based holdout and
  on simulated patients.
- **Population insights** suppress any group smaller than 5 patients.
- **Access control:** practitioners must be verified by an admin before they see any case,
  and every case view is audit-logged.
- **Security:** scrypt password hashing, revocable refresh tokens, per-IP rate limits,
  security headers, and a production start-up check that refuses development secrets.
- **Patient-facing guidance** is general lifestyle advice only. Herbs and doses are shown
  to practitioners only.

## Quick start

```bash
python -m venv .venv && .venv\Scripts\activate          # macOS/Linux: . .venv/bin/activate
pip install -e ".[all]"
cp .env.example .env
ayur serve-app                                            # API  http://127.0.0.1:8000/docs
cd mobile && npm install && npx expo start                # app  (w = web, a = Android)
```

The committed `knowledge_pack/` is all the API needs. To rebuild it from source data:

```bash
ayur fetch            # Kaggle + Orphanet, checksum-verified
ayur run              # quality gate → warehouse → analytics → knowledge pack
ayur build-evidence   # Europe PMC literature (resumable, ~1 hour)
ayur benchmark        # simulated-patient benchmark → manifest
```

Deployment to Render, Neon, Vercel and Google Play is covered step by step in
**[DEPLOYMENT.md](DEPLOYMENT.md)**.

## Testing

- **Backend:** 110 tests at 91% coverage, covering the whole pipeline on synthetic
  sources with planted structure, the clinical engine, and the full API flow (auth,
  consent, triage ordering, review, learning loop, k-anonymity, export and erasure).
- **App:** `tsc` and ESLint are clean.
- **End to end:** a browser test drives the exported web app against the live API,
  walking patient onboarding → check-up → adaptive answer → share → admin verification
  → practitioner examination and review → the patient sees the plan.
- **CI** (`.github/workflows/ci.yml`) runs all of the above, plus a migration-drift
  check and a Docker build.

## Limitations

- Knowledge bases are community uploads. The quality gate catches gross problems, not
  every error, and some modern-KB rows contradict each other; those are flagged and
  excluded from matching.
- Benchmark accuracy is on simulated textbook presentations; real-world accuracy is
  unknown until a clinical pilot.
- Fuzzy NAMC links (29) are candidates for a human coder to review.
- Thresholds for Desha (rainfall / humidity) and the pariksha likelihood weights are
  documented expert settings, not learned values.

## Layout

```
configs/sources.yaml       registry: origin (Kaggle / URL), sha256, role, gate thresholds
knowledge_pack/            PII-free engine data (JSON) + manifest with benchmark
src/ayurnidaan/
  clinical/                engine · differential · dosha · pariksha · kala_desha · red_flags
                           demographics · symptom_search · guidance · evaluation · knowledge
  app/                     FastAPI app: models · auth · routers · services (learning, insights)
  transform/               pii · normalize · symptoms · terminology (NAMC) · epidemiology (Orphanet)
  analytics/               clusters · screening · variables · risk   (analytics pipeline)
  evidence.py              Europe PMC crawl + regional relevance
  pipeline.py ingest.py quality.py warehouse.py cli.py
migrations/                Alembic
mobile/                    Expo app (patient · practitioner · admin)
tests/                     unit · synthetic end-to-end · API · real-data integration
```
