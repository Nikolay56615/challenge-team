// Состояние экрана: форма, история сеанса, жизненный цикл запроса (docs/plan.md, 5.2–5.6).
import { useEffect, useReducer, useRef } from 'react';
import { ApiError, NETWORK_MESSAGE, compare, isAbortError, isTaskFieldError, recommend } from '../api/client';
import type {
  CompareResponse,
  ExperienceCode,
  FormatPrefCode,
  HistoryEvent,
  IndustryCode,
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

export interface RecommendState {
  form: FormValues;
  /** Тема, выбранная в уточнении; сбрасывается при изменении задачи, смене профиля и «Сбросить» */
  topic: TopicCode | null;
  /** Задача запроса, к которому выбрана тема: с другой задачей тема не отправляется */
  topicTask: string | null;
  history: HistoryEvent[];
  profileId: string | null;
  compare: boolean;
  loading: boolean;
  outcome: Outcome | null;
  /** Запрос, по которому получен outcome: «Показать ещё», тема, «Отметить изученным» */
  resultCall: Call | null;
  /** Последний отправленный запрос: «Повторить» */
  lastCall: Call | null;
  /**
   * Ошибка последнего ответа. Во время загрузки остаётся до нового ответа: экран по ней понимает, что до запроса
   * показывал ошибку, а не начальный экран (D10), но баннер ошибки при загрузке не выводит
   */
  failure: RequestFailure | null;
  fieldError: string | null;
  /** «Оставить как есть»: уточнение скрыто до ответа на новый запрос из формы */
  clarificationHidden: boolean;
  /** Идёт новый запрос из формы, а не повтор прежнего с другой темой, лимитом или историей */
  newQuery: boolean;
}

const initialState: RecommendState = {
  form: EMPTY_FORM,
  topic: null,
  topicTask: null,
  history: [],
  profileId: null,
  compare: false,
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
  | { type: 'task'; value: string }
  | { type: 'fields'; patch: Partial<RefinementValues> }
  | { type: 'profile'; profile: Profile | null }
  | { type: 'compare'; value: boolean }
  | { type: 'topic'; value: TopicCode; task: string }
  | { type: 'history'; history: HistoryEvent[] }
  | { type: 'start'; call: Call; newQuery: boolean }
  | { type: 'success'; call: Call; outcome: Outcome }
  | { type: 'failure'; failure: RequestFailure | null; fieldError: string | null }
  | { type: 'hideClarification' }
  | { type: 'reset' };

function reducer(state: RecommendState, action: Action): RecommendState {
  switch (action.type) {
    case 'task':
      return { ...state, form: { ...state.form, task: action.value }, topic: null, topicTask: null, fieldError: null };
    case 'fields':
      return { ...state, form: { ...state.form, ...action.patch } };
    case 'profile': {
      // Смена профиля начинает новый сеанс: выдача прежнего профиля, его тема и история сбрасываются.
      // «Не выбран» оставляет введённые данные формы, но не историю профиля.
      const profile = action.profile;
      const fresh: RecommendState = {
        ...state,
        topic: null,
        topicTask: null,
        loading: false,
        outcome: null,
        resultCall: null,
        lastCall: null,
        failure: null,
        fieldError: null,
        clarificationHidden: false,
        newQuery: false,
      };
      if (!profile) return { ...fresh, profileId: null, history: [] };
      return {
        ...fresh,
        profileId: profile.id,
        form: {
          task: profile.task,
          stage: profile.stage,
          experience: profile.experience,
          format_pref: profile.format_pref,
          industry: profile.industry,
        },
        history: profile.history.map((event) => ({ ...event })),
      };
    }
    case 'compare':
      return { ...state, compare: action.value };
    case 'topic':
      return { ...state, topic: action.value, topicTask: action.task };
    case 'history':
      return { ...state, history: action.history };
    case 'start':
      // Прежний ответ, его ошибка и скрытое уточнение остаются до нового ответа: пока не появились скелетоны,
      // экран держит прежнее содержимое (кандидат D10)
      return { ...state, loading: true, lastCall: action.call, fieldError: null, newQuery: action.newQuery };
    case 'success':
      return {
        ...state,
        loading: false,
        outcome: action.outcome,
        resultCall: action.call,
        failure: null,
        clarificationHidden: state.newQuery ? false : state.clarificationHidden,
      };
    case 'failure':
      // Ошибка поля оставляет прежнюю выдачу; ошибка сервиса заменяет её баннером
      return action.fieldError
        ? { ...state, loading: false, failure: null, fieldError: action.fieldError }
        : {
            ...state,
            loading: false,
            failure: action.failure,
            outcome: null,
            resultCall: null,
            clarificationHidden: state.newQuery ? false : state.clarificationHidden,
          };
    case 'hideClarification':
      return { ...state, clarificationHidden: true };
    case 'reset':
      // Начальный экран: форма, тема, история, профиль, сравнение и выдача
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

export function useRecommend() {
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

  const run = (call: Call, newQuery = false) => {
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
  };

  /** Отменяет запрос в работе: его ответ больше не меняет состояние */
  const cancel = () => {
    seqRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
  };

  const bodyFromForm = (): RecommendRequest => ({
    task: state.form.task,
    stage: state.form.stage,
    experience: state.form.experience,
    format_pref: state.form.format_pref,
    industry: state.form.industry,
    // Тема выбрана для запроса с другой задачей: к новой задаче она не относится
    topic: state.topicTask === state.form.task ? state.topic : null,
    history: state.history.map((event) => ({ ...event })),
    profile_id: state.profileId,
    limit: DEFAULT_LIMIT,
    method: 'personal',
  });

  const actions = {
    setTask: (value: string) => {
      dispatch({ type: 'task', value });
    },
    setRefinements: (patch: Partial<RefinementValues>) => {
      dispatch({ type: 'fields', patch });
    },
    /** Профиль заполняет форму и историю; «Не выбран» очищает историю. Прежняя выдача сбрасывается */
    selectProfile: (profile: Profile | null) => {
      cancel();
      dispatch({ type: 'profile', profile });
    },
    setCompare: (value: boolean) => {
      dispatch({ type: 'compare', value });
    },

    /** «Подобрать материалы»: тело из формы, limit 5; при включённом сравнении — /api/compare */
    submit: () => {
      if (state.loading) return;
      run({ kind: state.compare ? 'compare' : 'recommend', body: bodyFromForm() }, true);
    },

    submitExample: (task: string, stage: StageCode | null) => {
      if (state.loading) return;
      dispatch({ type: 'task', value: task });
      dispatch({ type: 'fields', patch: { stage } });
      run({
        kind: state.compare ? 'compare' : 'recommend',
        body: { ...bodyFromForm(), task, stage, topic: null },
      }, true);
    },

    /** Выбор темы в уточнении: тот же запрос с полем topic; подборка по теме начинается с limit 5 */
    chooseTopic: (topic: TopicCode) => {
      const base = state.resultCall;
      if (!base) return;
      dispatch({ type: 'topic', value: topic, task: base.body.task });
      run({ kind: base.kind, body: { ...base.body, topic, limit: DEFAULT_LIMIT } });
    },

    /** «Показать ещё»: тот же запрос с limit 10 */
    showMore: () => {
      const base = state.resultCall;
      if (base) run({ kind: base.kind, body: { ...base.body, limit: MAX_LIMIT } });
    },

    /** «Отметить изученным»: событие в историю сеанса и повтор запроса с теми же параметрами */
    markComplete: (materialId: string) => {
      const history = appendComplete(state.history, materialId);
      dispatch({ type: 'history', history });
      const base = state.resultCall;
      if (base) run({ kind: base.kind, body: { ...base.body, history } });
    },

    /** «Повторить»: точное тело последнего запроса */
    retry: () => {
      if (state.lastCall) run(state.lastCall);
    },

    hideClarification: () => {
      dispatch({ type: 'hideClarification' });
    },

    /** «Сбросить»: форма, тема, история сеанса, профиль, сравнение и выдача */
    reset: () => {
      cancel();
      dispatch({ type: 'reset' });
    },
  };

  return { state, actions };
}
