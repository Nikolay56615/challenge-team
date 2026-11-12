// Состояние экрана: форма, история сеанса, жизненный цикл запроса (PLAN.md, 5.2–5.6).
import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { ApiError, NETWORK_MESSAGE, compare, isAbortError, isTaskFieldError, recommend } from '../api/client';
import type {
  CompareResponse,
  ExperienceCode,
  FormatPrefCode,
  HistoryEvent,
  IndustryCode,
  MaterialFilters,
  Profile,
  RecommendRequest,
  RecommendResponse,
  StageCode,
  TopicCode,
} from '../api/types';

export const DEFAULT_LIMIT = 5;
export const MAX_LIMIT = 10;
const HISTORY_LIMIT = 200;

export interface FormValues {
  task: string;
  stage: StageCode | null;
  experience: ExperienceCode | null;
  format_pref: FormatPrefCode | null;
  industry: IndustryCode | null;
}

export type RefinementValues = Omit<FormValues, 'task'>;

export const EMPTY_FORM: FormValues = { task: '', stage: null, experience: null, format_pref: null, industry: null };

export type CallKind = 'recommend' | 'compare';

/** Отправленный запрос: вид вызова и точное тело */
export interface Call {
  kind: CallKind;
  body: RecommendRequest;
}

export type Outcome =
  | { kind: 'recommend'; response: RecommendResponse }
  | { kind: 'compare'; response: CompareResponse };

export interface RequestFailure {
  message: string;
  /** Сообщения сервера нет: сбой сети, таймаут, ответ без тела ошибки */
  network: boolean;
}

export type Section = 'recommend' | 'catalog';

interface ResultState {
  loading: boolean;
  outcome: Outcome | null;
  /** Запрос, по которому получен outcome: «Показать ещё», тема, «Отметить изученным» */
  resultCall: Call | null;
  /** Последний отправленный запрос: «Повторить» */
  lastCall: Call | null;
  failure: RequestFailure | null;
  fieldError: string | null;
  /** «Оставить как есть»: уточнение скрыто до нового запроса из формы */
  clarificationHidden: boolean;
  /** Идёт новый запрос из формы, а не повтор прежнего с другой темой, лимитом или историей */
  newQuery: boolean;
}

const initialState: ResultState = {
  loading: false,
  outcome: null,
  resultCall: null,
  lastCall: null,
  failure: null,
  fieldError: null,
  clarificationHidden: false,
  newQuery: false,
};

type Action =
  | { type: 'clearFieldError' }
  | { type: 'start'; call: Call; newQuery: boolean }
  | { type: 'success'; call: Call; outcome: Outcome }
  | { type: 'failure'; failure: RequestFailure | null; fieldError: string | null }
  | { type: 'hideClarification' }
  | { type: 'reset' };

function reducer(state: ResultState, action: Action): ResultState {
  switch (action.type) {
    case 'clearFieldError':
      return { ...state, fieldError: null };
    case 'start':
      return {
        ...state,
        loading: true,
        lastCall: action.call,
        failure: null,
        fieldError: null,
        newQuery: action.newQuery,
        clarificationHidden: action.newQuery ? false : state.clarificationHidden,
      };
    case 'success':
      return { ...state, loading: false, outcome: action.outcome, resultCall: action.call, failure: null };
    case 'failure':
      // Ошибка поля оставляет прежнюю выдачу; ошибка сервиса заменяет её баннером
      return action.fieldError
        ? { ...state, loading: false, fieldError: action.fieldError }
        : { ...state, loading: false, failure: action.failure, outcome: null, resultCall: null };
    case 'hideClarification':
      return { ...state, clarificationHidden: true };
    case 'reset':
      return initialState;
  }
}

function failureAction(error: unknown): Action {
  if (isTaskFieldError(error)) return { type: 'failure', failure: null, fieldError: error.message };
  if (error instanceof ApiError) {
    return { type: 'failure', failure: { message: error.message, network: error.network }, fieldError: null };
  }
  return { type: 'failure', failure: { message: NETWORK_MESSAGE, network: true }, fieldError: null };
}

/** Событие complete с seq = max(seq) + 1; история не длиннее предела API */
export function appendComplete(history: readonly HistoryEvent[], materialId: string): HistoryEvent[] {
  const seq = history.reduce((max, event) => Math.max(max, event.seq), 0) + 1;
  const next: HistoryEvent[] = [...history, { material_id: materialId, event: 'complete', seq }];
  return next.length > HISTORY_LIMIT ? next.slice(next.length - HISTORY_LIMIT) : next;
}

function useResult(active: boolean, history: HistoryEvent[]) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const controllerRef = useRef<AbortController | null>(null);
  // Номер последнего запроса: обновлять состояние может только он
  const seqRef = useRef(0);

  useEffect(
    () => () => {
      seqRef.current += 1;
      controllerRef.current?.abort();
    },
    [],
  );

  const run = useCallback((call: Call, newQuery = false) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const seq = ++seqRef.current;
    dispatch({ type: 'start', call, newQuery });

    const pending: Promise<Outcome> =
      call.kind === 'compare'
        ? compare(call.body, controller.signal).then((response): Outcome => ({ kind: 'compare', response }))
        : recommend(call.body, controller.signal).then((response): Outcome => ({ kind: 'recommend', response }));

    pending
      .then(
        (outcome) => {
          if (seq === seqRef.current) dispatch({ type: 'success', call, outcome });
        },
        (error: unknown) => {
          if (seq !== seqRef.current || isAbortError(error)) return;
          dispatch(failureAction(error));
        },
      )
      .finally(() => {
        if (controllerRef.current === controller) controllerRef.current = null;
      });
  }, []);

  /** Отменяет запрос в работе: его ответ больше не меняет состояние */
  const cancel = () => {
    seqRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
  };

  useEffect(() => {
    const call = state.resultCall;
    // Каждый запрос хранит снимок истории. Скрытая выдача обновляется только при возвращении.
    if (active && call && !state.loading && !state.fieldError && call.body.history !== history) {
      run({ kind: call.kind, body: { ...call.body, history } });
    }
  }, [active, history, run, state.fieldError, state.loading, state.resultCall]);

  return {
    state,
    run,
    reset: () => {
      cancel();
      dispatch({ type: 'reset' });
    },
    clearFieldError: () => dispatch({ type: 'clearFieldError' }),
    hideClarification: () => dispatch({ type: 'hideClarification' }),
  };
}

export function useRecommend(section: Section) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [history, setHistory] = useState<HistoryEvent[]>([]);
  const [profileId, setProfileId] = useState<string | null>(null);
  const [compareMode, setCompare] = useState(false);
  const [topic, setTopic] = useState<{ value: TopicCode; task: string } | null>(null);
  const recommendation = useResult(section === 'recommend', history);
  const catalog = useResult(section === 'catalog', history);

  const bodyFromForm = (): RecommendRequest => ({
    ...form,
    topic: topic?.task === form.task ? topic.value : null,
    history,
    profile_id: profileId,
    limit: DEFAULT_LIMIT,
    method: 'personal',
  });

  const resultActions = ({ state, run, hideClarification }: ReturnType<typeof useResult>) => {
    const rerun = (call: Call | null, patch?: Partial<RecommendRequest>) => {
      if (call && !state.loading) run({ kind: call.kind, body: { ...call.body, history, ...patch } });
    };
    return {
      applyFilters: (filters: MaterialFilters | null) => rerun(state.resultCall, { filters, limit: DEFAULT_LIMIT }),
      showMore: () => rerun(state.resultCall, { limit: MAX_LIMIT }),
      markComplete: (materialId: string) => {
        if (!state.resultCall || state.loading) return;
        const updated = appendComplete(history, materialId);
        setHistory(updated);
        rerun(state.resultCall, { history: updated });
      },
      retry: () => rerun(state.lastCall),
      hideClarification,
    };
  };

  const runFromForm = (result: ReturnType<typeof useResult>, body: RecommendRequest) => {
    if (!result.state.loading) result.run({ kind: compareMode ? 'compare' : 'recommend', body }, true);
  };

  const clearResults = () => {
    setTopic(null);
    recommendation.reset();
    catalog.reset();
  };

  return {
    form,
    profileId,
    compare: compareMode,
    topic: topic?.value ?? null,
    setCompare,
    setTask: (task: string) => {
      setForm((current) => ({ ...current, task }));
      setTopic(null);
      recommendation.clearFieldError();
    },
    setRefinements: (patch: Partial<RefinementValues>) => setForm((current) => ({ ...current, ...patch })),
    selectProfile: (profile: Profile | null) => {
      clearResults();
      setProfileId(profile?.id ?? null);
      setHistory(profile?.history ?? []);
      if (profile) {
        const { task, stage, experience, format_pref, industry } = profile;
        setForm({ task, stage, experience, format_pref, industry });
      }
    },
    reset: () => {
      clearResults();
      setForm(EMPTY_FORM);
      setProfileId(null);
      setHistory([]);
      setCompare(false);
    },
    recommendation: {
      state: recommendation.state,
      actions: resultActions(recommendation),
      submit: () => runFromForm(recommendation, bodyFromForm()),
      chooseTopic: (value: TopicCode) => {
        const call = recommendation.state.resultCall;
        if (!call || recommendation.state.loading) return;
        setTopic({ value, task: call.body.task });
        recommendation.run({ kind: call.kind, body: { ...call.body, topic: value, limit: DEFAULT_LIMIT, history } });
      },
    },
    catalog: {
      state: catalog.state,
      actions: resultActions(catalog),
      browseTopic: (value: TopicCode) => runFromForm(catalog, { ...bodyFromForm(), task: '', topic: value }),
    },
  };
}

export type RecommendationResult = ReturnType<typeof useRecommend>['recommendation'];
