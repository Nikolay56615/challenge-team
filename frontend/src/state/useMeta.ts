// Справочники формы и тестовые профили демо-режима
import { useCallback, useEffect, useState } from 'react';
import { getMeta, getProfiles, isAbortError } from '../api/client';
import type { MetaResponse, Profile } from '../api/types';

export const DEFAULT_MAX_TASK_LENGTH = 300;

export interface MetaState {
  meta: MetaResponse | null;
  /** null — демо-режим выключен или профили не загружены */
  profiles: Profile[] | null;
  failed: boolean;
}

export function useMeta() {
  const [state, setState] = useState<MetaState>({ meta: null, profiles: null, failed: false });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled([getMeta(controller.signal), getProfiles(controller.signal)]).then(([meta, profiles]) => {
      if (controller.signal.aborted) return;
      if (meta.status === 'rejected' && isAbortError(meta.reason)) return;
      setState((prev) => ({
        meta: meta.status === 'fulfilled' ? meta.value : prev.meta,
        profiles: profiles.status === 'fulfilled' ? profiles.value : prev.profiles,
        failed: meta.status === 'rejected' && !prev.meta,
      }));
    });
    return () => {
      controller.abort();
    };
  }, [attempt]);

  const reload = useCallback(() => {
    setAttempt((n) => n + 1);
  }, []);
  return { ...state, reload };
}
