/**
 * B0 契约锁 · i18n 键棘轮（ratchet）
 * ---------------------------------------------------------------------------
 * 背景：v1.2.27 那批中文显示修复里，四语言键全靠人工补齐，补漏了没人知道
 * （实测 `ja.json` 比 `zh.json` 少 609 个键，线上看不出问题是因为
 * `i18n.ts` 里 `fallbackLng: "zh"` 兜着）。
 *
 * 这个测试不逼你补全翻译（那不现实），它只禁止**变差**：
 *  - 缺键数只许降不许升（棘轮）；
 *  - 新增键必须同时进 zh 与 en —— 中文是主语言，英文是通用语，
 *    这两份不齐，界面上就会出现"切了语言还是中文"或"直接吐 key 字面量"。
 *
 * 基线怎么更新：跑 `npm run test:run`，失败信息里有实际值。确认是变好了
 * 就把 BASELINE 调成新的实际值，并在 commit 说明里写清为什么变好。
 * 变差不许动基线 —— 那是要修的，不是要记录的。
 */
import { describe, expect, it } from "vitest";

import zh from "../../locales/zh.json";
import en from "../../locales/en.json";
import ja from "../../locales/ja.json";
import ru from "../../locales/ru.json";

const LOCALES = { zh, en, ja, ru } as const;
type LocaleName = keyof typeof LOCALES;
type OtherLocale = Exclude<LocaleName, "zh">;

/** 以 zh 为基准的「缺失键数」基线（2026-11-13 实测锁定） */
const BASELINE_MISSING: Record<OtherLocale, number> = {
  en: 51,
  ja: 609,
  ru: 594,
};

/** 相对 zh 的「多余键数」基线（历史遗留，同样只许降不许升） */
const BASELINE_EXTRA: Record<OtherLocale, number> = {
  en: 25,
  ja: 5,
  ru: 5,
};

function flattenKeys(node: unknown, prefix = ""): string[] {
  if (node === null || typeof node !== "object") return [];
  const out: string[] = [];
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const full = prefix ? `${prefix}.${key}` : key;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      out.push(...flattenKeys(value, full));
    } else {
      out.push(full);
    }
  }
  return out;
}

const keySets = Object.fromEntries(
  Object.entries(LOCALES).map(([name, value]) => [
    name,
    new Set(flattenKeys(value)),
  ]),
) as Record<LocaleName, Set<string>>;

function missingIn(base: Set<string>, other: Set<string>): string[] {
  return [...base].filter((k) => !other.has(k));
}

describe("i18n 键棘轮 —— 缺键只许降不许升", () => {
  it("四份语言文件都解析成对象，且键量在千级（防「空文件混进来」）", () => {
    for (const name of Object.keys(LOCALES) as LocaleName[]) {
      expect(LOCALES[name], `${name}.json 应为对象`).toBeTypeOf("object");
      expect(keySets[name].size, `${name}.json 键数异常偏低`).toBeGreaterThan(
        1000,
      );
    }
  });

  it.each(Object.keys(BASELINE_MISSING) as OtherLocale[])(
    "%s 相对 zh 的缺键数不得超过基线（棘轮）",
    (name) => {
      const actual = missingIn(keySets.zh, keySets[name]).length;
      const baseline = BASELINE_MISSING[name];
      expect(
        actual,
        `${name} 缺键 ${actual} > 基线 ${baseline}：新增的键要补进 ${name}.json；` +
          `若确属变好（本次修复补了翻译），把基线调成 ${actual} 并在 commit 里说明。`,
      ).toBeLessThanOrEqual(baseline);
    },
  );

  it.each(Object.keys(BASELINE_EXTRA) as OtherLocale[])(
    "%s 相对 zh 的多余键数不得超过基线（防孤儿键堆积）",
    (name) => {
      const extra = missingIn(keySets[name], keySets.zh).length;
      expect(extra).toBeLessThanOrEqual(BASELINE_EXTRA[name]);
    },
  );

  it("zh 与 en 必须保持同步：新增键不许只进 zh（中文加了英文没加）", () => {
    const onlyZh = missingIn(keySets.zh, keySets.en);
    const onlyEn = missingIn(keySets.en, keySets.zh);
    // 基线口径：zh 缺 en 侧 51 条、en 多 zh 侧 25 条，是历史欠账；
    // 两个方向都不许再涨，否则中英双语会越走越远。
    expect(onlyZh.length).toBeLessThanOrEqual(BASELINE_MISSING.en);
    expect(onlyEn.length).toBeLessThanOrEqual(BASELINE_EXTRA.en);
  });

  it("叶子值不许为空串（空串会让界面出现「空白标签」，比吐 key 更难查）", () => {
    const offenders: string[] = [];
    for (const name of Object.keys(LOCALES) as LocaleName[]) {
      const walk = (node: unknown, prefix = "") => {
        if (node === null || typeof node !== "object") return;
        for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
          const full = prefix ? `${prefix}.${key}` : key;
          if (value !== null && typeof value === "object" && !Array.isArray(value)) {
            walk(value, full);
          } else if (value === "") {
            offenders.push(`${name}:${full}`);
          }
        }
      };
      walk(LOCALES[name]);
    }
    expect(
      offenders.slice(0, 20),
      `空串叶子值（共 ${offenders.length} 条，最多列 20 条）`,
    ).toEqual([]);
  });

  it("聊天三组件用到的键四语言齐备（v1.2.27 中文显示那批的承重墙）", () => {
    // 这些键来自 EnhancedToolCallCard / CoApisChatResourceBar / SimplifiedResponseCard
    // 的真实调用点（grep 出来的，不是猜的）。缺一个，界面上就会出现
    // 「切了语言还是中文」或直接吐 key 字面量 —— 正是小蜜蜂报的那类问题。
    const required = [
      "chat.preview.convertTo",
      "chat.preview.downloadOriginal",
      "chat.resources.barTitleRound",
      "chat.resources.download",
      "chat.resources.groupProduced",
      "chat.resources.groupReference",
      "chat.resources.locateMessage",
      "chat.resources.preview",
      "chat.resources.produced",
      "chat.resources.reference",
      "chat.resources.showRest",
      "chat.resources.statusMissing",
      "chat.resources.toggleFilterTip",
      "chat.resources.viewAllSession",
      "chat.tool.aborted",
      "chat.tool.failed",
      "chat.tool.output",
      "chat.tool.params",
      "chat.tool.running",
      "chat.tool.truncated",
    ];
    for (const name of Object.keys(LOCALES) as LocaleName[]) {
      for (const key of required) {
        expect(
          keySets[name].has(key),
          `${name}.json 缺 ${key} —— 它会退回中文，或直接把 key 吐到界面上`,
        ).toBe(true);
      }
    }
  });
});
