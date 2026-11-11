import { useId, useLayoutEffect, useRef, useState, type Ref, type RefObject } from 'react';
import type { CompareResponse, Item, RecommendResponse } from '../api/types';
import { toSentence } from '../format';
import { Panel, TabPanel, Tabs } from '../kit';
import { MaterialCard } from './MaterialCard';

/** Порог компоновки, как в @container screen (min-width: 800px) в kit.css */
const WIDE_MIN_WIDTH = 800;

/** Ширина ближайшего контейнера .screen, а не окна: так же решает контейнерный запрос */
function useScreenIsWide(ref: RefObject<HTMLElement | null>): boolean {
  const [wide, setWide] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const screen = element.closest<HTMLElement>('.screen') ?? document.documentElement;
    setWide(screen.clientWidth >= WIDE_MIN_WIDTH);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWide(entry.contentRect.width >= WIDE_MIN_WIDTH);
    });
    observer.observe(screen);
    return () => observer.disconnect();
  }, [ref]);
  return wide;
}

/**
 * Выдача по запросу: статус strong или weak и хотя бы одна карточка.
 * При none, cold и empty метод показывает сообщение и стартовую подборку или только сообщение.
 */
function hasResults(response: RecommendResponse): boolean {
  return (response.status === 'strong' || response.status === 'weak') && response.items.length > 0;
}

/**
 * Итог сравнения для строки состояния (design/ui-kit.md, раздел 4). Позиции сравниваются,
 * только если оба метода вернули выдачу по запросу: стартовая подборка с ней несопоставима.
 */
export function compareStatus(response: CompareResponse): string {
  const { baseline, personal, diff } = response;
  const ready = 'Сравнение готово.';
  if (hasResults(baseline) && hasResults(personal)) {
    return `${ready} Изменились позиции: ${diff.changed_positions} из ${diff.compared_positions}.`;
  }
  if (hasResults(personal)) return `${ready} Подбор по теме не нашёл материалов по запросу.`;
  if (hasResults(baseline)) return `${ready} Персональный подбор не нашёл материалов по запросу.`;
  if (baseline.status === 'cold' && personal.status === 'cold' && baseline.items.length && personal.items.length) {
    return `${ready} Без задачи оба метода показывают стартовую подборку.`;
  }
  return `${ready} Ни один метод не нашёл материалов по запросу.`;
}

interface ColumnProps {
  title: string;
  response: RecommendResponse;
  onComplete?(item: Item): void;
}

/**
 * Колонка метода. Выдача по запросу — карточки. При none, cold и empty вместо карточек сообщение
 * ответа, а карточки собраны в группу «Стартовая подборка».
 */
function Column({ title, response, onComplete }: ColumnProps) {
  const starterId = useId();
  const ranked = hasResults(response);
  // Бейдж темы — как в основной выдаче: у смешанной выдачи и стартовой подборки
  const showTopics = !ranked || response.status === 'weak';
  const cards = response.items.map((item) => (
    <MaterialCard key={item.material_id} item={item} compact showTopics={showTopics} onComplete={onComplete} />
  ));

  return (
    <div className="compare__col">
      <h3 className="h3">{title}</h3>
      {ranked ? (
        cards
      ) : (
        <>
          <p>{toSentence(response.message)}</p>
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
  onComplete?(item: Item): void;
  /** Выбранная вкладка хранится снаружи: представление пересоздаётся при повторе запроса */
  tab: CompareTab;
  onTabChange(tab: CompareTab): void;
  /** Заголовок принимает фокус, когда нажатый элемент исчез вместе с прежним ответом */
  headingRef?: Ref<HTMLHeadingElement>;
}

/** Один профиль, один каталог, два метода. Широкий экран — две колонки, узкий — вкладки. */
export function CompareView({ response, onComplete, tab, onTabChange, headingRef }: CompareViewProps) {
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

  const baseline = <Column title="Подбор по теме" response={response.baseline} onComplete={onComplete} />;
  const personal = <Column title="Персональный подбор" response={response.personal} onComplete={onComplete} />;
  // Позиции сравниваются только между двумя выдачами по запросу
  const diff = hasResults(response.baseline) && hasResults(response.personal) ? response.diff : null;

  return (
    <div ref={rootRef} className="results">
      <Panel labelledBy={headingId}>
        <h2 id={headingId} ref={headingRef} className="h2" tabIndex={-1}>
          Сравнение методов на одном профиле и каталоге
        </h2>
        {diff ? (
          <p className="note">
            Изменились позиции: {diff.changed_positions} из {diff.compared_positions}.
          </p>
        ) : null}
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
            onSelect={(id) => onTabChange(id === baselineTab.id ? 'baseline' : 'personal')}
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
