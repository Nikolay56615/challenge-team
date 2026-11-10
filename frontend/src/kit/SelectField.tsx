import type { ReactNode, SelectHTMLAttributes } from 'react';
import { cx } from './cx';

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

export interface SelectFieldProps<T extends string>
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id' | 'value' | 'defaultValue' | 'onChange' | 'children' | 'multiple'> {
  id: string;
  label: string;
  optional?: boolean;
  value: T | null;
  onChange(value: T | null): void;
  options: readonly SelectOption<T>[];
  /** Подпись пустого значения: «Не указана» или «Не выбран» */
  emptyLabel: string;
  /** Подсказка под списком: div.field__hint, связана через aria-describedby */
  hint?: ReactNode;
  compact?: boolean;
  disabled?: boolean;
}

/** div.field > label + select.select + div.field__hint, компактный вариант select--compact. Атрибуты — на select. */
export function SelectField<T extends string>({
  id,
  label,
  optional = false,
  value,
  onChange,
  options,
  emptyLabel,
  hint,
  compact = false,
  disabled = false,
  className,
  'aria-describedby': describedByProp,
  ...rest
}: SelectFieldProps<T>) {
  const hintId = `${id}-hint`;
  const describedBy = cx(describedByProp, hint ? hintId : null) || undefined;
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
        {optional && (
          <>
            {' '}
            <span className="field__optional">необязательно</span>
          </>
        )}
      </label>
      <select
        {...rest}
        id={id}
        className={cx('select', compact && 'select--compact', className)}
        value={value ?? ''}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(event) => {
          const next = options.find((option) => option.value === event.target.value);
          onChange(next ? next.value : null);
        }}
      >
        <option value="">{emptyLabel}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint ? (
        <div id={hintId} className="field__hint">
          {hint}
        </div>
      ) : null}
    </div>
  );
}
