import { useId, type Ref } from 'react';
import type { Option, TopicCode } from '../api/types';
import { Button, Panel } from '../kit';
import { TopicPicker } from './TopicPicker';

interface CatalogTopicsProps {
  headingRef: Ref<HTMLHeadingElement>;
  topics: readonly Option<TopicCode>[];
  loaded: boolean;
  failed: boolean;
  reload(): void;
  value: TopicCode | null;
  current: TopicCode | null;
  onChange(value: TopicCode | null): void;
  onShow(value: TopicCode): void;
  disabled: boolean;
}

export function CatalogTopics({
  headingRef, topics, loaded, failed, reload, value, current, onChange, onShow, disabled,
}: CatalogTopicsProps) {
  const headingId = useId();
  return (
    <Panel labelledBy={headingId}>
      <h1 id={headingId} ref={headingRef} className="h1" tabIndex={-1}>Каталог</h1>
      {failed ? (
        <div className="actions">
          <p role="alert">Не удалось загрузить темы каталога</p>
          <Button onClick={reload}>Повторить</Button>
        </div>
      ) : !loaded ? (
        <p className="note" role="status">Загружаем темы…</p>
      ) : topics.length === 0 ? (
        <p>В каталоге пока нет доступных тем.</p>
      ) : (
        <>
          <div className="catalog-topics__picker">
            <TopicPicker
              label="Тема каталога"
              options={topics}
              value={value}
              onChange={onChange}
              onShow={onShow}
              disabled={disabled}
            />
          </div>
          <ul className="catalog-topics__list" aria-label="Темы каталога">
            {topics.map(({ label, value: topic }) => (
              <li key={topic}>
                <Button aria-pressed={current === topic} disabled={disabled} onClick={() => onShow(topic)}>
                  {label}
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
