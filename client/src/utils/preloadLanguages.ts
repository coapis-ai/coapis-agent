/**
 * 预加载 react-syntax-highlighter 语言包
 * 
 * 解决 @ant-design/x CodeHighlighter 动态导入失败的问题
 * 
 * 原因：
 * - @agentscope-ai/chat 使用 CodeHighlighter 的默认 prismLightMode=true
 * - prismLightMode=true 会动态 import() 语言包
 * - Vite 生产构建无法静态分析动态路径，导致模块加载失败
 * 
 * 解决方案：
 * - 静态导入常用语言包（使用 vite-plugin-static-import 或手动导入）
 * - 注册到 PrismLight
 */

import { PrismLight } from 'react-syntax-highlighter';

// 静态导入常用语言包
// 注意：这里使用静态导入，确保 Vite 能正确打包
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c';
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup';
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff';
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker';
import nginx from 'react-syntax-highlighter/dist/esm/languages/prism/nginx';
import ini from 'react-syntax-highlighter/dist/esm/languages/prism/ini';
import toml from 'react-syntax-highlighter/dist/esm/languages/prism/toml';
import powershell from 'react-syntax-highlighter/dist/esm/languages/prism/powershell';

/**
 * 注册所有语言包到 PrismLight
 */
export function registerLanguages(): void {
  // 注册语言到 PrismLight
  PrismLight.registerLanguage('javascript', javascript);
  PrismLight.registerLanguage('typescript', typescript);
  PrismLight.registerLanguage('jsx', jsx);
  PrismLight.registerLanguage('tsx', tsx);
  PrismLight.registerLanguage('python', python);
  PrismLight.registerLanguage('bash', bash);
  PrismLight.registerLanguage('json', json);
  PrismLight.registerLanguage('css', css);
  PrismLight.registerLanguage('markdown', markdown);
  PrismLight.registerLanguage('yaml', yaml);
  PrismLight.registerLanguage('sql', sql);
  PrismLight.registerLanguage('java', java);
  PrismLight.registerLanguage('c', c);
  PrismLight.registerLanguage('cpp', cpp);
  PrismLight.registerLanguage('go', go);
  PrismLight.registerLanguage('rust', rust);
  PrismLight.registerLanguage('html', markup); // markup 包含 HTML
  PrismLight.registerLanguage('xml', markup);   // markup 也包含 XML
  PrismLight.registerLanguage('diff', diff);
  PrismLight.registerLanguage('docker', docker);
  PrismLight.registerLanguage('nginx', nginx);
  PrismLight.registerLanguage('ini', ini);
  PrismLight.registerLanguage('toml', toml);
  PrismLight.registerLanguage('powershell', powershell);
}

/**
 * 初始化语言包（应用启动时调用）
 */
export function initLanguages(): void {
  registerLanguages();
}
