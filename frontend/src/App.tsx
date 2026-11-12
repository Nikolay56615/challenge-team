import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { Item, RecommendResponse, TopicCode } from './api/types';
import { CompareView, compareStatus, type CompareTab } from './components/CompareView';
import { DemoPanel } from './components/DemoPanel';
import { EmptyState, STARTER_VISIBLE, starterTotal } from './components/EmptyState';
import { IntroPanel } from './components/IntroPanel';
import { mergeFilterOptions, ResultFilters } from './components/ResultFilters';
import { LOADING_STATUS, ResultList } from './components/ResultList';
import { NETWORK_ERROR_TEXT, StateBanner } from './components/StateBanner';
import { TaskForm } from './components/TaskForm';
import { TopicPicker } from './components/TopicPicker';
import { Layout, Panel, Screen, TopBar } from './kit';
import { DEFAULT_MAX_TASK_LENGTH, useMeta } from './state/useMeta';
import { useRecommend } from './state/useRecommend';

/** Куда перевести фокус после ответа: элемент нового состояния, карточку focusIndex или выдачу после отправки формы */
type FocusGoal = 'state' | 'card' | 'submit';

export function App() {
  const metaState = useMeta();
  const { meta, profiles } = metaState;
  const { state, actions } = useRecommend();
  const maxLength = meta?.max_task_length ?? DEFAULT_MAX_TASK_LENGTH;
  const topics = meta?.topics ?? [];
  const [catalogTopic, setCatalogTopic] = useState<TopicCode | null>(null);

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
  const onChooseTopic = fromContent((topic: TopicCode) => actions.chooseTopic(topic));
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

  const submitFromForm = (action: () => void) => {
    if (metaState.failed) metaState.reload();
    resetView();
    // На узком экране выдача ниже формы: после ответа ведём фокус к её заголовку
    focusGoal.current = 'submit';
    action();
  };
  const onReset = () => {
    resetView();
    setCatalogTopic(null);
    actions.reset();
  };
  const onSelectProfile = (id: string | null) => {
    resetView();
    setCatalogTopic(null);
    actions.selectProfile(profiles?.find((profile) => profile.id === id) ?? null);
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
    if (previous?.status === 'weak' && previous.clarification && !state.clarificationHidden) {
      banner = (
        <StateBanner
          kind="clarification"
          clarification={previous.clarification}
          topic={state.topic}
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
    view = <IntroPanel />;
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
      if (response.status === 'weak' && response.clarification && !state.clarificationHidden) {
        banner = (
          <StateBanner
            kind="clarification"
            clarification={response.clarification}
            topic={state.topic}
            onChooseTopic={onChooseTopic}
            onDismiss={onDismiss}
          />
        );
      }
    } else {
      // none, cold, empty: заголовок пустой выдачи виден, строка состояния — для вспомогательных технологий
      view = (
        <EmptyState
          response={response}
          topic={state.topic}
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
    if (!goal || state.loading) return;
    focusGoal.current = null;
    // Ошибка поля: фокус уже переведён на поле задачи в TaskForm
    if (state.fieldError) return;
    const active = document.activeElement;
    // Пока шёл запрос, пользователь сам перевёл фокус: не перехватываем. Отправка формы — исключение:
    // фокус остаётся на кнопке, хотя ответ уже показан в другой колонке или ниже по странице.
    if (goal !== 'submit' && active && active !== document.body && active !== statusRef.current) return;
    let target: HTMLElement | null;
    if (failure) target = retryRef.current;
    else if (goal === 'card' && cardRef.current) target = cardRef.current;
    else if (statusHidden) target = headingRef.current;
    else target = statusRef.current;
    target?.focus();
  });

  return (
    <Screen>
      <TopBar brand="Учебная платформа" />
      <Layout
        aside={
          <>
            <TaskForm
              meta={meta}
              metaFailed={metaState.failed}
              values={state.form}
              maxLength={maxLength}
              error={state.fieldError}
              loading={state.loading}
              onTaskChange={actions.setTask}
              onRefinementsChange={actions.setRefinements}
              onSubmit={() => submitFromForm(actions.submit)}
              onReset={onReset}
            />
            {topics.length > 0 ? (
              <Panel as="div" tone="subtle">
                <TopicPicker
                  label="Тема каталога"
                  options={topics}
                  value={catalogTopic}
                  onChange={setCatalogTopic}
                  onShow={(topic) => submitFromForm(() => actions.browseTopic(topic))}
                  disabled={state.loading}
                />
              </Panel>
            ) : null}
            {profiles ? (
              <DemoPanel
                profiles={profiles}
                profileId={state.profileId}
                onSelectProfile={onSelectProfile}
                compare={state.compare}
                onCompareChange={actions.setCompare}
                disabled={state.loading}
              />
            ) : null}
          </>
        }
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
              filters={listResponse ? filters : null}
              onComplete={onComplete}
              onMore={onMore}
              focusIndex={focusIndex}
              cardRef={cardRef}
              headingRef={headingRef}
            />
            {view}
          </>
        }
      />
    </Screen>
  );
}
