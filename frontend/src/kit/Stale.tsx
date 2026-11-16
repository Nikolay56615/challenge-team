import type { ReactNode } from 'react';

export interface StaleProps {
  /** Идёт запрос, задержка скелетонов ещё не истекла */
  active: boolean;
  children?: ReactNode;
}

/**
 * Прежнее содержимое во время загрузки, пока не появились скелетоны.
 * div.stale не создаёт своего блока (display: contents): сетка колонки и высота страницы не меняются,
 * поэтому быстрый ответ не схлопывает колонку. Атрибут inert убирает содержимое из обхода Tab и дерева
 * доступности, о загрузке говорит StatusLine. Приглушение начинается через 150 мс: при быстром ответе его не видно.
 * Без active или без содержимого обёртки нет.
 */
export function Stale({ active, children }: StaleProps) {
  if (!active || children === null || children === undefined || children === false) return <>{children}</>;
  return (
    <div className="stale" inert>
      {children}
    </div>
  );
}
