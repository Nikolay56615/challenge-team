import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Item, Option, RecommendResponse, TopicCode } from '../api/types';
import { Button, Layout } from '../kit';
import { MAX_LIMIT, type RecommendationResult } from '../state/useRecommend';
import { useDelayedFlag } from '../state/useDelayedFlag';
import { CompareView, compareStatus, type CompareTab } from './CompareView';
import { EmptyState, STARTER_VISIBLE, starterTotal } from './EmptyState';
import { mergeFilterOptions, ResultFilters } from './ResultFilters';
import { LOADING_STATUS, REFRESHING_STATUS, ResultList } from './ResultList';
import { NETWORK_ERROR_TEXT, StateBanner } from './StateBanner';

type FocusGoal = 'state' | 'card' | 'submit' | 'heading';

interface RecommendationPaneProps {
  active: boolean;
  catalog?: boolean;
  result: Pick<RecommendationResult, 'state' | 'actions'>;
  topics: readonly Option<TopicCode>[];
  topic?: TopicCode | null;
  chooseTopic?(value: TopicCode): void;
  intro?: ReactNode;
  aside(submit: (action: () => void) => void, resetView: () => void): ReactNode;
}

export function RecommendationPane({
  active, catalog = false, result, topics, topic = null, chooseTopic, intro, aside,
}: RecommendationPaneProps) {
  const { state, actions } = result;
  // Представление выдачи переживает повтор того же запроса и сбрасывается новым запросом
  const [compareTab, setCompareTab] = useState<CompareTab>('personal');
  const [starterExpanded, setStarterExpanded] = useState(false);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);

  const statusRef = useRef<HTMLParagraphElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  const focusGoal = useRef<FocusGoal | null>(null);

  const resetView = () => {
    setCompareTab('personal');
    setStarterExpanded(false);
    setFocusIndex(null);
    focusGoal.current = null;
  };

  // Действие в области выдачи не уводит фокус: прежние карточки остаются на экране, нажатый элемент
  // чаще всего тоже. Если он всё же исчез, эффект ниже переведёт фокус к элементу нового состояния.
  const fromContent =
    <A extends unknown[]>(action: (...args: A) => void, goal: FocusGoal = 'state') =>
    (...args: A) => {
      focusGoal.current = goal;
      action(...args);
    };
  const onComplete = fromContent((item: Item) => actions.markComplete(item.material_id));
  const onChooseTopic = chooseTopic ? fromContent(chooseTopic) : undefined;
  const onRetry = fromContent(actions.retry);
  // Фильтры переносят фокус на заголовок со счётчиком: новая выдача объявляется сразу,
  // но страница не прокручивается — пользователь остаётся у панели фильтров.
  const onApplyFilters = fromContent(actions.applyFilters, 'heading');
  const shown = state.outcome?.kind === 'recommend' ? state.outcome.response : null;

  /** «Показать ещё»: фокус на первую новую карточку */
  const onMore = () => {
    setFocusIndex(shown?.items.length ?? null);
    fromContent(actions.showMore, 'card')();
  };

  /** «Показать все N»: раскрыть подборку; если сервер прислал меньше N, запросить до 10 */
  const onExpandStarter = () => {
    if (!shown || state.loading) return;
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

  /** «Оставить как есть»: баннер исчезает, строка состояния выдачи видна */
  const onDismiss = () => {
    statusRef.current?.focus();
    actions.hideClarification();
  };

  const submit = (action: () => void) => {
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
  // Повторное действие (тема, фильтры, «Показать ещё», «Отметить изученным», «Повторить»): прежняя
  // выдача остаётся на экране, пока не придёт новая, — иначе список исчезает на каждый запрос.
  const refreshing = state.loading && !state.newQuery && outcome !== null;
  // Новый запрос из формы: прежняя выдача к нему не относится, показывать её нельзя
  const pending = state.loading && !refreshing;
  // Скелетон появляется, только если запрос идёт дольше 200 мс: быстрый ответ не мигает
  const skeletonVisible = useDelayedFlag(pending);
  const filterOptions = outcome?.kind === 'compare'
    ? mergeFilterOptions(outcome.response.baseline.filter_options, outcome.response.personal.filter_options)
    : shown?.filter_options;
  // Фильтры остаются на месте, пока идёт повторный запрос или пока не показан скелетон
  const filters = filterOptions && !skeletonVisible && !failure ? (
    <ResultFilters options={filterOptions} applied={state.resultCall?.body.filters} onApply={onApplyFilters} />
  ) : null;
  const resultTopic = state.resultCall?.body.topic;
  const resultItems = outcome?.kind === 'compare' ? outcome.response.personal.items : outcome?.response.items;
  const topicItem = resultTopic ? resultItems?.find((item) => item.topics.includes(resultTopic)) : undefined;
  const topicLabel = topics.find((topic) => topic.value === resultTopic)?.label
    ?? (resultTopic && topicItem ? topicItem.topic_labels[topicItem.topics.indexOf(resultTopic)] : undefined);
  if (pending && skeletonVisible) {
    // Запрос идёт дольше 200 мс: прежнее содержимое уступает место скелетону
    status = LOADING_STATUS;
    statusHidden = false;
  } else if (failure) {
    banner = (
      <StateBanner
        kind="error"
        message={failure.network ? NETWORK_ERROR_TEXT : failure.message}
        onRetry={onRetry}
        retryRef={retryRef}
      />
    );
  } else if (!outcome) {
    view = intro;
  } else if (outcome.kind === 'compare') {
    // Позиции названы, только если оба метода вернули выдачу по запросу; иначе — какой метод ничего не нашёл
    status = refreshing ? REFRESHING_STATUS : compareStatus(outcome.response);
    view = (
      <CompareView
        response={outcome.response}
        topicLabel={topicLabel}
        filters={filters}
        onComplete={onComplete}
        tab={compareTab}
        onTabChange={setCompareTab}
        headingRef={headingRef}
        busy={refreshing}
      />
    );
  } else {
    const response = outcome.response;
    // Сводка «Нашли N материалов…» остаётся только для вспомогательных технологий:
    // на экране её заменяют сами карточки.
    status = refreshing ? REFRESHING_STATUS : response.message;
    if (response.status === 'strong' || response.status === 'weak') {
      listResponse = response;
      if (onChooseTopic && response.status === 'weak' && response.clarification && !state.clarificationHidden) {
        banner = (
          <StateBanner
            kind="clarification"
            clarification={response.clarification}
            topic={topic}
            onChooseTopic={onChooseTopic}
            onDismiss={onDismiss}
            disabled={refreshing}
          />
        );
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
          busy={refreshing}
        />
      );
    }
  }

  // Первые 200 мс запрос идёт без скелетона: прежнее содержимое остаётся на экране,
  // а строка состояния скрыто объявляет загрузку. Быстрый ответ меняет содержимое сразу.
  if (pending && !skeletonVisible) {
    status = LOADING_STATUS;
    statusHidden = true;
  }

  // Ответ на действие из области выдачи пришёл: если нажатый элемент исчез, фокус переходит
  // к видимому элементу — «Повторить», нужной карточке, заголовку представления или к строке состояния.
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
    // Пока шёл запрос, пользователь сам перевёл фокус: не перехватываем. Отправка формы и фильтры —
    // исключение: фокус остаётся на кнопке, хотя результат показан в другой колонке или ниже.
    if (goal === 'state' || goal === 'card') {
      if (focused && focused !== document.body && focused !== statusRef.current) return;
    }
    let target: HTMLElement | null;
    if (failure) target = retryRef.current;
    else if (goal === 'card' && cardRef.current) target = cardRef.current;
    else if (goal === 'heading' || statusHidden) target = headingRef.current;
    else target = statusRef.current;
    // Отправка формы: на узком экране выдача ниже формы, её нужно довести в поле зрения.
    // В остальных случаях страницу не прокручиваем: пользователь остаётся там, где читал.
    target?.focus({ preventScroll: goal !== 'submit' });
  });
  if (!active) return null;
  const moreInComparison = catalog && !skeletonVisible && outcome?.kind === 'compare'
    ? Math.max(0, ...[outcome.response.baseline, outcome.response.personal].map((response) =>
      response.filter_options ? Math.min(MAX_LIMIT, response.total_candidates) - response.items.length : 0))
    : 0;

  return (
    <Layout
      as="div"
      aside={aside(submit, resetView)}
      content={
        <>
          {banner}
          <ResultList
            status={status}
            statusHidden={statusHidden}
            statusRef={statusRef}
            loading={state.loading}
            skeletonVisible={skeletonVisible}
            busy={refreshing}
            response={listResponse}
            topicLabel={topicLabel}
            limitHint={catalog ? 'Используйте фильтры, чтобы сузить список.' : undefined}
            filters={listResponse ? filters : null}
            onComplete={onComplete}
            onMore={onMore}
            focusIndex={focusIndex}
            cardRef={cardRef}
            headingRef={headingRef}
          />
          {view}
          {moreInComparison > 0 ? (
            <Button aria-disabled={state.loading || undefined} onClick={() => {
              if (!state.loading) onMore();
            }}>
              Показать ещё {moreInComparison}
            </Button>
          ) : null}
        </>
      }
    />
  );
}
