import type { TextareaHTMLAttributes } from 'react';
import { formatCounter } from '../format';
import { cx } from './cx';

export interface TextAreaFieldProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id' | 'value' | 'defaultValue' | 'onChange' | 'children'> {
  id: string;
  label: string;
  value: string;
  onChange(value: string): void;
  maxLength: number;
  placeholder?: string;
  /** Подсказка при пустом поле; при вводе её место занимает счётчик «N из 300 символов» */
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  rows?: number;
}

/** div.field > label.field__label + textarea.textarea + div.field__error + div.field__hint. Атрибуты — на textarea. */
export function TextAreaField({
  id,
  label,
  value,
  onChange,
  maxLength,
  placeholder,
  hint,
  error,
  disabled = false,
  rows = 3,
  className,
  'aria-describedby': describedByProp,
  ...rest
}: TextAreaFieldProps) {
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const hintText = value.length > 0 ? formatCounter(value.length, maxLength) : hint;
  const describedBy = cx(describedByProp, error ? errorId : null, hintText ? hintId : null) || undefined;
  return (
    <div className="field">
      <label className="field__label" htmlFor={id}>
        {label}
      </label>
      <textarea
        {...rest}
        id={id}
        className={cx('textarea', className)}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        maxLength={maxLength}
        placeholder={placeholder}
        disabled={disabled}
        rows={rows}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
      />
      {error ? (
        <div id={errorId} className="field__error">
          {error}
        </div>
      ) : null}
      {hintText ? (
        <div id={hintId} className="field__hint">
          {hintText}
        </div>
      ) : null}
    </div>
  );
}
