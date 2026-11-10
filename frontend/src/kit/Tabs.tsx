import { useRef, type HTMLAttributes, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from './cx';

export interface TabItem {
  id: string;
  label: string;
}

export interface TabsProps extends Omit<HTMLAttributes<HTMLDivElement>, 'onSelect' | 'children' | 'role'> {
  ariaLabel: string;
  /** id вкладок уникальны на странице: из них строятся id элементов */
  tabs: readonly TabItem[];
  selected: string;
  onSelect(id: string): void;
}

const tabDomId = (id: string) => `${id}-tab`;
const panelDomId = (id: string) => `${id}-panel`;

/** div.tabs[role=tablist] > button.tab[role=tab]. Стрелки, Home, End, подвижный tabindex. */
export function Tabs({ ariaLabel, tabs, selected, onSelect, className, ...rest }: TabsProps) {
  const buttons = useRef(new Map<string, HTMLButtonElement>());

  const moveTo = (index: number) => {
    const tab = tabs[(index + tabs.length) % tabs.length];
    if (!tab) return;
    onSelect(tab.id);
    buttons.current.get(tab.id)?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (event.key) {
      case 'ArrowRight':
        moveTo(index + 1);
        break;
      case 'ArrowLeft':
        moveTo(index - 1);
        break;
      case 'Home':
        moveTo(0);
        break;
      case 'End':
        moveTo(tabs.length - 1);
        break;
      default:
        return;
    }
    event.preventDefault();
  };

  return (
    <div {...rest} className={cx('tabs', className)} role="tablist" aria-label={ariaLabel}>
      {tabs.map((tab, index) => {
        const isSelected = tab.id === selected;
        return (
          <button
            key={tab.id}
            ref={(element) => {
              if (element) buttons.current.set(tab.id, element);
              else buttons.current.delete(tab.id);
            }}
            type="button"
            role="tab"
            className="tab"
            id={tabDomId(tab.id)}
            aria-selected={isSelected}
            aria-controls={panelDomId(tab.id)}
            tabIndex={isSelected ? 0 : -1}
            onClick={() => onSelect(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export interface TabPanelProps extends HTMLAttributes<HTMLDivElement> {
  tabId: string;
  children: ReactNode;
}

/** div[role=tabpanel]; невыбранная панель скрывается атрибутом hidden */
export function TabPanel({ tabId, children, ...rest }: TabPanelProps) {
  return (
    <div {...rest} role="tabpanel" id={panelDomId(tabId)} aria-labelledby={tabDomId(tabId)} tabIndex={0}>
      {children}
    </div>
  );
}
