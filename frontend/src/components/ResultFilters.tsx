import { useId, useState } from 'react';
import type { FilterOptions, MaterialFilters, Option } from '../api/types';
import { Button, Panel, SelectField } from '../kit';

const NO_FILTERS: MaterialFilters = { format: null, access: null };

function mergeOptions<T extends string>(left: Option<T>[], right: Option<T>[]): Option<T>[] {
  return [...new Map([...left, ...right].map((option) => [option.value, option])).values()];
}

export function mergeFilterOptions(
  left: FilterOptions | null | undefined,
  right: FilterOptions | null | undefined,
): FilterOptions | null {
  if (!left || !right) return left ?? right ?? null;
  return { formats: mergeOptions(left.formats, right.formats), access: mergeOptions(left.access, right.access) };
}

export interface ResultFiltersProps {
  options: FilterOptions;
  applied?: MaterialFilters | null;
  onApply(filters: MaterialFilters | null): void;
}

function withCurrent<T extends string>(options: Option<T>[], value: T | null, label: string): Option<T>[] {
  if (value === null || options.some((option) => option.value === value)) return options;
  return [...options, { value, label }];
}

export function ResultFilters({ options, applied, onApply }: ResultFiltersProps) {
  const id = useId();
  const current = applied ?? NO_FILTERS;
  const [draft, setDraft] = useState(current);
  const changed = draft.format !== current.format || draft.access !== current.access;
  const active = Boolean(current.format || current.access);
  const formats = withCurrent(options.formats, current.format, 'Выбранный формат недоступен');
  const access = withCurrent(options.access, current.access, 'Выбранный вид доступа недоступен');

  return (
    <Panel as="div" tone="subtle" role="group" aria-label="Фильтры выдачи">
      <div className="result-filters__fields">
        <SelectField
          id={`${id}-format`}
          label="Формат"
          emptyLabel="Все форматы"
          options={formats}
          value={draft.format}
          onChange={(format) => setDraft({ ...draft, format })}
        />
        <SelectField
          id={`${id}-access`}
          label="Доступ"
          emptyLabel="Любой доступ"
          options={access}
          value={draft.access}
          onChange={(access) => setDraft({ ...draft, access })}
        />
      </div>
      <div className="actions">
        <Button disabled={!changed} onClick={() => onApply(draft)}>Применить фильтры</Button>
        <Button
          variant="link"
          disabled={!active && !changed}
          onClick={() => onApply(null)}
        >
          Сбросить фильтры
        </Button>
      </div>
    </Panel>
  );
}
