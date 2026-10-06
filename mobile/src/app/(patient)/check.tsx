// New check-up: emergency checklist -> symptoms -> what changes it -> assessment.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useState } from 'react';

import { Bar, Button, Card, Chip, ErrorText, Field, Notice, Row, Screen, SkeletonCards, Stepper, T } from '@/components/ui';
import { api } from '@/lib/api';
import { pretty, usePalette } from '@/lib/theme';

const AGNI_LABEL: Record<string, string> = {
  irregular: 'Irregular, variable hunger',
  sharp_frequent_hunger: 'Sharp hunger, irritable if I skip meals',
  slow_heavy_after_meals: 'Slow, heavy after meals',
  balanced: 'Balanced, regular',
};

export default function NewCheck() {
  const qc = useQueryClient();
  const c = usePalette();
  const flags = useQuery({ queryKey: ['red-flags'], queryFn: api.redFlags, staleTime: Infinity });
  const options = useQuery({ queryKey: ['intake-options'], queryFn: api.intakeOptions, staleTime: Infinity });
  const [step, setStep] = useState<1 | 2>(1);
  const [checklist, setChecklist] = useState<Record<string, boolean | undefined>>({});
  const [complaint, setComplaint] = useState('');
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [aggravating, setAggravating] = useState<string[]>([]);
  const [relieving, setRelieving] = useState<string[]>([]);
  const [agni, setAgni] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Debounce typing; the timer callback (not the effect body) updates state.
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);
  const search = useQuery({
    queryKey: ['symptom-search', debounced],
    queryFn: () => api.searchSymptoms(debounced),
    enabled: debounced.length >= 2,
  });
  const results = debounced.length >= 2 && query.trim().length >= 2 ? (search.data ?? []) : [];

  const allAnswered = flags.data?.every((f) => checklist[f.code] !== undefined);
  const anyYes = Object.values(checklist).some(Boolean);
  const toggle = (list: string[], set: (v: string[]) => void, v: string) =>
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      const enc = await api.createEncounter({
        red_flag_checklist: Object.fromEntries(Object.entries(checklist).map(([k, v]) => [k, !!v])),
        chief_complaint: complaint || undefined,
        symptoms: Object.fromEntries(symptoms.map((s) => [s, true])),
        free_text_symptoms: query.trim() && !symptoms.length ? [query.trim()] : [],
        aggravating, relieving, agni,
      });
      qc.invalidateQueries({ queryKey: ['encounters'] });
      router.replace(`/(patient)/encounter/${enc.id}`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (flags.isLoading || options.isLoading) return <Screen><SkeletonCards count={4} min={600} /></Screen>;
  const answeredFlags = flags.data?.filter((f) => checklist[f.code] !== undefined).length ?? 0;

  return (
    <Screen>
      <T v="h1">New check-up</T>
      <Stepper steps={['Safety check', 'Symptoms', 'Assessment']} current={step - 1} />
      {step === 1 && (
        <Card title="First, a safety check">
          <T v="muted">Answer each question. Any “yes” means you should get emergency care now.</T>
          <Bar label="Answered" value={answeredFlags / Math.max(1, flags.data?.length ?? 1)}
            color={anyYes ? c.critical : c.accent} display={`${answeredFlags} / ${flags.data?.length ?? 0}`} />
          {flags.data?.map((f) => (
            <Card key={f.code}>
              <T>{f.question}</T>
              <Row>
                <Chip label="Yes" selected={checklist[f.code] === true} onPress={() => setChecklist((c) => ({ ...c, [f.code]: true }))} />
                <Chip label="No" selected={checklist[f.code] === false} onPress={() => setChecklist((c) => ({ ...c, [f.code]: false }))} />
              </Row>
            </Card>
          ))}
          {anyYes && (
            <Notice tone="critical">
              <T v="h3">Please seek emergency care now - call 112 or 108.</T>
              <T>You can still save this record so a practitioner sees it.</T>
            </Notice>
          )}
          <Button label={anyYes ? 'Save emergency record' : 'Continue'} onPress={anyYes ? create : () => setStep(2)}
            disabled={!allAnswered} loading={busy} variant={anyYes ? 'danger' : 'primary'} />
        </Card>
      )}
      {step === 2 && (
        <>
          <Card title="What is bothering you?">
            <Field label="In your own words (optional)" value={complaint} onChangeText={setComplaint}
              placeholder="e.g. joint pain for two weeks" maxLength={300} />
            <Field label="Add symptoms" value={query} onChangeText={setQuery} placeholder="type: cough, loose motions, itching…" />
            <Row>
              {results.filter((r) => !symptoms.includes(r.term)).map((r) => (
                <Chip key={r.term} label={`+ ${r.term}`} onPress={() => { setSymptoms((s) => [...s, r.term]); setQuery(''); }} />
              ))}
            </Row>
            <T v="label">Your symptoms</T>
            <Row>
              {symptoms.length ? symptoms.map((s) => (
                <Chip key={s} label={`${s}  ✕`} tone="yes" onPress={() => setSymptoms((x) => x.filter((y) => y !== s))} />
              )) : <T v="small">None added yet.</T>}
            </Row>
          </Card>
          <Card title="What makes it worse? (Anupashaya)">
            <Row>{options.data?.aggravating.map((a) => (
              <Chip key={a} label={pretty(a)} selected={aggravating.includes(a)} onPress={() => toggle(aggravating, setAggravating, a)} />
            ))}</Row>
          </Card>
          <Card title="What makes it better? (Upashaya)">
            <Row>{options.data?.relieving.map((a) => (
              <Chip key={a} label={pretty(a)} selected={relieving.includes(a)} onPress={() => toggle(relieving, setRelieving, a)} />
            ))}</Row>
          </Card>
          <Card title="Your digestion (Agni)">
            <Row>{options.data?.agni.map((a) => (
              <Chip key={a} label={AGNI_LABEL[a] ?? pretty(a)} selected={agni === a} onPress={() => setAgni(agni === a ? null : a)} />
            ))}</Row>
          </Card>
          <ErrorText error={error} />
          <Row>
            <Button label="Back" variant="secondary" onPress={() => setStep(1)} />
            <Button label="See assessment" onPress={create} loading={busy}
              disabled={!symptoms.length && query.trim().length < 3} />
          </Row>
        </>
      )}
    </Screen>
  );
}
