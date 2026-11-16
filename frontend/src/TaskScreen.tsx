import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type { Clarification, Item, RecommendResponse, StageCode, TopicCode } from './api/types';
import { CompareView, compareStatus, type CompareTab } from './components/CompareView';
import { DemoPanel } from './components/DemoPanel';
import { EmptyState, STARTER_VISIBLE, starterTotal } from './components/EmptyState';
import { IntroPanel } from './components/IntroPanel';
import { LOADING_STATUS, ResultList } from './components/ResultList';
import { NETWORK_ERROR_TEXT, StateBanner } from './components/StateBanner';
import { TaskForm } from './components/TaskForm';
import { Layout, SKELETON_DELAY_MS, Stale, useDelayedFlag } from './kit';
import { DEFAULT_MAX_TASK_LENGTH, type useMeta } from './state/useMeta';
import { useRecommend } from './state/useRecommend';

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

/** Подбор по тексту задачи с анкетой и сравнением методов: прежний главный экран */
export function TaskScreen({ metaState }: { metaState: ReturnType<typeof useMeta> }) {
  const { meta, profiles } = metaState;
  const { state, actions } = useRecommend();
  const maxLength = meta?.max_task_length ?? DEFAULT_MAX_TASK_LENGTH;
  const examplesId = useId();

  // Представление выдачи переживает повтор того же запроса и сбрасывается новым запросом
  const [compareTab, setCompareTab] = useState<CompareTab>('personal');
  const [starterExpanded, setStarterExpanded] = useState(false);
  const [focusIndex, setFocusIndex] = useState<number | null>(null);
  const [introVersion, setIntroVersion] = useState(0);

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
    actions.chooseTopic(topic);
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

  const onSubmit = () => {
    if (metaState.failed) metaState.reload();
    resetView();
    // На узком экране выдача ниже формы: после ответа фокус переходит к первой карточке или заголовку представления
    focusGoal.current = 'submit';
    actions.submit();
  };
  const onExample = (task: string, stage: StageCode | null) => {
    if (metaState.failed) metaState.reload();
    resetView();
    fromContent(actions.submitExample)(task, stage);
  };
  const onReset = () => {
    resetView();
    setIntroVersion((version) => version + 1);
    actions.reset();
  };
  const onSelectProfile = (id: string | null) => {
    resetView();
    actions.selectProfile(profiles?.find((profile) => profile.id === id) ?? null);
  };

  // Правая колонка: баннер, строка состояния с выдачей, другое представление
  let banner: ReactNode = null;
  let status = '';
  let statusHidden = true;
  let listResponse: RecommendResponse | null = null;
  let showTopics = false;
  let view: ReactNode = null;

  const { outcome, failure } = state;
  // Опыт из запроса, по которому получена выдача: пометка «уровень» только при точном совпадении (src/match.ts)
  const experience = state.resultCall?.body.experience ?? null;
  // До появления скелетонов прежняя выдача остаётся видимой и неактивной.
  const slow = useDelayedFlag(state.loading, SKELETON_DELAY_MS);
  const holding = state.loading && !slow;

  const clarificationBanner = (clarification: Clarification) => (
    <StateBanner
      kind="clarification"
      clarification={clarification}
      topic={state.topic}
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
    if (previous?.status === 'weak' && previous.clarification && !state.clarificationHidden) {
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
    view = (
      <IntroPanel
        key={`${String(introVersion)}:${state.profileId ?? ''}`}
        id={examplesId}
        disabled={state.loading}
        onExample={onExample}
      />
    );
  } else if (outcome.kind === 'compare') {
    // Позиции названы, только если оба метода вернули выдачу по запросу; иначе — какой метод ничего не нашёл
    status = compareStatus(outcome.response);
    view = (
      <CompareView
        response={outcome.response}
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
      showTopics = response.status === 'weak';
      if (response.status === 'weak' && response.clarification && !state.clarificationHidden) {
        banner = clarificationBanner(response.clarification);
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
  useEffect(() => {
    const goal = focusGoal.current;
    if (!goal || state.loading) return;
    focusGoal.current = null;
    // Ошибка поля: фокус уже переведён на поле задачи в TaskForm
    if (state.fieldError) return;
    const active = document.activeElement;
    // После отправки переводим фокус с кнопки к выдаче. Если пользователь уже перешёл в другое поле,
    // оставляем фокус там.
    if (active && active !== document.body && active !== statusRef.current &&
      (goal !== 'submit' || active !== submitRef.current)) return;
    let target: HTMLElement | null;
    if (failure) target = retryRef.current;
    else if (goal === 'card' && cardRef.current) target = cardRef.current;
    else if (firstCardRef.current) target = firstCardRef.current;
    else if (statusHidden) target = headingRef.current;
    else target = statusRef.current;
    if (target && target === firstCardRef.current && bannerRef.current) focusBelowBanner(target, bannerRef.current);
    else target?.focus();
  });

  return (
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
              busy={slow}
              {...(!outcome && !failure ? { examplesId } : {})}
              submitRef={submitRef}
              onTaskChange={actions.setTask}
              onRefinementsChange={actions.setRefinements}
              onSubmit={onSubmit}
              onReset={onReset}
            />
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
              loading={slow}
              stale={holding}
              response={listResponse}
              showTopics={showTopics}
              onComplete={onComplete}
              onMore={onMore}
              focusIndex={focusIndex}
              cardRef={cardRef}
              firstCardRef={firstCardRef}
              experience={experience}
            />
            <Stale active={holding}>{view}</Stale>
          </>
        }
      />
  );
}
