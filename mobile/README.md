# Ayurnidaan app (Android + web)

One Expo (React Native, SDK 57) codebase builds the Android app and the website.

| Role | Screens |
|---|---|
| Patient | Home · New check (red-flag checklist → symptoms → upashaya / agni) · adaptive assessment · History & patterns · Profile (consents, location → Desha, Prakriti quiz, data export, account deletion) |
| Practitioner | Triaged queue · dense case view (findings, Vikriti/Prakriti, Kala-Desha, Ashtavidha pariksha entry, differential with evidence factors, condition references, Europe PMC literature, review) · population insights |
| Admin | Practitioner verification · learning-loop retraining · audit log |

## Run locally

```bash
npm install
# API on http://localhost:8000 - from the repo root run: ayur serve-app
EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo start      # press w for web, a for Android
```

Android emulators reach the host at `10.0.2.2`, which is the default when
`EXPO_PUBLIC_API_URL` is unset.

## Checks

```bash
npx tsc --noEmit
npx expo lint
npx expo export -p web     # static site in dist/
```

## Notes

- Tokens: SecureStore (Keychain/Keystore) on device, localStorage on web; access tokens
  refresh transparently and every sign-in/out clears the query cache so a shared device
  never shows the previous user's data.
- Location: coarse permission only (`ACCESS_COARSE_LOCATION`); precise and background
  location are blocked in `app.json`. The server rounds coordinates to ~11 km.
- Building for Google Play: see `../DEPLOYMENT.md`.
