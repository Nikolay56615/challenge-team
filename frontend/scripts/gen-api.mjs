// Типы TypeScript из схемы OpenAPI бэкенда (кандидат W10).
// Вход — src/api/openapi.json (npm run fetch:api), выход — src/api/schema.gen.ts. Файл не правится руками:
// совместимость с ручными типами src/api/types.ts проверяет при сборке src/api/contract.ts.
//
//   npm run gen:api            — записать src/api/schema.gen.ts
//   npm run gen:api -- --check — сравнить с записанным файлом, код выхода 1 при расхождении (шаг CI)
//
// Генератор — json-schema-to-typescript: схемы компонентов OpenAPI 3.1 совпадают с JSON Schema 2020-12.
// openapi-typescript не подошёл: версия 7 требует typescript 5, версия 6 тянет undici с уязвимостями.
import { readFileSync, writeFileSync } from 'node:fs';
import { compile } from 'json-schema-to-typescript';

const source = new URL('../src/api/openapi.json', import.meta.url);
const target = new URL('../src/api/schema.gen.ts', import.meta.url);
const check = process.argv.includes('--check');

const doc = JSON.parse(readFileSync(source, 'utf8'));
const schemas = doc.components?.schemas;
if (!schemas || typeof schemas !== 'object') {
  console.error('В src/api/openapi.json нет components.schemas');
  process.exit(1);
}

/**
 * Подписи title у свойств FastAPI пишет для документации. json-schema-to-typescript превратил бы каждую
 * в отдельный тип вроде `type Rank = number`, поэтому title остаётся только у самих схем компонентов.
 */
function stripTitles(node, keepTitle) {
  if (Array.isArray(node)) return node.map((child) => stripTitles(child, false));
  if (!node || typeof node !== 'object') return node;
  const out = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === 'title' && !keepTitle) continue;
    out[key] = key === 'properties'
      ? Object.fromEntries(Object.entries(value).map(([name, child]) => [name, stripTitles(child, false)]))
      : stripTitles(value, false);
  }
  return out;
}

const names = Object.keys(schemas).sort();
const components = Object.fromEntries(names.map((name) => [name, { ...stripTitles(schemas[name], true), title: name }]));
// Корень перечисляет все схемы компонентов: каждая становится экспортированным интерфейсом со своим именем
const root = {
  title: 'ApiSchemas',
  description: 'Все схемы компонентов OpenAPI по именам',
  type: 'object',
  properties: Object.fromEntries(names.map((name) => [name, { $ref: `#/components/schemas/${name}` }])),
  required: names,
  additionalProperties: false,
  components: { schemas: components },
};

const banner = [
  '/* eslint-disable */',
  '// Создано scripts/gen-api.mjs из src/api/openapi.json. Не править вручную: npm run gen:api.',
  `// Схема: OpenAPI ${doc.openapi}, ${doc.info?.title ?? 'API'} ${doc.info?.version ?? ''}`.trimEnd(),
].join('\n');

const output = await compile(root, 'ApiSchemas', {
  bannerComment: banner,
  // Ответы FastAPI не пишут additionalProperties: без этого у каждого интерфейса был бы индекс [k: string]
  additionalProperties: false,
  // maxItems: 200 у истории иначе дал бы объединение кортежей длиной до 200
  ignoreMinAndMaxItems: true,
  unknownAny: true,
  // Тип значения словаря без | undefined, как Record<string, number> в src/api/types.ts
  strictIndexSignatures: false,
  format: true,
  style: { singleQuote: true, printWidth: 120, trailingComma: 'all', endOfLine: 'lf' },
});

if (check) {
  let current;
  try {
    current = readFileSync(target, 'utf8');
  } catch {
    current = '';
  }
  if (current !== output) {
    console.error('src/api/schema.gen.ts расходится с src/api/openapi.json: выполните npm run gen:api');
    process.exit(1);
  }
  console.log(`src/api/schema.gen.ts совпадает со схемой, схем компонентов: ${names.length}`);
} else {
  writeFileSync(target, output, 'utf8');
  console.log(`src/api/schema.gen.ts из src/api/openapi.json, схем компонентов: ${names.length}`);
}
