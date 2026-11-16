import { useId, useRef, type FieldsetHTMLAttributes, type KeyboardEvent } from 'react';
import { cx } from './cx';

export interface ChipOption<T extends string> {
  value: T;
  label: string;
}

export interface ChipGroupProps<T extends string>
  extends Omit<FieldsetHTMLAttributes<HTMLFieldSetElement>, 'name' | 'onChange' | 'children' | 'disabled'> {
  legend: string;
  legendHidden?: boolean;
  /** Имя радиогруппы; к нему добавляется уникальный суффикс экземпляра */
  name: string;
  options: readonly ChipOption<T>[];
  value: T | null;
  onChange: (value: T | null) => void;
  optional?: boolean;
  /** Повторное нажатие на выбранный чип снимает выбор */
  allowDeselect?: boolean;
  disabled?: boolean;
  /**
   * auto — стрелки выбирают чип, как в нативной радиогруппе: поля формы.
   * manual — выбор запускает действие: стрелки только переносят фокус,
   * выбирают щелчок, пробел и Enter (WCAG 3.2.2). Темы уточнения и пустой выдачи.
   */
  activation?: 'auto' | 'manual';
}

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown']);
const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp']);

/** fieldset.field > legend + div.chip-group > label.chip > input[type=radio] + span.chip__label */
export function ChipGroup<T extends string>({
  legend,
  legendHidden = false,
  name,
  options,
  value,
  onChange,
  optional = false,
  allowDeselect = true,
  disabled = false,
  activation = 'auto',
  className,
  ...rest
}: ChipGroupProps<T>) {
  const groupName = `${name}-${useId()}`;
  const inputs = useRef<(HTMLInputElement | null)[]>([]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>, index: number, option: T, checked: boolean) => {
    // Пробел: по выбранной радиокнопке браузер click не отправляет
    if (event.key === ' ' && checked && allowDeselect) {
      event.preventDefault();
      onChange(null);
      return;
    }
    // Сочетания с Alt, Ctrl, Meta остаются браузеру
    if (activation !== 'manual' || event.altKey || event.ctrlKey || event.metaKey) return;
    const step = NEXT_KEYS.has(event.key) ? 1 : PREV_KEYS.has(event.key) ? -1 : 0;
    if (step !== 0) {
      // Стрелки только переносят фокус: выбор не меняется, действие не запускается
      event.preventDefault();
      inputs.current[(index + step + options.length) % options.length]?.focus();
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (!checked) onChange(option);
      else if (allowDeselect) onChange(null);
    }
  };

  return (
    <fieldset {...rest} className={cx('field', className)}>
      <legend className={legendHidden ? 'visually-hidden' : undefined}>
        {legend}
        {optional && (
          <>
            {' '}
            <span className="field__optional">необязательно</span>
          </>
        )}
      </legend>
      <div className="chip-group">
        {options.map((option, index) => {
          const checked = option.value === value;
          return (
            <label key={option.value} className="chip">
              <input
                ref={(element) => {
                  inputs.current[index] = element;
                }}
                type="radio"
                className="visually-hidden"
                name={groupName}
                value={option.value}
                checked={checked}
                disabled={disabled}
                onChange={() => {
                  onChange(option.value);
                }}
                // Повторное нажатие снимает выбор. Мышь: click приходит и по выбранной радиокнопке
                onClick={() => {
                  if (checked && allowDeselect) onChange(null);
                }}
                onKeyDown={(event) => {
                  onKeyDown(event, index, option.value, checked);
                }}
              />
              <span className="chip__label">{option.label}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
