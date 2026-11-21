/**
 * B0 契约锁 · 聊天执行区文案语气（2026-11-21 用户拍板「亲切版」）
 * ---------------------------------------------------------------------------
 * 背景：执行过程中界面直译状态枚举，读起来像后台日志——
 *   「深度思考」「执行计划」「执行中」「结果待补」「已放弃」……
 * 用户明确要人性化措辞，并选定了语气档位（亲切版）。
 *
 * 这个锁不检查语法，只禁止**机器腔回流**：只要这些词重新出现在
 * 聊天执行区的文案里，测试就红。改文案可以，把腔调改回去不行。
 *
 * 想放行新措辞：先跟用户确认语气档位，再改 BANNED，并在 commit 里写清依据。
 */
import { describe, expect, it } from "vitest";

import zh from "../../locales/zh.json";

/** 执行区禁用词：直译枚举、后台腔 */
const BANNED = [
  "深度思考",
  "执行计划",
  "执行中",
  "执行命令",
  "执行JS",
  "结果待补",
  "已放弃",
  "已中止",
];

/** 只锁执行区这三棵子树；管理后台的「加载失败」之类不在此列 */
const SCOPES = ["chat", "planBoard", "plan"];

type Json = Record<string, unknown>;

function collect(node: unknown, prefix: string, out: Array<[string, string]>) {
  if (node && typeof node === "object" && !Array.isArray(node)) {
    for (const [k, v] of Object.entries(node as Json)) {
      collect(v, `${prefix}.${k}`, out);
    }
  } else if (typeof node === "string") {
    out.push([prefix, node]);
  }
}

describe("聊天执行区文案语气锁（亲切版）", () => {
  const strings: Array<[string, string]> = [];
  for (const scope of SCOPES) {
    collect((zh as Json)[scope], scope, strings);
  }

  it("作用域非空：至少锁到 100 条文案，防止改名后静默空跑", () => {
    expect(strings.length).toBeGreaterThan(100);
  });

  it("不含机器腔禁用词", () => {
    const bad: string[] = [];
    for (const [key, value] of strings) {
      for (const word of BANNED) {
        if (value.includes(word)) {
          bad.push(`${key} = ${JSON.stringify(value)}  // 含禁用词「${word}」`);
        }
      }
    }
    expect(bad).toEqual([]);
  });

  it("关键状态词落在拍板的档位上", () => {
    // 只钉用户点名改过的几处，避免锁太死挡住正常微调
    expect(zh.chat.deepThinking).toBe("思考");
    expect(zh.planBoard.title).toBe("进度");
    expect(zh.planBoard.notStarted).toBe("还没开始");
    expect(zh.planBoard.resultMissing).toBe("结果还没记");
    expect(zh.chat.tool.running).toBe("正在处理");
    expect(zh.chat.tool.params).toBe("做什么");
    expect(zh.chat.tool.output).toBe("结果");
  });
});
