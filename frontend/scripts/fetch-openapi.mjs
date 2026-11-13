// Снимок схемы API для генерации типов (кандидат W10). Схему отдаёт запущенный бэкенд.
// Запуск из app/frontend: npm run fetch:api -- http://127.0.0.1:8000/openapi.json
// Файл src/api/openapi.json хранится в репозитории: из него npm run gen:api строит src/api/schema.gen.ts.
import { writeFileSync } from 'node:fs';

const url = process.argv[2] ?? 'http://127.0.0.1:8000/openapi.json';
const target = new URL('../src/api/openapi.json', import.meta.url);

const response = await fetch(url, { headers: { Accept: 'application/json' } });
if (!response.ok) {
  console.error(`${url}: HTTP ${response.status}`);
  process.exit(1);
}
const doc = await response.json();
if (typeof doc?.openapi !== 'string' || !doc.components?.schemas) {
  console.error(`${url}: ответ не похож на схему OpenAPI`);
  process.exit(1);
}
writeFileSync(target, `${JSON.stringify(doc, null, 2)}\n`, 'utf8');
console.log(`Схема OpenAPI ${doc.openapi} → src/api/openapi.json; схем компонентов: ${Object.keys(doc.components.schemas).length}, путей: ${Object.keys(doc.paths ?? {}).length}`);
