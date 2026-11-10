import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// Бэкенд FastAPI при локальной разработке (PLAN.md, 4.5)
const API_TARGET = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  // Две страницы: приложение и витрина UI-кита. Пути считаются от корня проекта.
  input: {
    main: 'index.html',
    kit: 'kit.html',
  },
  server: {
    proxy: { '/api': API_TARGET },
  },
  preview: {
    proxy: { '/api': API_TARGET },
  },
});
