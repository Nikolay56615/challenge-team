import { useId } from 'react';
import type { Route } from '../api/types';
import { typo } from '../format';

export interface RouteBlockProps {
  route: Route;
}

/** section.route: заголовок h2 в стиле kv__label и нумерованный список шагов */
export function RouteBlock({ route }: RouteBlockProps) {
  const headingId = useId();
  if (route.steps.length === 0) return null;
  return (
    <section className="route" aria-labelledby={headingId}>
      <h2 id={headingId} className="kv__label">
        {typo(route.title)}
      </h2>
      <ol>
        {route.steps.map((step) => (
          <li key={step.material_id}>{typo(step.title)}</li>
        ))}
      </ol>
    </section>
  );
}
