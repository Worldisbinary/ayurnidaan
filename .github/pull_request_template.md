## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## How it was tested

<!-- pytest / tsc / lint / manual steps / screenshots for UI changes -->

## Checklist

- [ ] Tests added or updated, and `pytest` passes locally
- [ ] `ruff check` and `ruff format --check` are clean; `npx tsc --noEmit` and `npx expo lint` too, if `mobile/` changed
- [ ] Schema changes come with an Alembic migration (`alembic check` passes)
- [ ] No secrets, tokens, real patient data or raw Kaggle files in the diff
- [ ] **Patient data:** any new field is covered by consent, export and erasure, and is never logged
- [ ] **Clinical logic:** rule changes cite their classical source; the engine benchmark (`ayur benchmark`) has not regressed
- [ ] User-facing text stays non-diagnostic ("possible", "discuss with a practitioner")
