import { useQuery } from '@tanstack/react-query';

import { Card, Columns, EmptyState, Notice, Screen, SkeletonCards, T, Table } from '@/components/ui';
import { api } from '@/lib/api';
import { pretty } from '@/lib/theme';

type Row = Record<string, string | number>;

export default function Insights() {
  const q = useQuery({ queryKey: ['insights'], queryFn: api.insights });
  const d = q.data as { k_anonymity: number; n_confirmed: number; ritu_body_system: Row[]; desha_dosha: Row[];
    ritu_condition: Row[] } | undefined;
  const table = (rows: Row[], keys: string[]) =>
    rows.length ? <Table head={[...keys.map(pretty), 'Cases']} rows={rows.map((r) => [...keys.map((k) => pretty(String(r[k]))), String(r.count)])} />
      : <EmptyState icon="shield-checkmark-outline" title="Hidden for privacy"
          message="Patterns appear once each group has enough confirmed cases to keep patients anonymous." />;
  return (
    <Screen onRefresh={() => q.refetch()} refreshing={q.isFetching}>
      <T v="h1">Population patterns</T>
      {!d ? <SkeletonCards count={3} min={380} /> : (
        <>
          <Notice><T v="small">{d.n_confirmed} confirmed diagnoses. Groups smaller than {d.k_anonymity} patients are hidden to protect privacy.</T></Notice>
          <Columns min={380}>
            <Card title="Season × body system">{table(d.ritu_body_system, ['ritu', 'body_system'])}</Card>
            <Card title="Habitat × dosha">{table(d.desha_dosha, ['desha', 'dosha'])}</Card>
            <Card title="Season × condition">{table(d.ritu_condition, ['ritu', 'condition'])}</Card>
          </Columns>
        </>
      )}
    </Screen>
  );
}
