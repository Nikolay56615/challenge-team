import { useEffect, useId, useMemo, useRef, useState, type SyntheticEvent } from 'react';
import { ApiError, feed as requestFeed, getUsers, isAbortError } from '../api/client';
import type {
  FeedHistoryEntry,
  FeedItem,
  FeedRequest,
  FeedResponse,
  HistoryEvent,
  IndustryCode,
  MetaResponse,
  StageCode,
  User,
} from '../api/types';
import { FAMILY_LABEL, FAMILY_ORDER, changeSentence, feedChange, formatShare } from '../feed';
import { typo } from '../format';
import { Banner, Button, Checkbox, Layout, Panel, SelectField, StatusLine, TextField, cx } from '../kit';
import { useScreenIsWide } from '../state/useScreenIsWide';
import { ClientCompare } from './ClientCompare';
import { CompareTable } from './CompareTable';
import { FeedCard } from './FeedCard';
import { ModelPassport } from './ModelPassport';

const FIRST_PAGE = 20;
const FULL_FEED = 50;
const LOADING_TEXT = 'Считаем ленту…';
const NETWORK_ERROR_TEXT = 'Сервис не ответил.';
/** Код клиента: те же знаки и длина, что принимает сервис */
const CODE_PATTERN = /^[A-Za-z0-9:_-]{1,64}$/;

export interface FeedScreenProps {
  /** history — клиент с историей из подключённого журнала; new — клиент без истории */
  mode: 'history' | 'new';
  /** Первые клиенты журнала в порядке показа; остальных открывает ввод кода */
  clients: readonly User[];
  meta: MetaResponse | null;
  onOpenTask: () => void;
  /** client — вид клиента: только карточки с причиной; product — оценки, расчёт и панели */
  audience: 'product' | 'client';
}

export function FeedScreen({ mode, clients, meta, onOpenTask, audience }: FeedScreenProps) {
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  // На узком экране сначала идут карточки: история и состав оценки переезжают под ленту
  const wide = useScreenIsWide(heading);
  const [clientId, setClientId] = useState<string | null>(clients[0]?.id ?? null);
  // Клиенты, открытые по коду: их нет среди первых клиентов журнала
  const [found, setFound] = useState<User[]>([]);
  const [code, setCode] = useState('');
  const [codeError, setCodeError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [stage, setStage] = useState<StageCode | null>(null);
  const [industry, setIndustry] = useState<IndustryCode | null>(null);
  const [excluded, setExcluded] = useState<string[]>([]);
  const [added, setAdded] = useState<HistoryEvent[]>([]);
  const [withPrice, setWithPrice] = useState(true);
  const [limit, setLimit] = useState(FIRST_PAGE);
  const [response, setResponse] = useState<FeedResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // Ключ запроса, на который уже пришёл ответ или ошибка: пока он отличается от текущего, идёт загрузка
  const [settled, setSettled] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // История до правок «что если»: по ней строятся отметки, которыми событие возвращают
  const [baseHistory, setBaseHistory] = useState<FeedHistoryEntry[]>([]);
  // Места карточек до последней правки «что если»
  const before = useRef<Map<string, number> | null>(null);
  const [change, setChange] = useState<ReturnType<typeof feedChange> | null>(null);
  // Лента прежнего клиента: после смены клиента экран называет число общих карточек
  const previous = useRef<{ id: string; cards: Set<string> } | null>(null);
  const [shared, setShared] = useState<{
    id: string;
    count: number;
    total: number;
  } | null>(null);
  // Клиент для сравнения и ответ на запрос его ленты; feed: null — запрос не удался
  const [compareId, setCompareId] = useState<string | null>(null);
  const [compared, setCompared] = useState<{
    key: string;
    feed: FeedResponse | null;
  } | null>(null);

  const body = useMemo<FeedRequest>(
    () => ({
      task: '',
      stage: mode === 'new' ? stage : null,
      experience: null,
      format_pref: null,
      industry: mode === 'new' ? industry : null,
      history: mode === 'new' ? [] : null,
      user_id: mode === 'history' ? clientId : null,
      exclude_history: excluded,
      add_history: added,
      limit,
      price_weight: withPrice ? null : 0,
    }),
    [mode, clientId, stage, industry, excluded, added, limit, withPrice],
  );
  const options = useMemo(() => [...clients, ...found], [clients, found]);
  const untouched = excluded.length === 0 && added.length === 0;
  const requestKey = `${JSON.stringify(body)}:${String(attempt)}`;
  const loading = settled !== requestKey;
  // Второй клиент для сравнения: его лента без правок «что если», с тем же пределом и учётом цены
  const compareWith = mode === 'history' && compareId !== clientId ? compareId : null;
  const compareKey = compareWith ? `${compareWith}:${String(limit)}:${String(withPrice)}` : null;
  const other = compared?.key === compareKey ? compared.feed : null;

  useEffect(() => {
    if (!compareWith || !compareKey) return undefined;
    const controller = new AbortController();
    const request: FeedRequest = {
      task: '',
      stage: null,
      experience: null,
      format_pref: null,
      industry: null,
      history: null,
      user_id: compareWith,
      exclude_history: [],
      add_history: [],
      limit,
      price_weight: withPrice ? null : 0,
    };
    requestFeed(request, controller.signal)
      .then((data) => {
        setCompared({ key: compareKey, feed: data });
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) setCompared({ key: compareKey, feed: null });
      });
    return () => {
      controller.abort();
    };
  }, [compareWith, compareKey, limit, withPrice]);

  useEffect(() => {
    const controller = new AbortController();
    requestFeed(body, controller.signal)
      .then((data) => {
        setResponse(data);
        setFailure(null);
        if (body.exclude_history.length === 0 && body.add_history.length === 0) setBaseHistory(data.history);
        setChange(before.current ? feedChange(before.current, data.items) : null);
        before.current = null;
        const was = previous.current;
        setShared(
          was
            ? {
                id: was.id,
                count: data.items.filter((item) => was.cards.has(item.material_id)).length,
                total: data.items.length,
              }
            : null,
        );
        previous.current = null;
        setSettled(requestKey);
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setFailure(error instanceof ApiError && !error.network ? error.message : NETWORK_ERROR_TEXT);
        setSettled(requestKey);
      });
    return () => {
      controller.abort();
    };
  }, [body, requestKey]);

  /** Правка «что если»: запомнить места, чтобы после ответа показать, что изменилось */
  const whatIf = (apply: () => void) => {
    before.current = new Map((response?.items ?? []).map((item) => [item.material_id, item.rank]));
    apply();
  };
  const resetWhatIf = () => {
    before.current = null;
    setChange(null);
    setExcluded([]);
    setAdded([]);
  };
  const onSelectClient = (id: string | null) => {
    const next = id ?? clients[0]?.id ?? null;
    // Сравнение идёт с лентой, которая сейчас на экране: её клиент назван в ответе, правок «что если» в ней нет
    const shown = response?.user?.id;
    if (response && shown && next !== shown && untouched) {
      // Сравниваются первые карточки обеих лент: после смены клиента лента снова открывается с первой порции
      const cards = response.items.slice(0, FIRST_PAGE).map((item) => item.material_id);
      previous.current = { id: shown, cards: new Set(cards) };
    }
    resetWhatIf();
    setLimit(FIRST_PAGE);
    setCodeError(null);
    setClientId(next);
  };
  /** Клиент по коду: сначала среди показанных, затем поиском в журнале */
  const onSubmitCode = (event: SyntheticEvent) => {
    event.preventDefault();
    if (searching) return; // Enter в поле отправляет форму и при недоступной кнопке
    const wanted = code.trim();
    if (!CODE_PATTERN.test(wanted)) {
      setCodeError(
        wanted
          ? 'В\u00A0коде допустимы латинские буквы, цифры, двоеточие, дефис и\u00A0подчёркивание'
          : 'Введите код клиента',
      );
      return;
    }
    const same = (user: User) => user.id.toLowerCase() === wanted.toLowerCase();
    const open = (user: User) => {
      onSelectClient(user.id);
      setCode('');
    };
    const known = options.find(same);
    if (known) {
      open(known);
      return;
    }
    setSearching(true);
    getUsers(wanted)
      .then((data) => {
        const user = data?.users.find(same);
        if (user) {
          setFound((list) => [...list, user]);
          open(user);
        } else {
          setCodeError(`Клиента с\u00A0кодом «${wanted}» нет в\u00A0журнале`);
        }
      })
      .catch(() => {
        setCodeError(NETWORK_ERROR_TEXT);
      })
      .finally(() => {
        setSearching(false);
      });
  };
  const onComplete = (item: FeedItem) => {
    whatIf(() => {
      // Сервис ставит добавленные события после истории: здесь нужен только порядок между ними
      setAdded([
        ...added,
        {
          material_id: item.material_id,
          event: 'complete',
          seq: added.length + 1,
        },
      ]);
    });
  };

  const items = response?.items ?? [];
  const first = items[0] ?? null;
  const last = items.length > 1 ? (items[items.length - 1] ?? null) : null;
  const addedIds = new Set(added.map((event) => event.material_id));
  const addedEntries = (response?.history ?? []).filter((entry) => addedIds.has(entry.material_id));

  const primary = (
    <Panel labelledBy={headingId}>
      <h1 id={headingId} ref={heading} className="h1 feed-title">
        {mode === 'history' ? 'Рекомендации по истории клиента' : 'Рекомендации для нового клиента'}
      </h1>
      {mode === 'history' ? (
        <>
          <SelectField
            id="feed-client"
            label="Клиент"
            value={clientId}
            onChange={onSelectClient}
            options={options.map((user) => ({
              value: user.id,
              label: user.label,
            }))}
            emptyLabel="Выберите клиента"
          />
          <form onSubmit={onSubmitCode} noValidate>
            <TextField
              id="feed-code"
              label="Код клиента"
              value={code}
              onChange={(value) => {
                setCode(value);
                setCodeError(null);
              }}
              error={codeError}
              autoComplete="off"
              spellCheck={false}
              maxLength={64}
              action={
                <Button type="submit" variant="secondary" aria-disabled={searching}>
                  Найти
                </Button>
              }
            />
          </form>
          <SelectField
            id="feed-compare"
            label={'Сравнить с\u00A0клиентом'}
            optional
            value={compareWith}
            onChange={setCompareId}
            options={options
              .filter((user) => user.id !== clientId)
              .map((user) => ({ value: user.id, label: user.label }))}
            emptyLabel="Не сравнивать"
          />
        </>
      ) : (
        <>
          <SelectField
            id="feed-stage"
            label="Стадия бизнеса"
            optional
            value={stage}
            onChange={(value) => {
              whatIf(() => {
                setStage(value);
              });
            }}
            options={(meta?.stages ?? []).map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            emptyLabel="Не указана"
          />
          <SelectField
            id="feed-industry"
            label="Сфера бизнеса"
            optional
            value={industry}
            onChange={(value) => {
              whatIf(() => {
                setIndustry(value);
              });
            }}
            options={(meta?.industries ?? []).map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            emptyLabel="Не указана"
          />
          <Button variant="link" onClick={onOpenTask}>
            Есть конкретная задача? Подобрать по задаче
          </Button>
        </>
      )}
    </Panel>
  );

  // История и состав оценки: на широком экране в боковой колонке, на узком после ленты
  const secondary = (
    <>
      {mode === 'history' || addedEntries.length > 0 ? (
        <Panel tone="subtle">
          <h2 className="kv__label">История клиента</h2>
          <ul className="feed-history">
            {mode === 'history'
              ? baseHistory.map((entry) => (
                  <li key={entry.material_id}>
                    <Checkbox
                      checked={!excluded.includes(entry.material_id)}
                      label={`${entry.title ?? entry.material_id} · ${entry.event_label.toLowerCase()}`}
                      onChange={(checked) => {
                        whatIf(() => {
                          setExcluded(
                            checked
                              ? excluded.filter((id) => id !== entry.material_id)
                              : [...excluded, entry.material_id],
                          );
                        });
                      }}
                    />
                  </li>
                ))
              : null}
            {addedEntries.map((entry) => (
              <li key={`added-${entry.material_id}`} className="feed-history__added">
                {entry.title ?? entry.material_id} · {entry.event_label.toLowerCase()}, добавлено для проверки
              </li>
            ))}
          </ul>
          {!untouched ? (
            <Button variant="link" onClick={resetWhatIf}>
              Вернуть исходную историю
            </Button>
          ) : null}
          {response?.facts.length ? (
            <dl className="feed-facts">
              {response.facts.map((fact) => (
                <div key={fact.name} className="feed-facts__row">
                  <dt>{fact.name}</dt>
                  <dd>{fact.value ? `${fact.value} (${fact.origin})` : fact.origin}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {response?.interests.length ? (
            <>
              <h3 className="feed-aside__subtitle">Темы истории</h3>
              <ul className="share-list">
                {response.interests.map((interest) => (
                  <li key={interest.label} className="share-list__row">
                    <span>{interest.label}</span>
                    <span className="share-list__value">{formatShare(interest.share)}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </Panel>
      ) : null}

      <Panel tone="subtle">
        <h2 className="kv__label">Из чего складывается оценка</h2>
        <ul className="feed-legend">
          {FAMILY_ORDER.map((family) => (
            <li key={family} className="feed-legend__row">
              <span className={`swatch swatch--${family}`} aria-hidden="true" />
              <span>{FAMILY_LABEL[family]}</span>
            </li>
          ))}
        </ul>
        {response?.sources.length ? (
          <>
            <h3 className="feed-aside__subtitle">Доли источников в&nbsp;оценках этих карточек</h3>
            <ul className="share-list">
              {response.sources.map((source) => (
                <li key={source.source} className="share-list__row">
                  <span>{typo(source.label)}</span>
                  <span className="share-list__value">{formatShare(source.share)}</span>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        <Checkbox
          checked={withPrice}
          label={'Учитывать доступ и\u00A0цену'}
          onChange={(checked) => {
            whatIf(() => {
              setWithPrice(checked);
            });
          }}
        />
        <ModelPassport />
      </Panel>
    </>
  );

  const content = (
    <>
      {failure ? (
        <Banner
          tone="error"
          title="Лента не загрузилась"
          actions={
            <Button
              variant="secondary"
              onClick={() => {
                setAttempt((value) => value + 1);
              }}
            >
              Повторить
            </Button>
          }
        >
          {failure}
        </Banner>
      ) : null}
      <StatusLine>{loading ? LOADING_TEXT : (response?.message ?? '')}</StatusLine>
      {change && !loading ? (
        <Banner tone="info" title="Лента пересчитана">
          {changeSentence(change)}
        </Banner>
      ) : null}
      {shared && !loading ? (
        <Banner tone="info" title="Другой клиент">
          {typo(
            `Общих карточек с\u00A0лентой клиента ${shared.id}: ${String(shared.count)} из ${String(shared.total)}.`,
          )}
        </Banner>
      ) : null}
      {other && response && !loading ? <ClientCompare own={response} other={other} /> : null}
      {first && last ? <CompareTable captionHidden caption="Первая и&nbsp;последняя карточки ленты" a={first} b={last} /> : null}
      {items.length > 0 ? <h2 className="visually-hidden">Материалы ленты</h2> : null}
      <div className={cx('feed-list', loading && 'feed-list--stale')} aria-busy={loading}>
        {items.map((item) => (
          <FeedCard
            key={item.material_id}
            item={item}
            topScore={first?.score ?? 0}
            reference={item === first ? last : first}
            shift={change?.shift.get(item.material_id)}
            onComplete={onComplete}
            disabled={loading}
          />
        ))}
      </div>
      {response && limit < FULL_FEED && response.total_candidates > items.length ? (
        <Button
          variant="secondary"
          aria-disabled={loading}
          onClick={() => {
            if (!loading) setLimit(FULL_FEED);
          }}
        >
          {typo(`Показать первые ${String(Math.min(FULL_FEED, response.total_candidates))}`)}
        </Button>
      ) : null}
    </>
  );

  if (audience === 'client') {
    // Вид клиента: то, что увидел бы он сам. Оценки, расчёт, сравнения и панели остаются в виде для продукта
    return (
      <Layout
        className="feed feed--client"
        aside={null}
        content={
          <>
            <h1 ref={heading} className="h1 feed-title">
              Рекомендации для вас
            </h1>
            {failure ? (
              <Banner tone="error" title="Лента не загрузилась">
                {failure}
              </Banner>
            ) : null}
            <StatusLine>{loading ? LOADING_TEXT : ''}</StatusLine>
            {items.length > 0 ? <h2 className="visually-hidden">Материалы ленты</h2> : null}
            <div className={cx('feed-list', loading && 'feed-list--stale')} aria-busy={loading}>
              {items.map((item) => (
                <FeedCard
                  key={item.material_id}
                  item={item}
                  topScore={0}
                  reference={null}
                  onComplete={onComplete}
                  disabled
                  plain
                />
              ))}
            </div>
          </>
        }
      />
    );
  }

  return (
    <Layout
      className="feed"
      aside={
        <>
          {primary}
          {wide ? secondary : null}
        </>
      }
      content={
        <>
          {content}
          {wide ? null : <div className="feed-secondary">{secondary}</div>}
        </>
      }
    />
  );
}
