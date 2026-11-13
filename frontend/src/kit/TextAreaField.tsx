import { useRef, useState, type ClipboardEvent, type DragEvent, type TextareaHTMLAttributes } from 'react';
import { formatCounter, formatLimitNotice } from '../format';
import { cx } from './cx';

export interface TextAreaFieldProps
  extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id' | 'value' | 'defaultValue' | 'onChange' | 'children'> {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  maxLength: number;
  placeholder?: string;
  /** Подсказка при пустом поле; при вводе её место занимает счётчик «N из 300 символов» */
  hint?: string;
  error?: string | null;
  disabled?: boolean;
  rows?: number;
}

/** Длина вставляемого текста так, как её посчитает textarea: переводы строк \r\n и \r становятся \n */
function insertedLength(text: string): number {
  return text.replace(/\r\n?/g, '\n').length;
}

/** Обрезанная вставка: сколько символов не поместилось и какое значение поля она дала */
interface Cut {
  count: number;
  value: string;
}

/**
 * div.field > label.field__label + textarea.textarea + div.field__error + div.field__hint. Атрибуты — на textarea.
 * У предела поле говорит об этом, а не обрезает вставку молча (docs/ui-kit.md, раздел 3): подсказка под полем
 * называет предел и число символов, которые не поместились, скрытая строка role="status" объявляет то же.
 * Сообщение о вставке относится к значению, которое она дала: правка текста, «Сбросить» или выбор профиля
 * меняют значение и снимают сообщение.
 */
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
  onPaste,
  onDrop,
  'aria-describedby': describedByProp,
  ...rest
}: TextAreaFieldProps) {
  const [cut, setCut] = useState<Cut | null>(null);
  // Сколько символов вставки не поместится: считается до вставки, значение известно после события ввода
  const pending = useRef(0);
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const cutCount = cut?.value === value ? cut.count : 0;
  const atLimit = value.length >= maxLength;
  const notice = cutCount > 0 || atLimit ? formatLimitNotice(maxLength, cutCount) : '';
  const hintText = notice || (value.length > 0 ? formatCounter(value.length, maxLength) : hint);
  const describedBy = cx(describedByProp, error ? errorId : null, hintText ? hintId : null) || undefined;

  // maxlength отбросит хвост вставки: число отброшенных символов считается до вставки
  const measure = (text: string, field: HTMLTextAreaElement) => {
    // У textarea selectionStart и selectionEnd всегда числа; null бывает только у input некоторых типов
    const selected = Math.abs(field.selectionEnd - field.selectionStart);
    const room = Math.max(0, maxLength - (field.value.length - selected));
    const length = insertedLength(text);
    const over = length > room ? length - room : 0;
    if (over > 0 && room === 0) {
      // Поле уже заполнено: maxlength не вставит ни символа, и события ввода не будет
      pending.current = 0;
      setCut({ count: over, value: field.value });
    } else {
      pending.current = over;
    }
  };

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
        onChange={(event) => {
          const next = event.target.value;
          setCut(pending.current > 0 ? { count: pending.current, value: next } : null);
          pending.current = 0;
          onChange(next);
        }}
        onPaste={(event: ClipboardEvent<HTMLTextAreaElement>) => {
          onPaste?.(event);
          if (!event.defaultPrevented) measure(event.clipboardData.getData('text'), event.currentTarget);
        }}
        onDrop={(event: DragEvent<HTMLTextAreaElement>) => {
          onDrop?.(event);
          if (!event.defaultPrevented) measure(event.dataTransfer.getData('text'), event.currentTarget);
        }}
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
        <div id={hintId} className={cx('field__hint', notice && 'field__hint--limit')}>
          {hintText}
        </div>
      ) : null}
      {/* Живая область всегда в дереве: появление сообщения о пределе объявляется. Счётчик не объявляется на каждый символ */}
      <span className="visually-hidden" role="status">
        {notice}
      </span>
    </div>
  );
}
