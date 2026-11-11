import { useId } from 'react';
import type { Option, TopicCode } from '../api/types';
import { Button, SelectField } from '../kit';

interface TopicPickerProps {
  label: string;
  options: readonly Option<TopicCode>[];
  value: TopicCode | null;
  onChange(topic: TopicCode | null): void;
  onShow(topic: TopicCode): void;
  disabled?: boolean;
}

export function TopicPicker({ label, options, value, onChange, onShow, disabled }: TopicPickerProps) {
  const id = useId();
  const selected = options.find((option) => option.value === value);
  return (
    <>
      <SelectField
        id={id}
        label={label}
        options={options}
        value={selected?.value ?? null}
        onChange={onChange}
        emptyLabel="Выберите тему"
        disabled={disabled}
      />
      <div className="actions">
        <Button disabled={disabled || !selected} onClick={() => { if (selected) onShow(selected.value); }}>
          Показать материалы темы
        </Button>
      </div>
    </>
  );
}
