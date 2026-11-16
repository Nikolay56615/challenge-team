import type { InputHTMLAttributes, ReactNode } from 'react';
import { cx } from './cx';

export interface TextFieldProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'id' | 'value' | 'defaultValue' | 'onChange' | 'children' | 'type'
> {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  /** Подсказка под полем: div.field__hint, связана через aria-describedby */
  hint?: ReactNode;
  error?: string | null;
  /** Кнопка в одной строке с полем, например «Найти» */
  action?: ReactNode;
  disabled?: boolean;
}

/**
 * div.field > label.field__label + div.field__row (input.input + действие) + div.field__error + div.field__hint.
 * Атрибуты — на input. Ошибка объявляется сразу: role="alert".
 */
export function TextField({
  id,
  label,
  value,
  onChange,
  hint,
  error,
  action,
  disabled = false,
  className,
  'aria-describedby': describedByProp,
  ...rest
}: TextFieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = cx(describedByProp, error ? errorId : null, hint ? hintId : null) || undefined;
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <div className="field__row">
        <input
          {...rest}
          id={id}
          type="text"
          className={cx('input', className)}
          value={value}
          disabled={disabled}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
        {action}
      </div>
      {error ? (
        <div id={errorId} className="field__error" role="alert">
          {error}
        </div>
      ) : null}
      {hint ? (
        <div id={hintId} className="field__hint">
          {hint}
        </div>
      ) : null}
    </div>
  );
}
