import { useId, useRef, type Ref } from 'react';
import type { CompareResponse, ExperienceCode, Item, RecommendResponse } from '../api/types';
import { toSentence, typo } from '../format';
import { Panel, TabPanel, Tabs } from '../kit';
import { useScreenIsWide } from '../state/useScreenIsWide';
import { MaterialCard } from './MaterialCard';

/**
 * Выдача по запросу: статус strong или weak и хотя бы одна карточка.
 * При none, cold и empty метод показывает сообщение и стартовую подборку или только сообщение.
 */
function hasResults(response: RecommendResponse): boolean {
  return (response.status === 'strong' || response.status === 'weak') && response.items.length > 0;
}

/**
 * Итог сравнения для строки состояния (docs/ui-kit.md, раздел 4). Позиции сравниваются,
 * только если оба метода вернули выдачу по запросу: стартовая подборка с ней несопоставима.
 */
export function compareStatus(response: CompareResponse): string {
  const { baseline, personal, diff } = response;
  if (hasResults(baseline) && hasResults(personal)) {
    return typo(`Изменились позиции: ${String(diff.changed_positions)} из ${String(diff.compared_positions)}.`);
  }
  // Пустая задача: подбор по теме показывает стартовую подборку, персональный подбирает по истории
  if (baseline.status === 'cold' && hasResults(personal)) {
    return 'Без задачи: стартовая подборка и\u00A0подбор по истории.';
  }
  if (hasResults(personal)) return 'Подбор по теме не нашёл материалов.';
  if (hasResults(baseline)) return 'Персональный подбор не нашёл материалов.';
  if (baseline.status === 'cold' && personal.status === 'cold' && baseline.items.length && personal.items.length) {
    return 'Без задачи: стартовая подборка.';
  }
  return 'Материалов по запросу нет.';
}

interface ColumnProps {
  title: string;
  response: RecommendResponse;
  onComplete?: ((item: Item) => void) | undefined;
  experience: ExperienceCode | null;
}

/**
 * Колонка метода. Выдача по запросу — карточки. При none, cold и empty вместо карточек сообщение
 * ответа, а карточки собраны в группу «Стартовая подборка».
 */
function Column({ title, response, onComplete, experience }: ColumnProps) {
  const starterId = useId();
  const ranked = hasResults(response);
  // Бейдж темы — как в основной выдаче: у смешанной выдачи и стартовой подборки
  const showTopics = !ranked || response.status === 'weak';
  const cards = response.items.map((item) => (
    <MaterialCard
      key={item.material_id}
      item={item}
      compact
      showTopics={showTopics}
      onComplete={onComplete}
      experience={experience}
    />
  ));

  return (
    <div className="compare__col">
      <h3 className="h3">{title}</h3>
      {ranked ? (
        cards
      ) : (
        <>
          <p className="compare__message">{typo(toSentence(response.message))}</p>
          {cards.length > 0 ? (
            <div className="starter" role="group" aria-labelledby={starterId}>
              <p id={starterId} className="kv__label">
                Стартовая подборка
              </p>
              {cards}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

/** Метод на вкладке узкого экрана */
export type CompareTab = 'baseline' | 'personal';

export interface CompareViewProps {
  response: CompareResponse;
  onComplete?: (item: Item) => void;
  /** Выбранная вкладка хранится снаружи: представление пересоздаётся при повторе запроса */
  tab: CompareTab;
  onTabChange: (tab: CompareTab) => void;
  /** Заголовок принимает фокус, когда нажатый элемент исчез вместе с прежним ответом */
  headingRef?: Ref<HTMLHeadingElement>;
  /** Опыт из запроса сравнения: для пометки «уровень» (src/match.ts) */
  experience?: ExperienceCode | null;
}

/** Один профиль, один каталог, два метода. Широкий экран — две колонки, узкий — вкладки. */
export function CompareView({ response, onComplete, tab, onTabChange, headingRef, experience = null }: CompareViewProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const wide = useScreenIsWide(rootRef);
  const uid = useId();
  const headingId = `${uid}-title`;
  const tabs = [
    { id: `${uid}-baseline`, label: 'Подбор по теме' },
    { id: `${uid}-personal`, label: 'Персональный подбор' },
  ] as const;
  const [baselineTab, personalTab] = tabs;
  const selected = tab === 'baseline' ? baselineTab.id : personalTab.id;

  const baseline = (
    <Column title="Подбор по теме" response={response.baseline} onComplete={onComplete} experience={experience} />
  );
  const personal = (
    <Column title="Персональный подбор" response={response.personal} onComplete={onComplete} experience={experience} />
  );

  return (
    <div ref={rootRef} className="results">
      <Panel labelledBy={headingId}>
        <h2 id={headingId} ref={headingRef} className="h2" tabIndex={-1}>
          Сравнение
        </h2>
      </Panel>

      {wide ? (
        <div className="compare">
          {baseline}
          {personal}
        </div>
      ) : (
        <>
          <Tabs
            ariaLabel="Метод подбора"
            tabs={tabs}
            selected={selected}
            onSelect={(id) => {
              onTabChange(id === baselineTab.id ? 'baseline' : 'personal');
            }}
          />
          <div className="compare">
            <TabPanel tabId={baselineTab.id} hidden={tab !== 'baseline'}>
              {baseline}
            </TabPanel>
            <TabPanel tabId={personalTab.id} hidden={tab !== 'personal'}>
              {personal}
            </TabPanel>
          </div>
        </>
      )}
    </div>
  );
}
