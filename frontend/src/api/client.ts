// Вызовы API (docs/plan.md, 4.4). Ответы и ошибки приводятся к типам контракта из ./types.
import type {
  ApiErrorBody,
  CompareResponse,
  FeedRequest,
  FeedResponse,
  MetaResponse,
  ModelCard,
  Profile,
  ProfilesResponse,
  RecommendRequest,
  RecommendResponse,
  UsersResponse,
} from './types';

/** Сообщение, когда сервис не дал пригодного ответа. */
export const NETWORK_MESSAGE = 'Сервис не ответил';

const TIMEOUT_MS = 15_000;

export type ApiErrorDetail = ApiErrorBody['error']['details'][number];

export class ApiError extends Error {
  /** HTTP-статус; 0 — ответа не было */
  readonly status: number;
  readonly details: ApiErrorDetail[];
  readonly code: string | null;
  /** true — сбой сети, таймаут или ответ без тела ошибки: сообщения сервера нет */
  readonly network: boolean;

  constructor(message: string, status: number, details: ApiErrorDetail[], code: string | null, network: boolean) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
    this.code = code;
    this.network = network;
  }
}

export function isAbortError(error: unknown): boolean {
  return typeof error === 'object' && error !== null && (error as { name?: unknown }).name === 'AbortError';
}

/** 422, детали которой указывают на поле задачи: сообщение выводится под полем. */
export function isTaskFieldError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 422 &&
    error.details.some((d) => d.field.split(/[^A-Za-z0-9_]+/).includes('task'))
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function networkError(status = 0): ApiError {
  return new ApiError(NETWORK_MESSAGE, status, [], null, true);
}

function httpError(status: number, data: unknown): ApiError {
  const error = isRecord(data) ? data.error : undefined;
  if (!isRecord(error) || typeof error.message !== 'string' || !error.message.trim()) {
    return networkError(status);
  }
  const details: ApiErrorDetail[] = Array.isArray(error.details)
    ? error.details
        .filter(isRecord)
        .filter((d) => typeof d.field === 'string' && typeof d.message === 'string')
        .map((d) => ({ field: String(d.field), message: String(d.message) }))
    : [];
  const code = typeof error.code === 'string' ? error.code : null;
  return new ApiError(error.message.trim(), status, details, code, false);
}

async function request(method: 'GET' | 'POST', path: string, body: unknown, signal?: AbortSignal): Promise<unknown> {
  // Свой контроллер: отмена вызывающим и таймаут различаются
  const controller = new AbortController();
  const forwardAbort = () => {
    controller.abort(signal?.reason);
  };
  if (signal?.aborted) controller.abort(signal.reason);
  else signal?.addEventListener('abort', forwardAbort, { once: true });
  // Флаг ставит таймер в замыкании. Без «as boolean» TypeScript сузил бы тип до false и счёл проверки ниже лишними
  let timedOut = false as boolean;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TIMEOUT_MS);

  try {
    let response: Response;
    try {
      response = await fetch(path, {
        method,
        headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
        // Для fetch null и отсутствие тела равнозначны. При exactOptionalPropertyTypes
        // RequestInit.body не принимает undefined
        body: body === undefined ? null : JSON.stringify(body),
        credentials: 'same-origin',
        signal: controller.signal,
      });
    } catch (error) {
      if (signal?.aborted && !timedOut) throw error;
      throw networkError();
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch (error) {
      if (signal?.aborted && !timedOut) throw error;
      if (timedOut) throw networkError();
      data = undefined;
    }

    if (!response.ok) throw httpError(response.status, data);
    if (data === undefined) throw networkError(response.status);
    return data;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forwardAbort);
  }
}

function isRecommendResponse(value: unknown): value is RecommendResponse {
  return (
    isRecord(value) &&
    typeof value.status === 'string' &&
    typeof value.message === 'string' &&
    Array.isArray(value.items) &&
    typeof value.total_candidates === 'number'
  );
}

export async function getMeta(signal?: AbortSignal): Promise<MetaResponse> {
  const data = await request('GET', '/api/meta', undefined, signal);
  if (!isRecord(data) || !Array.isArray(data.stages) || typeof data.max_task_length !== 'number') throw networkError(200);
  return data as unknown as MetaResponse;
}

/** Тестовые профили; null — демо-режим выключен (404). */
export async function getProfiles(signal?: AbortSignal): Promise<Profile[] | null> {
  try {
    const data = (await request('GET', '/api/profiles', undefined, signal)) as Partial<ProfilesResponse> | null;
    return Array.isArray(data?.profiles) ? data.profiles : [];
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Клиенты подключённого журнала, код которых начинается с query; null — демо-режим выключен (404). */
export async function getUsers(query = '', signal?: AbortSignal): Promise<UsersResponse | null> {
  try {
    const data = await request('GET', `/api/users?q=${encodeURIComponent(query)}`, undefined, signal);
    if (!isRecord(data) || !Array.isArray(data.users) || typeof data.total !== 'number') throw networkError(200);
    return data as unknown as UsersResponse;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Паспорт модели ленты; null — паспорт не записан (404). */
export async function getModelCard(signal?: AbortSignal): Promise<ModelCard | null> {
  try {
    const data = await request('GET', '/api/model-card', undefined, signal);
    if (!isRecord(data) || !Array.isArray(data.groups) || !Array.isArray(data.weights)) throw networkError(200);
    return data as unknown as ModelCard;
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

export async function recommend(body: RecommendRequest, signal?: AbortSignal): Promise<RecommendResponse> {
  const data = await request('POST', '/api/recommend', body, signal);
  if (!isRecommendResponse(data)) throw networkError(200);
  return data;
}

/** Лента по профилю: до 50 материалов с составом оценки по источникам */
export async function feed(body: FeedRequest, signal?: AbortSignal): Promise<FeedResponse> {
  const data = await request('POST', '/api/feed', body, signal);
  if (!isRecord(data) || typeof data.status !== 'string' || !Array.isArray(data.items) || !Array.isArray(data.history)) {
    throw networkError(200);
  }
  return data as unknown as FeedResponse;
}

export async function compare(body: RecommendRequest, signal?: AbortSignal): Promise<CompareResponse> {
  const data = await request('POST', '/api/compare', body, signal);
  if (
    !isRecord(data) ||
    !isRecommendResponse(data.baseline) ||
    !isRecommendResponse(data.personal) ||
    !isRecord(data.diff)
  ) {
    throw networkError(200);
  }
  return data as unknown as CompareResponse;
}
