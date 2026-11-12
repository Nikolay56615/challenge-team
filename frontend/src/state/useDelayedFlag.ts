import { useEffect, useState } from 'react';

/**
 * true не раньше чем через delay мс после того, как value стало true; сбрасывается сразу.
 * Прячет скелетон на быстрых ответах: загрузка короче delay не успевает показаться.
 */
export function useDelayedFlag(value: boolean, delay = 200): boolean {
  const [elapsed, setElapsed] = useState(false);

  useEffect(() => {
    if (!value) {
      setElapsed(false);
      return;
    }
    const timer = setTimeout(() => setElapsed(true), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return value && elapsed;
}
