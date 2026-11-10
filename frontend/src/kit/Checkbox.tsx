import type { InputHTMLAttributes } from 'react';

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'checked' | 'defaultChecked' | 'onChange' | 'children'> {
  checked: boolean;
  onChange(checked: boolean): void;
  label: string;
  disabled?: boolean;
}

/** label.checkbox > input[type=checkbox] + текст. Атрибуты — на input. */
export function Checkbox({ checked, onChange, label, disabled = false, ...rest }: CheckboxProps) {
  return (
    <label className="checkbox">
      <input
        {...rest}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}
