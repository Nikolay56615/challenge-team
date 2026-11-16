// Справочники формы, тестовые профили и клиенты демо-режима
import { useCallback, useEffect, useState } from 'react';
import { getMeta, getProfiles, getUsers, isAbortError } from '../api/client';
import type { MetaResponse, Profile, UsersResponse } from '../api/types';

export const DEFAULT_MAX_TASK_LENGTH = 300;

export interface MetaState {
  meta: MetaResponse | null;
  /** null — демо-режим выключен или профили не загружены */
  profiles: Profile[] | null;
  /** Клиенты для ленты по профилю; null — демо-режим выключен или список не загружен */
  users: UsersResponse | null;
  failed: boolean;
  /** Список клиентов запрошен, но сервис не ответил: это не то же, что «клиентов нет» */
  usersFailed: boolean;
}

export function useMeta() {
  const [state, setState] = useState<MetaState>({
    meta: null,
    profiles: null,
    users: null,
    failed: false,
    usersFailed: false,
  });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    void Promise.allSettled([getMeta(signal), getProfiles(signal), getUsers('', signal)]).then(
      ([meta, profiles, users]) => {
        if (signal.aborted) return;
        if (meta.status === 'rejected' && isAbortError(meta.reason)) return;
        setState((prev) => ({
          meta: meta.status === 'fulfilled' ? meta.value : prev.meta,
          profiles: profiles.status === 'fulfilled' ? profiles.value : prev.profiles,
          users: users.status === 'fulfilled' ? users.value : prev.users,
          failed: meta.status === 'rejected' && !prev.meta,
          usersFailed: users.status === 'rejected' && !isAbortError(users.reason),
        }));
      },
    );
    return () => {
      controller.abort();
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);
  return { ...state, reload };
}
