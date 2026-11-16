import { useEffect, useState, type HTMLAttributes } from 'react';
import { cx } from './cx';

/**
 * Задержка появления скелетонов, мс. Ответ быстрее неё приходит без мелькания
 * заглушек; о загрузке сразу сообщает StatusLine.
 */
export const SKELETON_DELAY_MS = 400;

/**
 * true, когда active держится дольше delay мс; вместе с active сразу становится false.
 * Экран так решает, когда прежнюю выдачу сменяют скелетоны (docs/ui-kit.md, раздел 3, Skeleton и Stale).
 */
export function useDelayedFlag(active: boolean, delay: number): boolean {
  const [late, setLate] = useState(false);
  // Когда ожидания нет, флаг сбрасывается при рендере, а не в эффекте: следующее ожидание начнётся с false.
  // Хук возвращает то же значение, что при сбросе в эффекте, но без второй фиксации
  if (late && (!active || delay <= 0)) setLate(false);
  useEffect(() => {
    if (!active || delay <= 0) return;
    const timer = setTimeout(() => {
      setLate(true);
    }, delay);
    return () => {
      clearTimeout(timer);
    };
  }, [active, delay]);
  return active && (delay <= 0 || late);
}

/** Атрибуты применяются к каждому скелетону; id не принимается: элементов несколько */
export interface SkeletonProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children' | 'id'> {
  count?: number;
  /** Через сколько миллисекунд после монтирования показать скелетоны; 0 — сразу */
  delay?: number;
}

/** div.skeleton: статичный градиент; о загрузке сообщает StatusLine. До истечения delay ничего не выводит. */
export function Skeleton({ count = 1, delay = 0, className, ...rest }: SkeletonProps) {
  const visible = useDelayedFlag(true, delay);
  if (!visible) return null;
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} {...rest} className={cx('skeleton', className)} aria-hidden="true" />
      ))}
    </>
  );
}
