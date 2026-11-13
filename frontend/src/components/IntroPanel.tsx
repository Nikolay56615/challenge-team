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
        <li>Материалы в&nbsp;порядке пользы для вашей задачи, а&nbsp;не по популярности.</li>
        <li>Причину выбора и&nbsp;следующий шаг по каждому материалу.</li>
        <li>
          Пометку «бесплатно» или «платно». Для платного&nbsp;— краткую пользу и&nbsp;переход на его страницу, если ссылка
          разрешена.
        </li>
      </ul>
      <p className="hint">
        Примеры задач: «Запустить первую рекламу», «Какой налоговый режим выбрать», «Навести порядок в&nbsp;задачах».
      </p>
    </Panel>
  );
}
