// Daily check-in: Dinacharya (routine) + what you ate. Takes about 30 seconds.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { Bar, Button, Card, Chip, Columns, ErrorText, Notice, Row, Screen, SkeletonCards, T } from '@/components/ui';
import { api } from '@/lib/api';
import type { DailyCatalog, DailyLog } from '@/lib/types';
import { DOSHA_ORDER, pretty, usePalette } from '@/lib/theme';
import { useToast } from '@/lib/toast';

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

export default function Today() {
  const qc = useQueryClient();
  const day = today();
  const catalog = useQuery({ queryKey: ['daily-catalog'], queryFn: api.dailyCatalog, staleTime: Infinity });
  const logs = useQuery({ queryKey: ['daily'], queryFn: () => api.daily(14) });
  const existing = useMemo(() => logs.data?.find((l) => l.day === day), [logs.data, day]);
  if (catalog.isLoading || logs.isLoading || !catalog.data) return <Screen><SkeletonCards count={4} min={420} /></Screen>;
  return <TodayForm key={existing?.day ?? 'new'} day={day} existing={existing} catalog={catalog.data}
    onSaved={() => ['daily', 'ayurveda', 'trends'].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))} />;
}

function TodayForm({ day, existing, catalog, onSaved }: {
  day: string; existing?: DailyLog; catalog: DailyCatalog; onSaved: () => void;
}) {
  const c = usePalette();
  const toast = useToast();
  const [routine, setRoutine] = useState<Record<string, boolean>>(existing?.dinacharya ?? {});
  const [meals, setMeals] = useState<Record<string, string[]>>(existing?.meals ?? {});
  const [saved, setSaved] = useState<DailyLog | null>(existing ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const score = catalog.dinacharya.reduce((s, i) => s + (routine[i.id] ? i.points : 0), 0);

  const toggleFood = (meal: string, food: string) =>
    setMeals((m) => {
      const list = m[meal] ?? [];
      return { ...m, [meal]: list.includes(food) ? list.filter((f) => f !== food) : [...list, food] };
    });

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const log = await api.saveDaily(day, { dinacharya: routine, meals });
      setSaved(log);
      onSaved();
      toast(log.analysis?.viruddha.length
        ? `Saved. ${log.analysis.viruddha.length} food-compatibility alert${log.analysis.viruddha.length > 1 ? 's' : ''} below.`
        : `Saved · routine score ${log.score}`, log.analysis?.viruddha.length ? 'info' : 'success');
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <T v="h1">Today · {new Date(day).toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'short' })}</T>
      <Columns min={380}>
        <Card title="Dinacharya (daily routine)" right={<T v="h3">{score}/100</T>}>
          <Bar label="Routine score" value={score / 100} color={c.accent} />
          {catalog.dinacharya.map((i) => (
            <Chip key={i.id} label={`${i.label} (+${i.points})`} selected={!!routine[i.id]}
              onPress={() => setRoutine((r) => ({ ...r, [i.id]: !r[i.id] }))} />
          ))}
        </Card>
        <Card title="What did you eat?">
          {catalog.meals.map((meal) => (
            <Card key={meal} title={meal}>
              <Row>
                {catalog.foods.map((f) => (
                  <Chip key={f.id} label={f.label} selected={(meals[meal] ?? []).includes(f.id)} onPress={() => toggleFood(meal, f.id)} />
                ))}
              </Row>
            </Card>
          ))}
        </Card>
      </Columns>
      <ErrorText error={error} />
      <Button label={saved ? 'Update today' : 'Save today'} onPress={save} loading={busy} />
      {saved?.analysis && (
        <Columns min={330}>
          <Card title="Today's tastes (Rasa)">
            {Object.entries(saved.analysis.tastes).map(([t, n]) => (
              <Bar key={t} label={pretty(t)} value={Math.min(1, n / 4)} color={c.accent} display={`${n}×`} />
            ))}
            {saved.analysis.missing_tastes.length > 0 && (
              <T v="small">Missing today: {saved.analysis.missing_tastes.map(pretty).join(', ')} - a balanced meal has all six.</T>
            )}
          </Card>
          <Card title="Effect on the doshas">
            {DOSHA_ORDER.map((d) => {
              const v = saved.analysis!.dosha_effect[d];
              return <T key={d}>{pretty(d)}: {v > 0 ? `▲ aggravated (+${v})` : v < 0 ? `▼ pacified (${v})` : '● neutral'}</T>;
            })}
            <T v="small">From the six tastes (Charaka Sutra 26): sweet, sour and salty calm Vata; sweet, bitter and astringent calm Pitta; pungent, bitter and astringent calm Kapha.</T>
          </Card>
          {saved.analysis.viruddha.length > 0 ? (
            <Notice tone="warning">
              <T v="h3">Incompatible combinations (Viruddha ahara)</T>
              {saved.analysis.viruddha.map((v, i) => <T key={i}>• {pretty(v.meal)}: {v.message}</T>)}
            </Notice>
          ) : <Notice><T>No incompatible food combinations today.</T></Notice>}
        </Columns>
      )}
    </Screen>
  );
}
