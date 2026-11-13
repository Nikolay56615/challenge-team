import { useId, useLayoutEffect, useRef, useState, type ReactNode, type Ref, type RefObject } from 'react';
import type { CompareResponse, ExperienceCode, Item, RecommendResponse } from '../api/types';
import { formatShownMaterials, toSentence, typo } from '../format';
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
    return () => {
      observer.disconnect();
    };
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
 * Итог сравнения для строки состояния (docs/ui-kit.md, раздел 4). Позиции сравниваются,
 * только если оба метода вернули выдачу по запросу: стартовая подборка с ней несопоставима.
 */
export function compareStatus(response: CompareResponse): string {
  const { baseline, personal, diff } = response;
  const ready = 'Сравнение готово.';
  if (hasResults(baseline) && hasResults(personal)) {
    return typo(`${ready} Изменились позиции: ${String(diff.changed_positions)} из ${String(diff.compared_positions)}.`);
  }
  // Пустая задача и история профиля: подбор по теме отвечает cold со стартовой подборкой, персональный
  // подбирает по истории (docs/plan.md, раздел 9, решение 2026-11-11). Запроса нет, поэтому о «не нашёл» речи нет
  if (baseline.status === 'cold' && hasResults(personal)) {
    return `${ready} Без задачи подбор по теме показывает стартовую подборку, персональный\u00A0— подбор по истории.`;
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
  const cards = response.items.map((item) => (
    <MaterialCard
      key={item.material_id}
      item={item}
      compact
      onComplete={onComplete}
      experience={experience}
    />
  ));

  return (
    <div className="compare__col">
      <h3 className="h3">{title}</h3>
      {ranked ? (
        <>
          <p className="note">{formatShownMaterials(cards.length, response.total_candidates)}</p>
          {cards}
        </>
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
  topicLabel?: string | undefined;
  filters?: ReactNode;
  onTabChange: (tab: CompareTab) => void;
  /** Заголовок принимает фокус, когда нажатый элемент исчез вместе с прежним ответом */
  headingRef?: Ref<HTMLHeadingElement>;
  /** Опыт из запроса сравнения: для пометки «уровень» (src/match.ts) */
  experience?: ExperienceCode | null;
}

/** Один профиль, один каталог, два метода. Широкий экран — две колонки, узкий — вкладки. */
export function CompareView({ response, onComplete, tab, onTabChange, headingRef, topicLabel, filters, experience = null }: CompareViewProps) {
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
  // Позиции сравниваются только между двумя выдачами по запросу
  const diff = hasResults(response.baseline) && hasResults(response.personal) ? response.diff : null;

  return (
    <div ref={rootRef} className="results">
      <Panel labelledBy={headingId}>
        <h2 id={headingId} ref={headingRef} className="h2" tabIndex={-1}>
          {topicLabel ? `Сравнение по теме «${topicLabel}»` : 'Сравнение методов на одном профиле и\u00a0каталоге'}
        </h2>
        {diff ? (
          <p className="note">
            {typo(`Изменились позиции: ${String(diff.changed_positions)} из ${String(diff.compared_positions)}.`)}
          </p>
        ) : null}
      </Panel>

      {filters}
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
