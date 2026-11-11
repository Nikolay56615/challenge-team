import { useId } from 'react';
import { Panel } from '../kit';

/** Начальное состояние: «Что вы получите» и примеры задач */
export function IntroPanel() {
  const headingId = useId();
  return (
    <Panel labelledBy={headingId}>
      <h2 id={headingId} className="h2">
        Что вы получите
      </h2>
      <ul className="list">
        <li>Материалы в порядке пользы для вашей задачи.</li>
        <li>Причину выбора и доступные действия по каждому материалу.</li>
        <li>Формат, условия доступа и длительность, если она известна.</li>
      </ul>
      <p className="hint">
        Примеры задач: «Запустить первую рекламу», «Какой налоговый режим выбрать», «Навести порядок в задачах».
      </p>
    </Panel>
  );
}
