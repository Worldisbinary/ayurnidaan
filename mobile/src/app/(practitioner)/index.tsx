import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';

import { Badge, Card, Chip, ErrorText, Loading, Notice, Row, Screen, T, Table } from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { pretty } from '@/lib/theme';

export default function Queue() {
  const { user } = useSession();
  const [status, setStatus] = useState<'submitted' | 'reviewed'>('submitted');
  const q = useQuery({ queryKey: ['queue', status], queryFn: () => api.queue(status), enabled: !!user?.practitioner_verified,
    refetchInterval: 30_000 });

  if (!user?.practitioner_verified) {
    return (
      <Screen>
        <T v="h1">Awaiting verification</T>
        <Notice><T>An administrator is checking registration number against the State / NCISM register.
          You will see patient cases once verified.</T></Notice>
      </Screen>
    );
  }
  const rows = q.data ?? [];
  const counts = { emergency: 0, urgent: 0, routine: 0 };
  rows.forEach((r) => counts[r.triage_level]++);

  return (
    <Screen onRefresh={() => q.refetch()} refreshing={q.isFetching}>
      <Row style={{ justifyContent: 'space-between' }}>
        <T v="h1">Case queue</T>
        <Row>
          <Chip label="Awaiting review" selected={status === 'submitted'} onPress={() => setStatus('submitted')} />
          <Chip label="Reviewed" selected={status === 'reviewed'} onPress={() => setStatus('reviewed')} />
        </Row>
      </Row>
      <Row>
        <Badge status="emergency" /><T>{counts.emergency}</T>
        <Badge status="urgent" /><T>{counts.urgent}</T>
        <Badge status="routine" /><T>{counts.routine}</T>
      </Row>
      <ErrorText error={q.error} />
      <Card title={`${rows.length} cases · emergencies first`}>
        {q.isLoading ? <Loading /> : rows.length ? (
          <Table head={['Triage', 'Received', 'Patient', 'Complaint', 'Top condition', 'Vikriti', 'Ritu', 'Mine']}
            flex={[1.2, 1.1, 1.1, 2, 2, 0.9, 0.9, 0.5]}
            rows={rows.map((r) => [
              <Badge key="t" status={r.triage_level} />,
              new Date(r.created_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
              `${r.patient.age ?? '?'}${r.patient.sex ? r.patient.sex[0].toUpperCase() : ''} · ${r.patient.desha ?? '—'}`,
              r.chief_complaint ?? '—',
              r.top_condition ? `${r.top_condition} (${Math.round((r.top_likelihood ?? 0) * 100)}%)` : '—',
              pretty(r.vikriti), pretty(r.ritu), r.assigned_to_me ? '●' : '',
            ])}
            onRowPress={(i) => router.push(`/(practitioner)/case/${rows[i].id}`)} />
        ) : <T v="muted">No cases.</T>}
      </Card>
    </Screen>
  );
}
