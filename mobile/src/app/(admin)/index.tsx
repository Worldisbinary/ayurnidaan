import { useMutation, useQuery } from '@tanstack/react-query';

import { Button, Card, Columns, ErrorText, KV, Loading, Notice, Row, Screen, T, Table } from '@/components/ui';
import { api } from '@/lib/api';
import { useSession } from '@/lib/session';

export default function AdminHome() {
  const { signOut } = useSession();
  const pending = useQuery({ queryKey: ['pending'], queryFn: api.pendingPractitioners });
  const learning = useQuery({ queryKey: ['learning'], queryFn: api.learning });
  const audit = useQuery({ queryKey: ['audit'], queryFn: api.audit });
  const verify = useMutation({ mutationFn: (id: string) => api.verify(id), onSuccess: () => pending.refetch() });
  const retrain = useMutation({ mutationFn: api.retrain, onSuccess: () => learning.refetch() });

  return (
    <Screen onRefresh={() => { pending.refetch(); learning.refetch(); audit.refetch(); }} refreshing={pending.isFetching}>
      <Row style={{ justifyContent: 'space-between' }}>
        <T v="h1">Administration</T>
        <Button label="Sign out" variant="ghost" compact onPress={signOut} />
      </Row>
      <Columns min={420}>
        <Card title="Practitioners awaiting verification">
          {pending.isLoading ? <Loading /> : pending.data?.length ? pending.data.map((p) => (
            <Row key={p.id} style={{ justifyContent: 'space-between' }}>
              <T style={{ flex: 1 }}>{p.full_name} · {p.registration_number}{'\n'}<T v="small">{p.email}</T></T>
              <Button label="Verify" compact onPress={() => verify.mutate(p.id)} loading={verify.isPending} />
            </Row>
          )) : <T v="muted">None pending.</T>}
          <T v="small">Check each registration number against the State Board / NCISM register before verifying.</T>
        </Card>
        <Card title="Learning loop">
          {learning.data ? (
            <KV items={[['Active model', learning.data.active_version], ['Eligible confirmed cases', String(learning.data.eligible_cases)]]} />
          ) : <Loading />}
          <Button label="Retrain from confirmed cases" onPress={() => retrain.mutate()} loading={retrain.isPending} />
          {retrain.data && (
            <Notice tone={retrain.data.promoted ? 'info' : 'warning'}>
              <T>{retrain.data.promoted ? `Promoted ${retrain.data.version}` : `Not promoted: ${retrain.data.reason}`}</T>
            </Notice>
          )}
          <ErrorText error={retrain.error} />
        </Card>
      </Columns>
      <Card title="Audit log (latest)">
        {audit.data ? (
          <Table head={['When', 'Actor', 'Action', 'Entity']} flex={[1.4, 1.2, 1.4, 1.6]}
            rows={audit.data.slice(0, 60).map((r) => [new Date(r.at).toLocaleString(), r.actor?.slice(0, 8) ?? '—', r.action,
              `${r.entity ?? ''} ${r.entity_id?.slice(0, 8) ?? ''}`])} />
        ) : <Loading />}
      </Card>
    </Screen>
  );
}
