import {
  linkifyWorkspacePaths,
  toMyfilesParams,
  toWorkspaceRel,
} from "../src/pages/Chat/workspaceLinks";

let failed = 0;
const eq = (name: string, got: string, want: string) => {
  if (got !== want) {
    failed += 1;
    console.log(`FAIL ${name}\n  got  : ${got}\n  want : ${want}`);
  } else {
    console.log(`ok   ${name}`);
  }
};

// 1) 绝对路径 → 链接
eq(
  "abs path linkified",
  linkifyWorkspacePaths("已生成 /app/working/workspaces/alice/files/plan.md 请查收"),
  "已生成 [plan.md](files/plan.md) 请查收",
);

// 2) 相对路径 → 链接
eq(
  "rel path linkified",
  linkifyWorkspacePaths("报告在 files/入市方案.md 里"),
  "报告在 [入市方案.md](files/入市方案.md) 里",
);

// 3) 代码块里的路径是示例，不动
const fenced = "用法：\n```bash\ncat files/plan.md\n```\n完成";
eq("fenced untouched", linkifyWorkspacePaths(fenced), fenced);

// 4) 行内代码不动
eq("inline code untouched", linkifyWorkspacePaths("见 `files/plan.md`"), "见 `files/plan.md`");

// 5) 已有链接不套娃
eq("existing link untouched", linkifyWorkspacePaths("[方案](files/plan.md)"), "[方案](files/plan.md)");

// 6) http 链接不动
const url = "参考 https://example.com/files/plan.md 与 [x](https://a.b/c.md)";
eq("http untouched", linkifyWorkspacePaths(url), url);

// 7) 幂等
const once = linkifyWorkspacePaths("见 files/a.md");
eq("idempotent", linkifyWorkspacePaths(once), once);

// 8) 普通文本不碰
eq("plain text untouched", linkifyWorkspacePaths("今天天气好，files 目录"), "今天天气好，files 目录");

// 9) 尾部标点剥离
eq(
  "trailing punctuation stripped",
  linkifyWorkspacePaths("见 files/a.md。"),
  "见 [a.md](files/a.md)。",
);

// 10) 路径换算
eq(
  "myfiles params files",
  JSON.stringify(toMyfilesParams("files/a/b.md")),
  JSON.stringify({ category: "files", path: "a/b.md" }),
);
eq(
  "myfiles params media",
  JSON.stringify(toMyfilesParams("media/pic.png")),
  JSON.stringify({ category: "media", path: "pic.png" }),
);

// 11) 链接形态归一
eq("toWorkspaceRel preview url", toWorkspaceRel("/api/files/preview/files%2Fplan.md"), "files/plan.md");
eq("toWorkspaceRel abs", toWorkspaceRel("/app/working/workspaces/alice/files/x.docx"), "files/x.docx");
eq("toWorkspaceRel external", toWorkspaceRel("https://a.b/c.md"), "");

console.log(failed ? `\n${failed} FAILED` : "\nall green");
process.exit(failed ? 1 : 0);
