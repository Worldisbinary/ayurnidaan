// One generic screen renders every optional questionnaire module defined by the API.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { Bar, Button, Card, Chip, ErrorText, Field, KV, Notice, Row, Screen, SkeletonCards, T } from '@/components/ui';
import { api } from '@/lib/api';
import { pretty, usePalette } from '@/lib/theme';
import { useToast } from '@/lib/toast';

function summarise(result: Record<string, unknown>): [string, string][] {
  return Object.entries(result)
    .filter(([k, v]) => !['answered', 'total', 'dosha_signals', 'evidence', 'answers', 'note'].includes(k) && v != null &&
      typeof v !== 'object')
    .map(([k, v]) => [pretty(k), pretty(String(v))]);
}

export default function ModuleScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const qc = useQueryClient();
  const c = usePalette();
  const toast = useToast();
  const q = useQuery({ queryKey: ['questionnaires'], queryFn: api.questionnaires });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const module = q.data?.find((m) => m.id === id);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = Object.fromEntries(Object.entries(answers).map(([k, v]) => {
        const qn = module?.questions.find((x) => x.id === k);
        return [k, qn?.kind === 'number' ? Number(v) : v];
      }));
      setResult(await api.submitModule(id, payload));
      ['ayurveda', 'profile', 'questionnaires', 'trends'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      toast(`${module?.title ?? 'Module'} saved - your profile is updated`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (q.isLoading) return <Screen><SkeletonCards count={4} min={600} /></Screen>;
  if (!module) return <Screen><Notice tone="warning"><T>This questionnaire is not available.</T></Notice></Screen>;
  const answered = Object.values(answers).filter(Boolean).length;

  return (
    <Screen>
      <T v="h1">{module.title}</T>
      <T v="muted">{module.description}</T>
      <Bar label="Answered" value={answered / Math.max(1, module.questions.length)} color={c.accent}
        display={`${answered} / ${module.questions.length}`} />
      {module.completed_at && <T v="small">Last completed {new Date(module.completed_at).toLocaleDateString()} - answering again updates it.</T>}
      {module.questions.map((qn, i) => (
        <Card key={qn.id} title={`${i + 1} / ${module.questions.length}`}>
          {qn.kind === 'number' ? (
            <Field label={`${qn.text}${qn.unit ? ` (${qn.unit})` : ''}`} value={answers[qn.id] ?? ''} keyboardType="numeric"
              onChangeText={(v) => setAnswers((a) => ({ ...a, [qn.id]: v.replace(/[^0-9.]/g, '') }))} />
          ) : (
            <>
              <T>{qn.text}</T>
              <Row>
                {qn.options?.map((o) => (
                  <Chip key={o.value} label={o.label} selected={answers[qn.id] === o.value}
                    onPress={() => setAnswers((a) => ({ ...a, [qn.id]: o.value }))} />
                ))}
              </Row>
            </>
          )}
        </Card>
      ))}
      <ErrorText error={error} />
      <Button label={`Save (${answered}/${module.questions.length} answered)`} onPress={submit} loading={busy} disabled={answered === 0} />
      {result && (
        <Card title="Your result">
          <KV items={summarise(result)} />
          {typeof result.note === 'string' && <T v="small">{result.note}</T>}
          <Button label="Back to dashboard" variant="secondary" onPress={() => router.replace('/(patient)')} />
        </Card>
      )}
    </Screen>
  );
}
