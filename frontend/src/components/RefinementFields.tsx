import { useId } from 'react';
import type { MetaResponse } from '../api/types';
import { ChipGroup, Disclosure, SelectField } from '../kit';
import type { FormValues, RefinementValues } from '../state/useRecommend';

export interface RefinementFieldsProps {
  /** Подписи стадий, опыта, форматов и сфер из GET /api/meta */
  meta: MetaResponse | null;
  metaFailed?: boolean;
  values: FormValues;
  onChange(patch: Partial<RefinementValues>): void;
  disabled?: boolean;
}

/** Disclosure «Уточнения — необязательно»: три группы чипов и список сфер */
export function RefinementFields({ meta, metaFailed = false, values, onChange, disabled = false }: RefinementFieldsProps) {
  const uid = useId();
  return (
    <Disclosure
      summary={
        <span>
          Уточнения <span className="field__optional">необязательно</span>
        </span>
      }
    >
      {meta ? (
        <>
          <ChipGroup
            legend="Стадия бизнеса"
            optional
            name="stage"
            options={meta.stages}
            value={values.stage}
            onChange={(stage) => onChange({ stage })}
            disabled={disabled}
          />
          <ChipGroup
            legend="Опыт в теме"
            optional
            name="experience"
            options={meta.experience}
            value={values.experience}
            onChange={(experience) => onChange({ experience })}
            disabled={disabled}
          />
          <ChipGroup
            legend="Нужный формат"
            optional
            name="format"
            options={meta.formats}
            value={values.format_pref}
            onChange={(format_pref) => onChange({ format_pref })}
            disabled={disabled}
          />
          <SelectField
            id={`${uid}-industry`}
            label="Сфера бизнеса"
            optional
            value={values.industry}
            onChange={(industry) => onChange({ industry })}
            options={meta.industries}
            emptyLabel="Не указана"
            disabled={disabled}
          />
        </>
      ) : metaFailed ? (
        <p className="hint">Не удалось загрузить варианты уточнений. Подбор работает и без них.</p>
      ) : null}
    </Disclosure>
  );
}
