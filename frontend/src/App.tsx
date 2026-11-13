import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Clarification, Item, Option, RecommendResponse, TopicCode } from './api/types';
import { CatalogTopics } from './components/CatalogTopics';
import { mergeFilterOptions, ResultFilters } from './components/ResultFilters';
import { CompareView, compareStatus, type CompareTab } from './components/CompareView';
import { DemoPanel } from './components/DemoPanel';
import { EmptyState, STARTER_VISIBLE, starterTotal } from './components/EmptyState';
import { IntroPanel } from './components/IntroPanel';
import { LOADING_STATUS, ResultList } from './components/ResultList';
import { NETWORK_ERROR_TEXT, StateBanner } from './components/StateBanner';
import { TaskForm } from './components/TaskForm';
import { Button, Layout, Screen, SKELETON_DELAY_MS, Stale, TopBar, useDelayedFlag } from './kit';
import { DEFAULT_MAX_TASK_LENGTH, useMeta } from './state/useMeta';
import { MAX_LIMIT, useRecommend, type RecommendationResult, type Section } from './state/useRecommend';

/** Куда перевести фокус после ответа: элемент нового состояния, карточку focusIndex или выдачу после отправки формы */
type FocusGoal = 'state' | 'card' | 'submit';

/** Отступ от верхнего края окна при прокрутке к баннеру или карточке, px */
const SCROLL_MARGIN = 12;
/** Сколько карточки должно быть видно под баннером: рамка, номер позиции и начало названия, px */
const CARD_PEEK = 48;

/**
 * Фокус на первую карточку под баннером уточнения (docs/ui-kit.md, 4.1; ИИ-10). Сам focus() поставил бы
 * карточку в середину окна, и на 390 px вопрос баннера ушёл бы за верхний край. Окно показывает начало
 * баннера и начало карточки; если вместе они не помещаются, как в окне 320×256 при увеличении 400 %,
 * в окне остаётся карточка с фокусом.
 */
function focusBelowBanner(card: HTMLElement, banner: HTMLElement) {
  card.focus({ preventScroll: true });
  const bannerTop = banner.getBoundingClientRect().top;
  const cardTop = card.getBoundingClientRect().top;
  if (bannerTop >= 0 && cardTop + CARD_PEEK <= window.innerHeight) return;
  const fits = cardTop - bannerTop + CARD_PEEK + SCROLL_MARGIN <= window.innerHeight;
  window.scrollBy(0, (fits ? bannerTop : cardTop) - SCROLL_MARGIN);
}

type PaneResult = Pick<RecommendationResult, 'state' | 'actions'>;
type Submit = (action: () => void) => void;

function RecommendationPane({ active, result, topics, topic = null, chooseTopic, catalog = false, aside }: {
  active: boolean;
  result: PaneResult;
  topics: readonly Option<TopicCode>[];
  topic?: TopicCode | null;
  chooseTopic?: (value: TopicCode) => void;
  catalog?: boolean;
  aside: (submit: Submit, resetView: () => void, slow: boolean, submitRef: React.Ref<HTMLButtonElement>) => ReactNode;
}) {
  const { state, actions } = result;

  // Представление выдачи переживает повтор того же запроса и сбрасывается новым запросом
  const [compareTab, setCompareTab] = useState<CompareTab>('personal');
  const [starterExpanded, setStarterExpanded] = useState(false);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);

  const statusRef = useRef<HTMLParagraphElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const submitRef = useRef<HTMLButtonElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  // Первая карточка выдачи strong или weak: видимая цель фокуса после ответа (docs/ui-kit.md, 4.1; ИИ-10)
  const firstCardRef = useRef<HTMLElement>(null);
  const bannerRef = useRef<HTMLDivElement>(null);
  const focusGoal = useRef<FocusGoal | null>(null);

  const resetView = () => {
    setCompareTab('personal');
    setStarterExpanded(false);
    setFocusIndex(null);
    focusGoal.current = null;
  };

  // Действие в области выдачи убирает или блокирует нажатый элемент. Пока идёт запрос, фокус ждёт
  // на видимой строке состояния; после ответа эффект ниже переводит его к элементу нового состояния.
  const fromContent =
    <A extends unknown[]>(action: (...args: A) => void, goal: FocusGoal = 'state') =>
    (...args: A) => {
      focusGoal.current = goal;
      statusRef.current?.focus();
      action(...args);
    };
  const onComplete = fromContent((item: Item) => {
    actions.markComplete(item.material_id);
  });
  const onChooseTopic = fromContent((topic: TopicCode) => {
    chooseTopic?.(topic);
  });
  const onRetry = fromContent(actions.retry);
  const shown = state.outcome?.kind === 'recommend' ? state.outcome.response : null;

  /** «Показать ещё»: фокус на первую новую карточку */
  const onMore = () => {
    setFocusIndex(shown?.items.length ?? null);
    fromContent(actions.showMore, 'card')();
  };

  /** «Показать все N»: раскрыть подборку; если сервер прислал меньше N, запросить до 10 */
  const onExpandStarter = () => {
    if (!shown) return;
    const visible = starterExpanded ? shown.items.length : Math.min(STARTER_VISIBLE, shown.items.length);
    setFocusIndex(visible);
    setStarterExpanded(true);
    if (starterTotal(shown) > shown.items.length) {
      fromContent(actions.showMore, 'card')();
    } else {
      // Кнопка исчезает после раскрытия: фокус перейдёт на первую раскрытую карточку
      focusGoal.current = 'card';
    }
  };

  /** «Оставить как есть»: баннер исчезает, фокус — на первую карточку выдачи, а не на скрытую строку состояния */
  const onDismiss = () => {
    (firstCardRef.current ?? statusRef.current)?.focus();
    actions.hideClarification();
  };

  const submit: Submit = (action) => {
    resetView();
    focusGoal.current = 'submit';
    action();
  };

  // Правая колонка: баннер, строка состояния с выдачей, другое представление
  let banner: ReactNode = null;
  let status = '';
  let statusHidden = true;
  let listResponse: RecommendResponse | null = null;
  let view: ReactNode = null;

  const { outcome, failure } = state;
  const options = outcome?.kind === 'compare'
    ? mergeFilterOptions(outcome.response.baseline.filter_options, outcome.response.personal.filter_options)
    : shown?.filter_options;
  const filters = options && !failure ? (
    <ResultFilters key={JSON.stringify(state.resultCall?.body.filters ?? null)} options={options} applied={state.resultCall?.body.filters} onApply={fromContent(actions.applyFilters)} />
  ) : null;
  const resultTopic = state.resultCall?.body.topic;
  const topicLabel = topics.find((entry) => entry.value === resultTopic)?.label;
  // Опыт из запроса, по которому получена выдача: пометка «уровень» только при точном совпадении (src/match.ts)
  const experience = state.resultCall?.body.experience ?? null;
  // D10: строка состояния говорит о загрузке сразу. Скелетоны появляются, только если ответ дольше
  // SKELETON_DELAY_MS; до этого прежнее содержимое остаётся на месте, неактивное (Stale), и колонка не схлопывается
  const slow = useDelayedFlag(state.loading, SKELETON_DELAY_MS);
  const holding = state.loading && !slow;

  const clarificationBanner = (clarification: Clarification) => (
    <StateBanner
      kind="clarification"
      clarification={clarification}
      topic={topic}
      onChooseTopic={onChooseTopic}
      onDismiss={onDismiss}
      disabled={state.loading}
      bannerRef={bannerRef}
    />
  );

  if (slow) {
    // Повтор того же запроса (тема, «Показать ещё», «Отметить изученным»): уточнение прежнего ответа
    // остаётся заблокированным до нового ответа, выбранная тема видна. Новый запрос из формы его убирает.
    const previous = outcome?.kind === 'recommend' && !state.newQuery ? outcome.response : null;
    if (chooseTopic && previous?.status === 'weak' && previous.clarification && !state.clarificationHidden) {
      banner = clarificationBanner(previous.clarification);
    }
  } else if (failure) {
    // Во время загрузки «Повторить» уже нажата: баннер ошибки остаётся неактивным до ответа или скелетонов,
    // о загрузке говорит строка состояния
    banner = (
      <Stale active={holding}>
        <StateBanner
          kind="error"
          message={failure.network ? NETWORK_ERROR_TEXT : failure.message}
          onRetry={onRetry}
          retryRef={retryRef}
        />
      </Stale>
    );
  } else if (!outcome) {
    view = catalog ? null : <IntroPanel />;
  } else if (outcome.kind === 'compare') {
    // Позиции названы, только если оба метода вернули выдачу по запросу; иначе — какой метод ничего не нашёл
    status = compareStatus(outcome.response);
    view = (
      <CompareView
        response={outcome.response}
        filters={filters}
        topicLabel={topicLabel}
        onComplete={onComplete}
        tab={compareTab}
        onTabChange={setCompareTab}
        headingRef={headingRef}
        experience={experience}
      />
    );
  } else {
    const response = outcome.response;
    // Сводка «Нашли N материалов…» остаётся только для вспомогательных технологий:
    // на экране её заменяют сами карточки.
    status = response.message;
    if (response.status === 'strong' || response.status === 'weak') {
      listResponse = response;
      if (chooseTopic && response.status === 'weak' && response.clarification && !state.clarificationHidden) {
        banner = clarificationBanner(response.clarification);
      }
    } else {
      // none, cold, empty: заголовок пустой выдачи виден, строка состояния — для вспомогательных технологий
      view = catalog ? (
        <h2 ref={headingRef} className="h2" tabIndex={-1}>{response.message}</h2>
      ) : (
        <EmptyState
          response={response}
          topic={topic}
          onChooseTopic={onChooseTopic}
          onComplete={onComplete}
          expanded={starterExpanded}
          onExpand={onExpandStarter}
          headingRef={headingRef}
          focusIndex={focusIndex}
          cardRef={cardRef}
          experience={experience}
        />
      );
    }
  }
  if (state.loading) {
    status = LOADING_STATUS;
    statusHidden = false;
  }

  // Ответ на действие из области выдачи пришёл: фокус с ждущей строки состояния переходит к видимому
  // элементу — «Повторить», нужной карточке, первой карточке выдачи или заголовку представления.
  // Скрытая строка состояния и скрытый заголовок «Подборка» целью не бывают: кольцо фокуса на них не видно
  // (docs/ui-kit.md, 1 и 4.1; evaluation/track1-heuristic-review.md, ИИ-10).
  useEffect(() => {
    const goal = focusGoal.current;
    if (!active) {
      focusGoal.current = null;
      return;
    }
    if (!goal || state.loading) return;
    focusGoal.current = null;
    // Ошибка поля: фокус уже переведён на поле задачи в TaskForm
    if (state.fieldError) return;
    const focused = document.activeElement;
    // После отправки переводим фокус с кнопки к выдаче. Если пользователь уже перешёл в другое поле,
    // оставляем фокус там.
    if (focused && focused !== document.body && focused !== statusRef.current &&
      (goal !== 'submit' || focused !== submitRef.current)) return;
    let target: HTMLElement | null;
    if (failure) target = retryRef.current;
    else if (goal === 'card' && cardRef.current) target = cardRef.current;
    else if (firstCardRef.current) target = firstCardRef.current;
    else if (statusHidden) target = headingRef.current;
    else target = statusRef.current;
    if (target && target === firstCardRef.current && bannerRef.current) focusBelowBanner(target, bannerRef.current);
    else target?.focus();
  });

  if (!active) return null;

  const moreInComparison = !state.loading && outcome?.kind === 'compare'
    ? Math.max(0, ...[outcome.response.baseline, outcome.response.personal].map((response) =>
      response.filter_options ? Math.min(MAX_LIMIT, response.total_candidates) - response.items.length : 0))
    : 0;

  // The renderer only forwards the ref to the form button. State is changed by its event handlers.
  // eslint-disable-next-line react-hooks/refs
  const paneAside = aside(submit, resetView, slow, submitRef);

  return (
      <Layout aside={paneAside}
        content={
          <>
            {banner}
            <ResultList
              status={status}
              statusHidden={statusHidden}
              statusRef={statusRef}
              loading={slow}
              stale={holding}
              response={listResponse}
              topicLabel={topicLabel}
              headingRef={headingRef}
              filters={listResponse ? filters : null}
              onComplete={onComplete}
              onMore={onMore}
              focusIndex={focusIndex}
              cardRef={cardRef}
              firstCardRef={firstCardRef}
              experience={experience}
            />
            <Stale active={holding}>{view}</Stale>
            {moreInComparison > 0 ? <Button onClick={onMore}>Показать ещё {moreInComparison}</Button> : null}
          </>
        }
      />
  );
}

function currentSection(): Section {
  return window.location.hash === '#catalog' ? 'catalog' : 'recommend';
}

export function App() {
  const [section, setSection] = useState(currentSection);
  const [catalogTopic, setCatalogTopic] = useState<TopicCode | null>(null);
  const { meta, profiles, failed, reload } = useMeta();
  const session = useRecommend(section);
  const { recommendation, catalog } = session;
  const topics = meta?.topics ?? [];
  const sectionHeading = useRef<HTMLHeadingElement>(null);
  const previousSection = useRef(section);

  useEffect(() => {
    const update = () => { setSection(currentSection()); };
    window.addEventListener('hashchange', update);
    return () => { window.removeEventListener('hashchange', update); };
  }, []);

  useEffect(() => {
    if (previousSection.current !== section) {
      sectionHeading.current?.focus();
      previousSection.current = section;
    }
  }, [section]);

  return (
    <Screen>
      <TopBar brand="Учебная платформа" navigation={
        <nav className="topbar__nav" aria-label="Разделы">
          <a href="#recommend" aria-current={section === 'recommend' ? 'page' : undefined}>Подбор</a>
          <a href="#catalog" aria-current={section === 'catalog' ? 'page' : undefined}>Каталог</a>
        </nav>
      } />
        <RecommendationPane
          active={section === 'recommend'}
          result={recommendation}
          topics={topics}
          topic={session.topic}
          chooseTopic={recommendation.chooseTopic}
          aside={(submit, resetView, slow, submitRef) => (
            <>
              <TaskForm
                headingRef={sectionHeading}
                meta={meta}
                metaFailed={failed}
                values={session.form}
                maxLength={meta?.max_task_length ?? DEFAULT_MAX_TASK_LENGTH}
                error={recommendation.state.fieldError}
                loading={recommendation.state.loading}
                busy={slow}
                submitRef={submitRef}
                onTaskChange={session.setTask}
                onRefinementsChange={session.setRefinements}
                onSubmit={() => {
                  if (failed) reload();
                  submit(recommendation.submit);
                }}
                onReset={() => {
                  resetView();
                  setCatalogTopic(null);
                  session.reset();
                }}
              />
              {profiles ? (
                <DemoPanel
                  profiles={profiles}
                  profileId={session.profileId}
                  onSelectProfile={(id) => {
                    resetView();
                    setCatalogTopic(null);
                    session.selectProfile(profiles.find((profile) => profile.id === id) ?? null);
                  }}
                  compare={session.compare}
                  onCompareChange={session.setCompare}
                  disabled={recommendation.state.loading}
                />
              ) : null}
            </>
          )}
        />
        <RecommendationPane
          active={section === 'catalog'}
          result={catalog}
          topics={topics}
          catalog
          aside={(submit) => (
            <CatalogTopics
              headingRef={sectionHeading}
              topics={topics}
              loaded={meta !== null}
              failed={failed}
              reload={reload}
              value={catalogTopic}
              current={catalog.state.lastCall?.body.topic ?? null}
              onChange={setCatalogTopic}
              onShow={(topic) => {
                setCatalogTopic(topic);
                submit(() => { catalog.browseTopic(topic); });
              }}
              disabled={catalog.state.loading}
            />
          )}
        />
    </Screen>
  );
}
