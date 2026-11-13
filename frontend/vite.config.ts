import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  // Бэкенд FastAPI при локальной разработке (docs/plan.md, 4.5). Другой адрес задаёт переменная окружения
  // API_TARGET, например API_TARGET=http://127.0.0.1:8080: loadEnv читает переменные с префиксом API_
  const env = loadEnv(mode, '.', 'API_');
  // eslint-disable-next-line @typescript-eslint/prefer-nullish-coalescing -- пустая API_TARGET= тоже значит адрес по умолчанию
  const API_TARGET = env.API_TARGET || 'http://127.0.0.1:8000';

  return {
    plugins: [react()],
    // Две страницы: приложение и витрина UI-кита. Пути считаются от корня проекта.
    input: {
      main: 'index.html',
      kit: 'kit.html',
    },
    build: {
      // Порог предупреждения о размере чанка ужесточён с 500 до 250 КБ: случайный импорт тяжёлой
      // библиотеки виден в выводе сборки (кандидат W14)
      chunkSizeWarningLimit: 250,
    },
    server: {
      proxy: { '/api': API_TARGET },
    },
    preview: {
      proxy: { '/api': API_TARGET },
    },
  };
});
