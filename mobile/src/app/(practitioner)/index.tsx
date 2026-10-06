import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';

import {
  Badge, Card, Chip, EmptyState, ErrorText, Notice, Row, Screen, Skeleton, StatRow, StatTile, T, Table,
} from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';
import { pretty } from '@/lib/theme';

function QueueSkeleton() {
  return (
    <>
      {Array.from({ length: 5 }, (_, i) => (
        <Row key={i} style={{ paddingVertical: 8, flexWrap: 'nowrap' }}>
          <Skeleton h={16} w={80} r={8} /><Skeleton h={10} w="15%" /><Skeleton h={10} w="35%" /><Skeleton h={10} w="30%" />
        </Row>
      ))}
    </>
  );
}

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
      <StatRow>
        <StatTile label="Emergency" value={counts.emergency} icon="alert-circle" tone={counts.emergency ? 'critical' : 'muted'}
          hint="call the patient first" />
        <StatTile label="Urgent" value={counts.urgent} icon="warning" tone={counts.urgent ? 'warning' : 'muted'} hint="review today" />
        <StatTile label="Routine" value={counts.routine} icon="checkmark-circle" tone="good" hint="review this week" />
        <StatTile label="Assigned to me" value={rows.filter((r) => r.assigned_to_me).length} icon="person-outline" tone="accent"
          hint={status === 'submitted' ? 'awaiting review' : 'reviewed'} />
      </StatRow>
      <ErrorText error={q.error} />
      <Card title={`${rows.length} cases · emergencies first`}>
        {q.isLoading ? <QueueSkeleton /> : rows.length ? (
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
        ) : (
          <EmptyState icon={status === 'submitted' ? 'checkmark-done-outline' : 'file-tray-outline'}
            title={status === 'submitted' ? 'Queue is clear' : 'No reviewed cases yet'}
            message={status === 'submitted'
              ? 'New cases appear here as soon as a patient shares a check-up. The queue refreshes every 30 seconds.'
              : 'Cases you confirm or revise are listed here.'} />
        )}
      </Card>
    </Screen>
  );
}
