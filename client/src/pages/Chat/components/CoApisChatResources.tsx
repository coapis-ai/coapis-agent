import { useMemo, useState } from "react";
import { Button } from "antd";
import { FileTextOutlined, GlobalOutlined, DownloadOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { getApiToken, getApiUrl } from "../../../api/config";
import { toMyfilesParams } from "../workspaceLinks";

/**
 * 答案侧「产出卡 + 资源条」（B3）。
 *
 * 一次回答里智能体写了哪些文件、读了哪些网页，今天全埋在工具结果里。这里
 * 把它们分两层呈现：
 *
 *  ┌ 产出卡（producer）：本会话**写出来**的文件，直接给可点链接——
 *  │   「预览」开右侧抽屉看正文，「下载」走工作区作用域端点。
 *  │   用户不用再去「我的空间」里手动找文件。
 *  └ 资源条（reference）：本会话**引用过**的文件与网页，默认折叠，
 *      标题 + 链接一行一条；网页新窗口打开，文件走预览。
 *
 * 数据来自 completed 响应事件上的 `resources`（后端 B1 采集器），形状见
 * `normalize`。坏了不渲染，绝不阻塞消息。
 */

export interface LiveResource {
  kind: string;
  ref?: string;
  path?: string;
  title?: string;
  role?: string;
  source?: string;
}

interface Props {
  resources?: LiveResource[];
  onPreview?: (target: { path: string; title?: string }) => void;
}

const normalize = (raw?: LiveResource[]) => {
  const out: Array<{
    kind: "file" | "web";
    path: string;
    title: string;
    role: "producer" | "reference";
  }> = [];
  const seen = new Set<string>();
  for (const r of raw || []) {
    const kind = r?.kind === "web" ? "web" : r?.kind === "file" ? "file" : null;
    const path = (r?.ref || r?.path || "").trim();
    if (!kind || !path) continue;
    const key = `${kind}::${path}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      kind,
      path,
      title: (r?.title || (kind === "file" ? path.split("/").pop() : path)) as string,
      role: r?.role === "producer" ? "producer" : "reference",
    });
  }
  return out;
};

const fileDownloadUrl = (path: string) => {
  // 台账给的是工作区相对路径（files/x.md），myfiles 要的是分类内路径（x.md）
  const { category, path: rel } = toMyfilesParams(path);
  return getApiUrl(
    `/myfiles/download?path=${encodeURIComponent(rel)}&category=${encodeURIComponent(
      category,
    )}&token=${encodeURIComponent(getApiToken())}`,
  );
};

export default function CoApisChatResources({ resources, onPreview }: Props) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const items = useMemo(() => normalize(resources), [resources]);
  const producers = useMemo(
    () => items.filter((i) => i.role === "producer" && i.kind === "file"),
    [items],
  );
  const references = useMemo(
    () => items.filter((i) => !(i.role === "producer" && i.kind === "file")),
    [items],
  );
  const shownRefs = expanded ? references : references.slice(0, 5);

  if (items.length === 0) return null;

  return (
    <div
      style={{
        marginTop: 10,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        maxWidth: "100%",
      }}
    >
      {producers.length > 0 && (
        <div
          style={{
            border: "1px solid var(--coapis-border, #e8e8e8)",
            borderRadius: 10,
            padding: "10px 12px",
            background: "var(--coapis-card-bg, #fafafa)",
          }}
        >
          <div style={{ fontSize: 12, opacity: 0.72, marginBottom: 6 }}>
            {t("chat.resources.producedFiles", "本会话产出文件")}
          </div>
          {producers.map((p) => (
            <div
              key={`p-${p.path}`}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                minWidth: 0,
                padding: "2px 0",
              }}
            >
              <FileTextOutlined style={{ flexShrink: 0 }} />
              <span
                title={p.path}
                style={{
                  flex: "1 1 auto",
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  fontSize: 13,
                }}
              >
                {p.title}
              </span>
              {onPreview && (
                <Button
                  size="small"
                  type="link"
                  style={{ flexShrink: 0 }}
                  onClick={() => onPreview({ path: p.path, title: p.title })}
                >
                  {t("chat.resources.preview", "预览")}
                </Button>
              )}
              <Button
                size="small"
                type="link"
                icon={<DownloadOutlined />}
                style={{ flexShrink: 0 }}
                href={fileDownloadUrl(p.path)}
              >
                {t("chat.resources.download", "下载")}
              </Button>
            </div>
          ))}
        </div>
      )}

      {references.length > 0 && (
        <div style={{ fontSize: 12 }}>
          <div style={{ opacity: 0.72, marginBottom: 4 }}>
            {t("chat.resources.usedResources", "本会话引用的资源")}
            <span style={{ margin: "0 6px" }}>· {references.length}</span>
            <Button
              size="small"
              type="text"
              style={{ fontSize: 12 }}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded
                ? t("chat.resources.collapse", "收起")
                : t("chat.resources.expand", "展开")}
            </Button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {shownRefs.map((r) => (
              <div
                key={`r-${r.kind}-${r.path}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  minWidth: 0,
                }}
              >
                {r.kind === "web" ? (
                  <GlobalOutlined style={{ flexShrink: 0, opacity: 0.6 }} />
                ) : (
                  <FileTextOutlined style={{ flexShrink: 0, opacity: 0.6 }} />
                )}
                <a
                  href={
                    r.kind === "web"
                      ? r.path
                      : fileDownloadUrl(r.path)
                  }
                  target="_blank"
                  rel="noreferrer noopener"
                  title={r.path}
                  onClick={(e) => {
                    if (r.kind === "file" && onPreview) {
                      e.preventDefault();
                      onPreview({ path: r.path, title: r.title });
                    }
                  }}
                  style={{
                    flex: "1 1 auto",
                    minWidth: 0,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                    color: "inherit",
                    textDecoration: "none",
                    borderBottom: "1px dotted rgba(0,0,0,0.25)",
                  }}
                >
                  {r.title}
                </a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
