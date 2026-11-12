// 一次性检查：列出仓库根 config.json 里看起来像密钥的键（值打码），用于决定 .gitignore
import fs from 'node:fs';

const raw = fs.readFileSync('config.json', 'utf8');
const data = JSON.parse(raw);
const SECRET_RE = /key|token|secret|password|credential/i;
const rows = [];

for (const [k, v] of Object.entries(data)) {
  if (SECRET_RE.test(k)) {
    const s = String(v ?? '');
    rows.push(`${k} = ${s ? s.slice(0, 4) + '***(' + s.length + ' chars)' : '(empty)'}`);
  } else {
    rows.push(`${k} = ${JSON.stringify(v)}`);
  }
}

console.log(rows.join('\n'));
