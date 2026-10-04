// Dense case view: everything needed to examine, decide and document in one screen.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Linking, View } from 'react-native';

import { DifferentialList, DoshaBars, KalaDeshaCard, TriageBanner } from '@/components/clinical';
import { Badge, Button, Card, Chip, Columns, ErrorText, Field, KV, Loading, Row, Screen, T, Table } from '@/components/ui';
import { api } from '@/lib/api';
import type { CaseView } from '@/lib/types';
import { DESHA_LABEL, pretty, space } from '@/lib/theme';

const DECISIONS = [
  ['confirmed', 'Confirm'], ['revised', 'Revise to selected'], ['ruled_out', 'Rule out all'], ['referred', 'Refer'],
] as const;

export default function CaseScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['case', id], queryFn: () => api.caseView(id) });
  const opts = useQuery({ queryKey: ['intake-options'], queryFn: api.intakeOptions, staleTime: Infinity });
  const [selected, setSelected] = useState<string | null>(null);
  const [exam, setExam] = useState<Record<string, string>>({});
  const [decision, setDecision] = useState<string>('confirmed');
  const [notes, setNotes] = useState('');
  const [plan, setPlan] = useState('');

  const refresh = (enc: CaseView['encounter']) =>
    qc.setQueryData<CaseView>(['case', id], (old) => (old ? { ...old, encounter: enc } : old));
  const claim = useMutation({ mutationFn: () => api.claim(id), onSuccess: () => q.refetch() });
  const examine = useMutation({ mutationFn: () => api.examine(id, exam), onSuccess: refresh });
  const review = useMutation({
    mutationFn: () => {
      // Same effective selection the screen shows: explicit pick, else the top-ranked condition.
      const effective = selected ?? q.data?.encounter.assessment?.differential?.[0]?.condition_id ?? null;
      return api.review(id, { decision, condition_id: decision === 'confirmed' || decision === 'revised' ? effective : null,
        notes: notes || undefined, plan: plan || undefined });
    },
    onSuccess: (enc) => {
      refresh(enc);
      qc.invalidateQueries({ queryKey: ['queue'] });
      router.replace('/(practitioner)');
    },
  });

  if (q.isLoading || !q.data) return <Screen><Loading /><ErrorText error={q.error} /></Screen>;
  const { encounter: e, patient, history, condition_references: refs } = q.data;
  const a = e.assessment;
  const sel = selected ?? a?.differential?.[0]?.condition_id ?? null;
  const ref = sel ? refs[sel] : undefined;
  const p = patient.profile;
  const reviewed = e.status === 'reviewed';

  return (
    <Screen onRefresh={() => q.refetch()} refreshing={q.isFetching}>
      <Row style={{ justifyContent: 'space-between' }}>
        <View style={{ flex: 1 }}>
          <T v="h2">{patient.name} · {e.inputs?.age ?? '?'}{p?.sex ? ` ${p.sex}` : ''}</T>
          <T v="small">{e.chief_complaint ?? 'No complaint text'} · {new Date(e.created_at).toLocaleString()} · engine {e.engine_version}</T>
        </View>
        <Badge status={e.triage_level} />
        <Badge status={e.status} />
        {!reviewed && <Button label="Claim" compact variant="secondary" onPress={() => claim.mutate()} loading={claim.isPending} />}
      </Row>
      {a && <TriageBanner a={a} />}

      <Columns min={360}>
        <Card title="Patient">
          <KV items={[
            ['Desha', p?.desha ? DESHA_LABEL[p.desha] : '—'],
            ['Prakriti', p?.prakriti?.dominant ? pretty(p.prakriti.dominant) : '—'],
            ['Chronic conditions', p?.chronic_conditions?.join(', ') || '—'],
            ['Current medicines', p?.current_medicines?.join(', ') || '—'],
            ['Previous check-ups', String(history.encounters.length - 1)],
          ]} />
          {history.recurring.length > 0 && (
            <T v="small">Recurring: {history.recurring.map((r) => `${r.condition} ×${r.episodes}`).join(', ')}</T>
          )}
        </Card>

        <Card title="Reported findings">
          <Row>
            {Object.entries(e.inputs?.symptoms ?? {}).map(([s, v]) => <Chip key={s} label={s} tone={v ? 'yes' : 'no'} />)}
          </Row>
          <KV items={[
            ['Worse with', e.inputs?.aggravating?.map(pretty).join(', ') || '—'],
            ['Better with', e.inputs?.relieving?.map(pretty).join(', ') || '—'],
            ['Agni', pretty(a?.agni) || '—'],
            ['Ama', a?.ama ? `${pretty(a.ama.level)}${a.ama.signs.length ? ` (${a.ama.signs.join(', ')})` : ''}` : '—'],
          ]} />
        </Card>

        {a && <DoshaBars title="Vikriti" profile={a.vikriti} />}
        {a && <DoshaBars title="Prakriti" profile={a.prakriti} />}
        {a && <KalaDeshaCard a={a} />}

        <Card title="Ashtavidha pariksha · examination">
          {Object.entries(opts.data?.examination ?? {}).map(([field, values]) => (
            <Row key={field}>
              <T v="label" style={{ width: 64 }}>{field}</T>
              {values.map((v) => (
                <Chip key={v} label={pretty(v)} selected={(exam[field] ?? e.inputs?.examination?.[field]) === v}
                  onPress={() => setExam((x) => ({ ...x, [field]: v }))} />
              ))}
            </Row>
          ))}
          <ErrorText error={examine.error} />
          <Button label="Record findings & re-assess" variant="secondary" onPress={() => examine.mutate()}
            loading={examine.isPending} disabled={!Object.keys(exam).length || reviewed} />
        </Card>
      </Columns>

      <Columns min={480}>
        <Card title="Differential · select a condition to review">
          {a?.differential ? (
            <DifferentialList items={a.differential} dense selectedId={sel} onSelect={(d) => setSelected(d.condition_id)} />
          ) : <T v="muted">No differential (emergency stop).</T>}
        </Card>

        <View style={{ gap: space.md }}>
          <Card title="Reference for selected condition">
            {ref ? (
              <>
                {Object.entries(ref.practitioner_reference).map(([k, v]) => (
                  <View key={k}><T v="label">{pretty(k)}</T><T>{v}</T></View>
                ))}
                {Object.entries(ref.patient_guidance).map(([k, v]) => (
                  <View key={k}><T v="label">{pretty(k)}</T><T>{v}</T></View>
                ))}
                <T v="small">Typical symptoms: {ref.typical_symptoms.join(', ')}</T>
                <T v="small">Typical age {ref.age[0]}–{ref.age[1]} · sex weight F {ref.sex_weight.female} / M {ref.sex_weight.male}</T>
              </>
            ) : <T v="muted">Select a condition.</T>}
          </Card>
          <Card title="Literature (Europe PMC)">
            {ref?.literature ? (
              <T v="small">{ref.literature.hits_all.toLocaleString()} papers · {ref.literature.hits_india.toLocaleString()} India ·
                {' '}{ref.literature.hits_ayurveda} on Ayurveda · regional weight {ref.literature.regional_weight}</T>
            ) : <T v="small">No literature data for this condition.</T>}
            {ref?.papers?.length ? (
              <Table head={['Paper', 'Year', 'Cited']} flex={[4, 0.7, 0.6]}
                rows={ref.papers.map((pp) => [pp.title, pp.year, String(pp.cited_by)])}
                onRowPress={(i) => Linking.openURL(ref.papers[i].url)} />
            ) : null}
          </Card>
          <Card title={reviewed ? 'Reviewed' : 'Your decision'}>
            {reviewed ? e.reviews.map((r) => (
              <T key={r.created_at}>{pretty(r.decision)}: {r.condition_name ?? '—'} {r.plan ? `· ${r.plan}` : ''}</T>
            )) : (
              <>
                <Row>{DECISIONS.map(([k, label]) => (
                  <Chip key={k} label={label} selected={decision === k} onPress={() => setDecision(k)} />
                ))}</Row>
                <T v="small">Selected: {a?.differential?.find((d) => d.condition_id === sel)?.name ?? '—'}</T>
                <Field label="Clinical notes" value={notes} onChangeText={setNotes} multiline style={{ minHeight: 60 }} />
                <Field label="Plan (shown to patient)" value={plan} onChangeText={setPlan} multiline style={{ minHeight: 60 }} />
                <ErrorText error={review.error} />
                <Button label="Submit review" onPress={() => review.mutate()} loading={review.isPending}
                  disabled={(decision === 'confirmed' || decision === 'revised') && !sel} />
                <T v="small">Confirmed diagnoses from patients who consented to research improve the model after admin review.</T>
              </>
            )}
          </Card>
        </View>
      </Columns>
    </Screen>
  );
}
