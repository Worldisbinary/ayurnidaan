import { useQuery, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';

import { DoshaBars } from '@/components/clinical';
import { Button, Card, Chip, ErrorText, Loading, Row, Screen, T } from '@/components/ui';
import { api } from '@/lib/api';
import type { DoshaProfile } from '@/lib/types';

export default function PrakritiQuiz() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['prakriti-questions'], queryFn: api.prakritiQuestions, staleTime: Infinity });
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<DoshaProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      setResult((await api.savePrakriti(answers)) as DoshaProfile);
      qc.invalidateQueries({ queryKey: ['profile'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  if (q.isLoading) return <Screen><Loading /></Screen>;
  return (
    <Screen>
      <T v="h1">Prakriti · your constitution</T>
      <T v="muted">Answer for how you have been most of your life, not just recently. These 9 questions were
        selected from a 25-item questionnaire and give the same accuracy.</T>
      {q.data?.map((item, i) => (
        <Card key={item.id} title={`${i + 1} / ${q.data.length}`}>
          <T>{item.question}</T>
          <Row>
            {item.options.map((o) => (
              <Chip key={o} label={o} selected={answers[item.id] === o} onPress={() => setAnswers((a) => ({ ...a, [item.id]: o }))} />
            ))}
          </Row>
        </Card>
      ))}
      <ErrorText error={error} />
      <Button label="See my Prakriti" onPress={save} loading={busy}
        disabled={Object.keys(answers).length < (q.data?.length ?? 1)} />
      {result && (
        <>
          <DoshaBars title="Your Prakriti" profile={result} />
          <Button label="Done" variant="secondary" onPress={() => router.replace('/(patient)')} />
        </>
      )}
    </Screen>
  );
}
