import { useEffect, useId, type Ref } from 'react';
import type { MetaResponse } from '../api/types';
import { charsGenitive, formatAvailableMaterials } from '../format';
import { Button, Panel, TextAreaField } from '../kit';
import type { FormValues, RefinementValues } from '../state/useRecommend';
import { RefinementFields } from './RefinementFields';

export interface TaskFormProps {
  headingRef?: Ref<HTMLHeadingElement>;
  meta: MetaResponse | null;
  metaFailed?: boolean;
  values: FormValues;
  maxLength: number;
  /** Ошибка валидации задачи из ответа 422 */
  error: string | null;
  loading: boolean;
  onTaskChange(value: string): void;
  onRefinementsChange(patch: Partial<RefinementValues>): void;
  onSubmit(): void;
  onReset(): void;
}

/** Форма: задача, уточнения, «Подобрать материалы» и «Сбросить». Данные не очищаются при загрузке и ошибке. */
export function TaskForm({
  headingRef,
  meta,
  metaFailed = false,
  values,
  maxLength,
  error,
  loading,
  onTaskChange,
  onRefinementsChange,
  onSubmit,
  onReset,
}: TaskFormProps) {
  const uid = useId();
  const headingId = `${uid}-title`;
  const taskId = `${uid}-task`;
  const catalog = meta?.catalog;

  // Ошибка валидации: фокус на поле, текст ошибки связан через aria-describedby
  useEffect(() => {
    if (error) document.getElementById(taskId)?.focus();
  }, [error, taskId]);

  return (
    <Panel labelledBy={headingId}>
      <h1 id={headingId} ref={headingRef} className="h1" tabIndex={-1}>
        Подберём материалы под вашу задачу
      </h1>
      {catalog ? (
        <p className="note">
          {catalog.source === 'synthetic'
            ? 'Тестовый каталог'
            : `Локальный каталог · ${formatAvailableMaterials(catalog.available)}`}
        </p>
      ) : null}
      <TextAreaField
        id={taskId}
        label="Что вы хотите сделать?"
        value={values.task}
        onChange={onTaskChange}
        maxLength={maxLength}
        placeholder="Например: запустить первую рекламу"
        hint={`До ${maxLength} ${charsGenitive(maxLength)}. Можно своими словами, без терминов`}
        error={error}
        disabled={loading}
        rows={3}
      />
      <RefinementFields
        meta={meta}
        metaFailed={metaFailed}
        values={values}
        onChange={onRefinementsChange}
        disabled={loading}
      />
      <div className="actions">
        {/* Во время загрузки кнопка остаётся в фокусе: aria-disabled вместо disabled */}
        <Button
          variant="primary"
          aria-disabled={loading || undefined}
          onClick={() => {
            if (!loading) onSubmit();
          }}
        >
          {loading ? 'Подбираем…' : 'Подобрать материалы'}
        </Button>
        <Button variant="link" onClick={onReset}>
          Сбросить
        </Button>
      </div>
    </Panel>
  );
}
