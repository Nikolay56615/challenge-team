// Web Vitals в режиме разработки. Значения пишутся
// в консоль браузера и никуда не отправляются: это лабораторные данные одной машины, а не полевые.
// Модуль загружается динамическим импортом под import.meta.env.DEV и в сборку не попадает.
import { onCLS, onINP, onLCP, type Metric } from 'web-vitals';

function log(metric: Metric): void {
  // CLS — безразмерная доля, LCP и INP — миллисекунды
  const value = metric.name === 'CLS' ? metric.value.toFixed(4) : `${String(Math.round(metric.value))} мс`;
  console.info(`[web-vitals] ${metric.name} ${value} (${metric.rating})`);
}

/** Подписка на LCP, CLS и INP; reportAllChanges — значение пишется при каждом изменении, а не при уходе со страницы */
export function reportWebVitals(): void {
  onLCP(log, { reportAllChanges: true });
  onCLS(log, { reportAllChanges: true });
  onINP(log, { reportAllChanges: true });
}
