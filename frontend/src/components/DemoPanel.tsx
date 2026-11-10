import { useId } from 'react';
import type { Profile } from '../api/types';
import { Checkbox, Panel, SelectField } from '../kit';

export interface DemoPanelProps {
  profiles: readonly Profile[];
  profileId: string | null;
  onSelectProfile(id: string | null): void;
  compare: boolean;
  onCompareChange(value: boolean): void;
  disabled?: boolean;
}

/**
 * Демо-режим: тестовый профиль с синтетической историей и переключатель сравнения.
 * Выбор профиля заполняет форму и историю сеанса, «Не выбран» очищает историю; прежняя выдача сбрасывается.
 */
export function DemoPanel({ profiles, profileId, onSelectProfile, compare, onCompareChange, disabled = false }: DemoPanelProps) {
  const uid = useId();
  const headingId = `${uid}-title`;
  const options = profiles.map((profile) => ({ value: profile.id, label: profile.label }));
  const selected = profiles.find((profile) => profile.id === profileId);

  return (
    <Panel as="aside" tone="subtle" labelledBy={headingId}>
      <div className="panel__row">
        <h2 id={headingId} className="kv__label">
          Демо-режим
        </h2>
        <span className="hint">только в локальном стенде</span>
      </div>
      <SelectField
        id={`${uid}-profile`}
        label="Тестовый профиль"
        value={profileId}
        onChange={onSelectProfile}
        options={options}
        emptyLabel="Не выбран"
        hint={selected?.description || undefined}
        compact
        disabled={disabled}
      />
      <Checkbox checked={compare} onChange={onCompareChange} label="Сравнить с подбором по теме" disabled={disabled} />
    </Panel>
  );
}
