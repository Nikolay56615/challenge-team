import type { Ref } from 'react';
import type { Clarification, TopicCode } from '../api/types';
import { Banner, Button, ChipGroup } from '../kit';

export const ERROR_TITLE = 'Не удалось получить подборку';
export const NETWORK_ERROR_TEXT = 'Сервис не ответил. Введённые данные сохранены — повторите запрос.';

export type StateBannerProps =
  | {
      kind: 'clarification';
      clarification: Clarification;
      topic: TopicCode | null;
      onChooseTopic(topic: TopicCode): void;
      onDismiss(): void;
      disabled?: boolean;
    }
  | {
      kind: 'error';
      /** Текст ответа сервиса или NETWORK_ERROR_TEXT */
      message: string;
      onRetry(): void;
      /** «Повторить» принимает фокус, если повтор из области выдачи снова не удался */
      retryRef?: Ref<HTMLButtonElement>;
    };

/** Уточнение при слабом совпадении или ошибка запроса с «Повторить» */
export function StateBanner(props: StateBannerProps) {
  if (props.kind === 'error') {
    return (
      <Banner
        tone="error"
        title={ERROR_TITLE}
        actions={
          <Button ref={props.retryRef} variant="primary" size="sm" onClick={props.onRetry}>
            Повторить
          </Button>
        }
      >
        {props.message}
      </Banner>
    );
  }

  const { clarification, topic, onChooseTopic, onDismiss, disabled = false } = props;
  return (
    <Banner
      tone="info"
      title={clarification.question}
      actions={
        <>
          {clarification.options.length > 0 ? (
            <ChipGroup
              legend="Тема"
              legendHidden
              name="clarification-topic"
              options={clarification.options}
              value={topic}
              onChange={(value) => {
                if (value) onChooseTopic(value);
              }}
              allowDeselect={false}
              activation="manual"
              disabled={disabled}
            />
          ) : null}
          <Button variant="link" onClick={onDismiss} disabled={disabled}>
            Оставить как есть
          </Button>
        </>
      }
    >
      {clarification.text}
    </Banner>
  );
}
