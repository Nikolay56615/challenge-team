// ESLint интерфейса (кандидат W09): typescript-eslint strictTypeChecked и stylisticTypeChecked с проверкой
// типов, правила хуков React. Запуск: npm run lint; предупреждения тоже ломают проверку (--max-warnings 0).
//
// Один пакет TypeScript 6.0 и для сборки (tsc), и для правил с типами: typescript-eslint 8 поддерживает
// TypeScript ниже 6.1.
import js from '@eslint/js';
import { defineConfig, globalIgnores } from 'eslint/config';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default defineConfig(
  // schema.gen.ts создаёт npm run gen:api, совпадение со схемой проверяет gen:api -- --check
  globalIgnores(['dist/', '.screenshots/', 'src/api/schema.gen.ts']),
  {
    linterOptions: { reportUnusedDisableDirectives: 'error', reportUnusedInlineConfigs: 'error' },
  },
  js.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
  },
  // Скрипты и тесты Node.js — модули JavaScript без проекта TypeScript: правила с типами к ним не применяются
  {
    files: ['**/*.{js,mjs}'],
    languageOptions: { globals: globals.node },
  },
);
