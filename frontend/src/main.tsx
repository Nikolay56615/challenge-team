import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/kit.css';
import './styles/app.css';
import { App } from './App';

const container = document.getElementById('root');
if (!container) throw new Error('Не найден контейнер #root');

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Только в режиме разработки: в production import.meta.env.DEV равен false, ветка и модуль web-vitals
// в сборку не попадают (кандидат W04)
if (import.meta.env.DEV) {
  void import('./dev/vitals').then(({ reportWebVitals }) => {
    reportWebVitals();
  });
}
