import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Item, Option, RecommendResponse, TopicCode } from '../api/types';
import { Button, Layout } from '../kit';
import { MAX_LIMIT, type RecommendationResult } from '../state/useRecommend';
import { CompareView, compareStatus, type CompareTab } from './CompareView';
import { EmptyState, STARTER_VISIBLE, starterTotal } from './EmptyState';
import { mergeFilterOptions, ResultFilters } from './ResultFilters';
import { LOADING_STATUS, ResultList } from './ResultList';
import { NETWORK_ERROR_TEXT, StateBanner } from './StateBanner';

type FocusGoal = 'state' | 'card' | 'submit';

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

  // Действие в области выдачи убирает или блокирует нажатый элемент. Пока идёт запрос, фокус ждёт
  // на видимой строке состояния; после ответа эффект ниже переводит его к элементу нового состояния.
  const fromContent =
    <A extends unknown[]>(action: (...args: A) => void, goal: FocusGoal = 'state') =>
    (...args: A) => {
      focusGoal.current = goal;
      statusRef.current?.focus();
      action(...args);
    };
  const onComplete = fromContent((item: Item) => actions.markComplete(item.material_id));
  const onChooseTopic = chooseTopic ? fromContent(chooseTopic) : undefined;
  const onRetry = fromContent(actions.retry);
  const onApplyFilters = fromContent(actions.applyFilters);
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
  const filterOptions = outcome?.kind === 'compare'
    ? mergeFilterOptions(outcome.response.baseline.filter_options, outcome.response.personal.filter_options)
    : shown?.filter_options;
  const filters = filterOptions && !state.loading && !failure ? (
    <ResultFilters options={filterOptions} applied={state.resultCall?.body.filters} onApply={onApplyFilters} />
  ) : null;
  const resultTopic = state.resultCall?.body.topic;
  const resultItems = outcome?.kind === 'compare' ? outcome.response.personal.items : outcome?.response.items;
  const topicItem = resultTopic ? resultItems?.find((item) => item.topics.includes(resultTopic)) : undefined;
  const topicLabel = topics.find((topic) => topic.value === resultTopic)?.label
    ?? (resultTopic && topicItem ? topicItem.topic_labels[topicItem.topics.indexOf(resultTopic)] : undefined);
  if (state.loading) {
    status = LOADING_STATUS;
    statusHidden = false;
    // Повтор того же запроса (тема, «Показать ещё», «Отметить изученным»): уточнение прежнего ответа
    // остаётся заблокированным до нового ответа, выбранная тема видна. Новый запрос из формы его убирает.
    const previous = outcome?.kind === 'recommend' && !state.newQuery ? outcome.response : null;
    if (onChooseTopic && previous?.status === 'weak' && previous.clarification && !state.clarificationHidden) {
      banner = (
        <StateBanner
          kind="clarification"
          clarification={previous.clarification}
          topic={topic}
          onChooseTopic={onChooseTopic}
          onDismiss={onDismiss}
          disabled
        />
      );
    }
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
    status = compareStatus(outcome.response);
    view = (
      <CompareView
        response={outcome.response}
        topicLabel={topicLabel}
        filters={filters}
        onComplete={onComplete}
        tab={compareTab}
        onTabChange={setCompareTab}
        headingRef={headingRef}
      />
    );
  } else {
    const response = outcome.response;
    // Сводка «Нашли N материалов…» остаётся только для вспомогательных технологий:
    // на экране её заменяют сами карточки.
    status = response.message;
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
        />
      );
    }
  }

  // Ответ на действие из области выдачи пришёл: фокус с ждущей или скрытой строки состояния переходит
  // к видимому элементу — «Повторить», нужной карточке, заголовку представления или к самой строке.
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
    // Пока шёл запрос, пользователь сам перевёл фокус: не перехватываем. Отправка формы — исключение:
    // фокус остаётся на кнопке, хотя ответ уже показан в другой колонке или ниже по странице.
    if (goal !== 'submit' && focused && focused !== document.body && focused !== statusRef.current) return;
    let target: HTMLElement | null;
    if (failure) target = retryRef.current;
    else if (goal === 'card' && cardRef.current) target = cardRef.current;
    else if (statusHidden) target = headingRef.current;
    else target = statusRef.current;
    target?.focus();
  });
  if (!active) return null;
  const moreInComparison = catalog && !state.loading && outcome?.kind === 'compare'
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
          {moreInComparison > 0 ? <Button onClick={onMore}>Показать ещё {moreInComparison}</Button> : null}
        </>
      }
    />
  );
}
