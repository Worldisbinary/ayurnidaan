// Assessment + adaptive interview: the engine asks the most informative next question.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { DhatuCard, SrotasCard, SubdoshaCard } from '@/components/ayurveda';
import { AssessmentSummary, DoshaBars, KalaDeshaCard } from '@/components/clinical';
import { Badge, Button, Card, Chip, Columns, ErrorText, Loading, Notice, Row, Screen, T } from '@/components/ui';
import { api } from '@/lib/api';
import { useToast } from '@/lib/toast';
import type { Encounter } from '@/lib/types';

export default function EncounterScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ['encounter', id], queryFn: () => api.encounter(id) });
  const set = (e: Encounter) => qc.setQueryData(['encounter', id], e);
  const answer = useMutation({ mutationFn: (a: Record<string, boolean>) => api.answer(id, a), onSuccess: set });
  const consents = useQuery({ queryKey: ['consents'], queryFn: api.consents });
  const [agree, setAgree] = useState(false);
  const hasCare = !!consents.data?.consents.care;
  const submit = useMutation({
    mutationFn: async () => {
      // Consent is explicit and recorded before sharing (DPDP Act): never implied by a click.
      if (!hasCare) await api.setConsent('care', true);
      return api.submit(id);
    },
    onSuccess: (e) => {
      set(e);
      qc.invalidateQueries({ queryKey: ['encounters'] });
      qc.invalidateQueries({ queryKey: ['consents'] });
      toast('Shared - a verified practitioner will review it');
    },
    onError: (err) => toast(err instanceof Error ? err.message : 'Could not share', 'error'),
  });

  if (q.isLoading || !q.data) return <Screen><Loading /><ErrorText error={q.error} /></Screen>;
  const e = q.data;
  const a = e.assessment;
  const open = e.status === 'draft' || e.status === 'emergency';
  const asked = Object.keys(e.inputs?.symptoms ?? {}).length;

  return (
    <Screen onRefresh={() => q.refetch()} refreshing={q.isFetching}>
      <Row style={{ justifyContent: 'space-between' }}>
        <T v="h2">{e.chief_complaint || 'Check-up'}</T>
        <Badge status={e.status === 'draft' ? e.triage_level : e.status} />
      </Row>
      <T v="small">{new Date(e.created_at).toLocaleString()} · {asked} answers · engine {e.engine_version}</T>
      {e.reviews.map((r) => (
        <Notice key={r.created_at} icon="medkit">
          <T v="h3">Practitioner: {r.decision === 'confirmed' || r.decision === 'revised' ? r.condition_name : r.decision.replace('_', ' ')}</T>
          {r.plan && <T>Plan: {r.plan}</T>}
          {r.notes && <T v="muted">{r.notes}</T>}
        </Notice>
      ))}
      {a && <AssessmentSummary a={a} />}
      {a && !a.stopped && open && a.next_questions && a.next_questions.length > 0 && (
        <Card title="A few more questions sharpen the result">
          {a.next_questions.map((nq) => (
            <Row key={nq.symptom} style={{ justifyContent: 'space-between' }}>
              <T style={{ flex: 1 }}>Do you have <T style={{ fontWeight: '700' }}>{nq.symptom}</T>?</T>
              <Chip label="Yes" onPress={() => answer.mutate({ [nq.symptom]: true })} />
              <Chip label="No" onPress={() => answer.mutate({ [nq.symptom]: false })} />
            </Row>
          ))}
          {answer.isPending && <Loading />}
          <ErrorText error={answer.error} />
        </Card>
      )}
      {a && !a.stopped && (
        <Columns>
          <DoshaBars title="Vikriti · current imbalance" profile={a.vikriti}
            note="Estimated from your symptoms and what changes them." />
          <DoshaBars title="Prakriti · constitution" profile={a.prakriti}
            note={a.prakriti ? undefined : 'Answer the Prakriti questions in Profile.'} />
          <KalaDeshaCard a={a} />
          <SubdoshaCard derived={a.ayurveda ?? null} />
          <DhatuCard derived={a.ayurveda ?? null} />
          <SrotasCard derived={a.ayurveda ?? null} />
          {a.guidance && (
            <Card title="General guidance">
              {[...a.guidance.season, ...a.guidance.balance].map((g) => <T key={g}>• {g}</T>)}
              <T v="small">{a.guidance.note}</T>
            </Card>
          )}
        </Columns>
      )}
      {open && (
        <Card title="Next step">
          <T v="muted">Share this check-up with a verified Ayurvedic practitioner for review and a confirmed diagnosis.</T>
          {!hasCare && (
            <Chip label="I consent to share this check-up and my profile with verified practitioners for my care"
              selected={agree} onPress={() => setAgree((v) => !v)} />
          )}
          <ErrorText error={submit.error} />
          <Button label="Share with a practitioner" icon="paper-plane" onPress={() => submit.mutate()}
            loading={submit.isPending} disabled={!hasCare && !agree} />
        </Card>
      )}
      <Button label="Back to home" variant="ghost" onPress={() => router.replace('/(patient)')} />
    </Screen>
  );
}
