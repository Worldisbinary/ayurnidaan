import { useQueryClient } from '@tanstack/react-query';
import { createContext, use, useCallback, useEffect, useMemo, useRef, useState, type PropsWithChildren } from 'react';

import { api, bindTokens } from './api';
import { getItem, setItem } from './storage';
import type { Tokens, User } from './types';

const KEY = 'ayurnidaan.session';

interface SessionValue {
  isLoading: boolean;
  user: User | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (b: { email: string; password: string; full_name: string; role: string; registration_number?: string }) => Promise<void>;
  signOut: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function useSession(): SessionValue {
  const v = use(SessionContext);
  if (!v) throw new Error('useSession must be used inside <SessionProvider>');
  return v;
}

export function SessionProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const tokens = useRef<Tokens | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setLoading] = useState(true);

  const store = useCallback((t: Tokens | null) => {
    tokens.current = t;
    void setItem(KEY, t ? JSON.stringify(t) : null);
    if (!t) {
      setUser(null);
      queryClient.clear(); // never let the next person on a shared device see cached health data
    }
  }, [queryClient]);

  useEffect(() => {
    bindTokens({ get: () => tokens.current, set: store });
    (async () => {
      try {
        const raw = await getItem(KEY);
        if (raw) {
          tokens.current = JSON.parse(raw) as Tokens;
          setUser(await api.me());
        }
      } catch {
        store(null);
      } finally {
        setLoading(false);
      }
    })();
  }, [store]);

  const value = useMemo<SessionValue>(
    () => ({
      isLoading,
      user,
      signIn: async (email, password) => {
        queryClient.clear();
        store(await api.login(email, password));
        setUser(await api.me());
      },
      signUp: async (b) => {
        queryClient.clear();
        store(await api.register(b));
        setUser(await api.me());
      },
      signOut: async () => store(null),
      refreshUser: async () => setUser(await api.me()),
    }),
    [isLoading, user, store, queryClient],
  );

  return <SessionContext value={value}>{children}</SessionContext>;
}
