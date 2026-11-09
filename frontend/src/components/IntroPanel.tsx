import { useEffect, useId, useRef, useState } from 'react';
import type { StageCode } from '../api/types';
import { Button, Panel } from '../kit';

const EXAMPLES = [
  { task: 'Запустить первую рекламу', detail: 'Найти первых клиентов для своего дела', image: 'marketing' },
  { task: 'Какой налоговый режим выбрать', detail: 'Сравнить налоговые режимы для ИП', image: 'finance' },
  { task: 'Как делегировать задачи', detail: 'Понять, кто за что отвечает', image: 'business' },
];

const STAGES = [
  { value: 'idea', label: 'Планирую открыть дело' },
  { value: 'start', label: 'Недавно начал бизнес' },
  { value: 'growth', label: 'Хочу развивать бизнес' },
] as const satisfies readonly { value: StageCode; label: string }[];

interface IntroPanelProps {
  id?: string;
  disabled?: boolean;
  onExample: (task: string, stage: StageCode | null) => void;
}

export function IntroPanel({ id, disabled = false, onExample }: IntroPanelProps) {
  const [task, setTask] = useState<string | null>(null);
  const generatedId = useId();
  const headingId = id ?? generatedId;
  const heading = useRef<HTMLHeadingElement>(null);
  const moved = useRef(false);
  useEffect(() => {
    if (moved.current) heading.current?.focus();
  }, [task]);

  const changeStep = (value: string | null) => {
    moved.current = true;
    setTask(value);
  };

  return (
    <Panel labelledBy={headingId}>
      <div>
        <p className="note">{task === null ? 'Шаг 1\u00a0из 2' : 'Шаг 2\u00a0из 2'}</p>
        <h2 id={headingId} ref={heading} tabIndex={-1} className="h2">
          {task === null ? 'Что хотите сделать?' : 'На каком этапе ваш бизнес?'}
        </h2>
      </div>
      {task === null ? (
        <>
          <ul className="intro__examples">
            {EXAMPLES.map(({ task: example, detail, image }) => (
              <li key={example}>
                <Button className="intro__example" disabled={disabled} onClick={() => { changeStep(example); }}>
                  <img src={`/course-topics/${image}.jpg`} alt="" width="96" height="64" />
                  <span>
                    <strong>{example}</strong>
                    <span className="hint">{detail}</span>
                  </span>
                </Button>
              </li>
            ))}
          </ul>
          <Button variant="link" disabled={disabled} onClick={() => { onExample('', null); }}>
            Показать материалы для начала
          </Button>
        </>
      ) : (
        <>
          <p className="hint">{task}</p>
          <ul className="intro__examples">
            {STAGES.map(({ value, label }) => (
              <li key={value}>
                <Button disabled={disabled} onClick={() => { onExample(task, value); }}>
                  {label}
                </Button>
              </li>
            ))}
          </ul>
          <div className="actions">
            <Button variant="link" disabled={disabled} onClick={() => { changeStep(null); }}>Назад</Button>
            <Button variant="link" disabled={disabled} onClick={() => { onExample(task, null); }}>
              Пропустить уточнение
            </Button>
          </div>
        </>
      )}
    </Panel>
  );
}
