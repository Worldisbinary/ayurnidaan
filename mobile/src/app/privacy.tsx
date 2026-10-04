import { Card, Screen, T } from '@/components/ui';

// Public page: Google Play requires a reachable privacy-policy URL for health apps.
// Policy text must be reviewed by a lawyer before production launch.
const SECTIONS: [string, string][] = [
  ['Who we are', 'Ayurnidaan is a screening and clinical decision-support service for Ayurvedic care. It does not provide a diagnosis; a qualified practitioner confirms any diagnosis.'],
  ['What we collect', 'Account details (name, email), health information you enter (symptoms, history, constitution questionnaire), date of birth and sex, and - only if you allow it - your approximate location. Exact GPS coordinates are rounded to about 11 km on our server and never stored.'],
  ['Why (purposes, each with separate consent)', 'Care: sharing your check-ups with practitioners. Location: estimating your local climate (Desha), which influences Ayurvedic assessment. Research: using practitioner-confirmed, de-identified cases to improve the screening model. You can give or withdraw each consent at any time in Profile.'],
  ['What we never do', 'We do not sell your data, show advertising, or share your data with insurers or employers.'],
  ['Your rights (DPDP Act 2023)', 'You can download all your data (Profile → Export my data) and permanently delete your account and health records (Profile → Delete account). Withdrawing location consent erases your stored location.'],
  ['Security', 'Data is encrypted in transit (HTTPS). Passwords are hashed with scrypt. Access is role-based and every view of a patient record by a practitioner is audit-logged.'],
  ['Emergencies', 'This service is not for emergencies. If you have chest pain, difficulty breathing, signs of stroke, heavy bleeding or thoughts of self-harm, call 112 / 108, or Tele-MANAS 14416.'],
  ['Contact / Grievance officer', 'privacy@ayurnidaan.example (replace with the operator\'s grievance officer before launch).'],
];

export default function Privacy() {
  return (
    <Screen>
      <T v="h1">Privacy policy</T>
      <T v="small">Version 2026-10</T>
      {SECTIONS.map(([h, body]) => (
        <Card key={h} title={h}><T>{body}</T></Card>
      ))}
    </Screen>
  );
}
