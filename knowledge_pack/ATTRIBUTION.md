# Knowledge pack: data sources, licences and attribution

The source code of Ayurnidaan is MIT-licensed (see `../LICENSE`). The JSON files in this
folder are **derived from third-party data**, and the licences below apply to them, not
the MIT licence. Each file was checked against its upstream licence before it was
committed (October 2026). Kaggle licences were read from each dataset's Kaggle API
metadata (`licenseName`), which is what its Kaggle page displays.

| File | Derived from | Upstream licence | What is redistributed |
|---|---|---|---|
| `conditions.json` | Ayurvedic Knowledge Dataset; AyurGenixAI: Ayurvedic Dataset; Orphanet; Europe PMC | CC BY 4.0; CC BY 4.0; CC BY 4.0; bibliographic metadata | condition names, symptoms (canonicalised), dosha, age/sex fit, treatment principles; Orphanet prevalence class; literature hit counts |
| `symptoms.json` | the two condition datasets above | CC BY 4.0 | canonical symptom vocabulary, aliases, frequencies, cluster ids |
| `vikriti.json` | the two condition datasets above | CC BY 4.0 | per-symptom dosha log-likelihood ratios (statistics computed from them) |
| `prakriti.json`, `prakriti_full.json` | Doshas for Vata Pitta and Kapha | ODbL 1.0 (database), DbCL 1.0 (contents) | questionnaire item names and answer options, and logistic-regression coefficients fitted on the data |
| `evidence.json`, `evidence_cache.json` | Europe PMC REST API | bibliographic metadata | title, journal, year, PMID, DOI, citation count and hit counts. No abstracts or full text |
| `manifest.json` | this project | MIT | version, checksums, metrics and benchmark |
| `namc_links.json` | NAMC codes (Kaggle mirror) | **unclear**, so **not committed** | generated locally by `ayur fetch-namc` |

## Required attribution

**Ayurvedic Knowledge Dataset** by Akash kumar P R,
<https://www.kaggle.com/datasets/akashkumarpr/ayurvedic-knowledge-dataset>, licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). *Changes:* symptom text
split and canonicalised, dosha and body-system labels normalised, age/sex text parsed into
numeric fit weights, conflicting rows flagged, and records merged with the other sources.

**AyurGenixAI: Ayurvedic Dataset** by kirti,
<https://www.kaggle.com/datasets/kagglekirti123/ayurgenixai-ayurvedic-dataset>, licensed
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). *Changes:* as above.
Herb, test and diet fields are carried into `practitioner_reference` and `patient_guidance`.

**Doshas for Vata Pitta and Kapha** by Mathew Healy,
<https://www.kaggle.com/datasets/devanshsingh2207/doshas-for-vata-pitta-and-kapha>.
Contains information from this database, which is made available under the
[Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1-0/); its
contents are under the [Database Contents License (DbCL) 1.0](https://opendatacommons.org/licenses/dbcl/1-0/).
`prakriti*.json` hold model coefficients fitted on the database (a Produced Work under
ODbL §4.3) plus the questionnaire's item and option labels. No assessment records are
redistributed.

**Orphanet**: prevalence classes and disorder names. *Orphadata: Free access data from
Orphanet. © INSERM 1999. Available on <https://www.orphadata.com>.* Licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). *Changes:* prevalence classes
reduced to India / Asia / Worldwide estimates and converted into prior weights; names
matched to the condition list.

**Europe PMC**: literature metadata retrieved through the Europe PMC REST API
(<https://europepmc.org>). Only bibliographic fields and hit counts are stored. Europe PMC's
terms of use apply (<https://europepmc.org/Copyright>). MEDLINE/PubMed citation records
are provided by the U.S. National Library of Medicine.

## Not redistributed

- **NAMC codes** (Ministry of AYUSH National Ayurveda Morbidity Codes, Kaggle mirror
  `nnm22cs185surajn/national-ayurveda-morbidity-codes-csv`). The mirror's licence field
  says "Other (specified in description)", but the description is empty, so the terms are
  unclear. The codes are therefore **not committed**. `ayur fetch-namc` downloads the CSV
  with your own Kaggle credentials and writes `namc_links.json` locally (git- and
  Docker-ignored). The API shows NAMC codes only when that file is present.
- **Lifestyle intake survey** (`riyaptl1/ayurvedic-lifecycle-form-diabetes-prediction`,
  licence "Unknown", contains names). It is used only by the local analytics pipeline.
  Nothing derived from it is in this folder or in the Docker image. `manifest.json` keeps
  only its SHA-256 checksum, for lineage.
- **Raw files** of every source stay in `data/raw/` (git-ignored) and are re-downloaded,
  checksum-verified, by `ayur fetch`.

If you are a rights holder and believe a file here is used incorrectly, please open an
issue or use the contact in `../SECURITY.md`.
