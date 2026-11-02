import { chromium } from 'playwright';
import fs from 'fs';

const token = fs.readFileSync('/tmp/tok_prod.txt', 'utf8').trim();
const base = 'http://127.0.0.1:4890';
const out = [];
const issues = [];

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
page.on('console', (m) => {
  if (m.type() === 'error') issues.push('前端报错: ' + m.text().slice(0, 200));
});
page.on('pageerror', (e) => issues.push('页面异常: ' + String(e).slice(0, 200)));
page.on('response', async (r) => {
  const u = r.url();
  if (r.status() >= 400 && u.includes('/api/')) issues.push(`接口 ${r.status()} ${u.replace(base, '')}`);
});

await page.goto(base + '/', { waitUntil: 'domcontentloaded' });
await page.evaluate(([t]) => {
  sessionStorage.setItem('coapis_auth_token', t);
  sessionStorage.setItem('coapis_current_username', 'admin');
}, [token]);
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(3000);

// 取真实知识库编号
const kbList = await page.evaluate(async () => {
  const r = await fetch('/api/knowledge/bases', { headers: { Authorization: 'Bearer ' + sessionStorage.getItem('coapis_auth_token') } });
  return await r.json();
});
const kbItems = kbList.bases || kbList.items || kbList;
const kbId = kbItems[0].kb_id;
console.log('探针知识库:', kbId, kbItems[0].name);

const targets = [
  ['聊天首页', base + '/'],
  ['知识库列表', base + '/ent/knowledge-bases'],
  ['知识库详情', base + '/ent/knowledge-bases/' + kbId],
  ['知识库文件', base + '/ent/knowledge-bases/' + kbId + '/files'],
  ['场景绑定', base + '/ent/scene-kb-bindings'],
  ['消息管理', base + '/ent/messages'],
  ['用户管理', base + '/admin/users'],
  ['标签管理', base + '/admin/tags'],
  ['场景管理', base + '/admin/scenes'],
];

for (const [label, url] of targets) {
  const before = issues.length;
  await page.goto(url, { waitUntil: 'networkidle', timeout: 25000 }).catch((e) => issues.push('导航失败 ' + label + ' ' + String(e).slice(0, 80)));
  await page.waitForTimeout(2200);
  const text = await page.locator('body').innerText().catch(() => '');
  const h = await page.locator('h1,h2,h3,h4').first().innerText().catch(() => '无标题');
  out.push(`${label}: 文字量=${text.length} 首标题=${JSON.stringify(h.slice(0, 24))} 本页新增问题=${issues.length - before}`);
  await page.screenshot({ path: `/tmp/prod_${label.replace(/[^\w]/g, '')}.png` });
}

await browser.close();
console.log('=== 页面 ===\n' + out.join('\n'));
const uniq = [...new Set(issues)];
console.log('=== 问题清单 ===\n' + (uniq.join('\n') || '无'));
console.log('合计=' + uniq.length);
