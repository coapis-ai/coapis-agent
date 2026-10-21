// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
import api from "@/api";
import { chatApi } from "../../api/modules/chat";
import { getApiToken, getApiUrl } from "../../api/config";
export type CopyableContent = {
  type?: string;
  text?: string;
  refusal?: string;
};

export type CopyableMessage = {
  role?: string;
  content?: string | CopyableContent[];
};

export type CopyableResponse = {
  output?: CopyableMessage[];
};

export type RuntimeLoadingBridgeApi = {
  getLoading?: () => boolean | string;
  setLoading?: (loading: boolean | string) => void;
};

// ---------------------------------------------------------------------------
// 用户气泡补媒体块（「+ 资源菜单」通道）
// ---------------------------------------------------------------------------
//
// 为什么需要它：SDK 的用户气泡**不读**我们发出去的 content，它读的是
// {query, fileList} —— 见 @agentscope-ai/chat 的
// AgentScopeRuntimeWebUI/core/Chat/hooks/useChatMessageHandler.js:
//   createRequestMessage(data) → cards[0].data = RequestBuilder().handle(data)
// RequestBuilder 只认 data.fileList（原生上传）。而「+ 菜单」选的文件走的是
// 组件 state（selectedFiles → biz_params.selected_files + 我们重写的 content），
// 从不进 fileList。结果：模型收得到图（content 里有 image 块），气泡里只有
// 一个文件名 chip，没有缩略图。
//
// 修法：请求发出后（SDK 已 flushSync 建好这条用户消息），把同样的媒体块
// 补写进气泡卡片读的 data.input[0].content。Request/Card.js 认
// type:"image"+image_url / "video"+video_url / "audio"+audio_url，
// 补进去就有 Images/Videos/Audios 卡片。
//
// 注意三处口径：
//  1. 这里写的是**预览 URL**（浏览器取得到的），不是发给后端的 stored name
//     （normalizeContentUrls 会把 URL 折成 /media/x，那是给后端的路径形态）。
//  2. 必须整体新建对象：updateMessage 是浅合并，原地改数组 React 看不见。
//  3. 只补不重复补：按 URL 去重，重试/连发都不会叠加。

export type ChatMessagesBridgeApi = {
  getMessages: () => any[];
  updateMessage: (message: { id: string } & Record<string, any>) => void;
};

const REQUEST_CARD_CODE = "AgentScopeRuntimeRequestCard";

/** 找出气泡里已存在的媒体块 URL，用于去重（不重复补同一张图）。 */
function existingMediaUrls(content: any[]): Set<string> {
  const urls = new Set<string>();
  for (const c of content) {
    if (!c || typeof c !== "object") continue;
    const u = c.image_url || c.video_url || c.audio_url || c.source?.url;
    if (typeof u === "string") urls.add(u);
  }
  return urls;
}

/**
 * 把媒体块补进**最后一条**用户气泡。
 *
 * blocks 为展示形态的内容块（type 为 image/video/audio，带预览 URL）。
 * 找不到消息/卡片结构不合预期时静默跳过 —— 补缩略图是锦上添花，
 * 绝不能把发送流程带崩。
 */
export function appendMediaToUserBubble(
  bridge: ChatMessagesBridgeApi | null,
  blocks: any[],
): void {
  if (!bridge || blocks.length === 0) return;
  try {
    const messages = bridge.getMessages() || [];
    let target: any = null;
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i]?.role === "user") {
        target = messages[i];
        break;
      }
    }
    if (!target) return;

    const cards: any[] = target.cards || [];
    const cardIdx = cards.findIndex(
      (c) => c?.code === REQUEST_CARD_CODE && Array.isArray(c?.data?.input?.[0]?.content),
    );
    if (cardIdx < 0) return;

    const card = cards[cardIdx];
    const oldContent: any[] = card.data.input[0].content;
    const have = existingMediaUrls(oldContent);
    const fresh = blocks.filter((b) => {
      const u = b?.image_url || b?.video_url || b?.audio_url;
      return u && !have.has(u);
    });
    if (fresh.length === 0) return;

    const nextCards = [...cards];
    nextCards[cardIdx] = {
      ...card,
      data: {
        ...card.data,
        input: [
          ...card.data.input.slice(0, 1),
          ...card.data.input.slice(1),
        ].map((inp: any, idx: number) =>
          idx === 0 ? { ...inp, content: [...oldContent, ...fresh] } : inp,
        ),
      },
    };
    bridge.updateMessage({ id: target.id, cards: nextCards });
  } catch (error) {
    console.warn("[Chat] attach media to user bubble failed:", error);
  }
}

// ---------------------------------------------------------------------------
// Text extraction utilities
// ---------------------------------------------------------------------------

/** Extract copyable text from assistant response. */
export function extractCopyableText(response: CopyableResponse): string {
  const collectText = (assistantOnly: boolean) => {
    const chunks = (response.output || []).flatMap((item: CopyableMessage) => {
      if (assistantOnly && item.role !== "assistant") return [];

      if (typeof item.content === "string") {
        return [item.content];
      }

      if (!Array.isArray(item.content)) {
        return [];
      }

      return item.content.flatMap((content: CopyableContent) => {
        if (content.type === "text" && typeof content.text === "string") {
          return [content.text];
        }

        if (content.type === "refusal" && typeof content.refusal === "string") {
          return [content.refusal];
        }

        return [];
      });
    });

    return chunks.filter(Boolean).join("\n\n").trim();
  };

  return collectText(true) || JSON.stringify(response);
}

/** Extract plain text from user message content. */
export function extractUserMessageText(m: any): string {
  if (typeof m.content === "string") return m.content;
  if (!Array.isArray(m.content)) return "";
  return m.content
    .filter((p: any) => p.type === "text")
    .map((p: any) => p.text || "")
    .join("\n");
}

export function extractTextFromMessage(msg: any): string {
  const innerMessage = msg?.cards?.[0]?.data?.input?.[0];
  if (!innerMessage) return "";
  return extractUserMessageText(innerMessage);
}

// ---------------------------------------------------------------------------
// Clipboard utilities
// ---------------------------------------------------------------------------

/** Copy text to clipboard with fallback for non-secure contexts. */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);

  let copied = false;
  try {
    textarea.focus();
    textarea.select();
    copied = document.execCommand("copy");
  } finally {
    document.body.removeChild(textarea);
  }

  if (!copied) {
    throw new Error("Failed to copy text");
  }
}

// ---------------------------------------------------------------------------
// Error response utilities
// ---------------------------------------------------------------------------

/** Build a 400 error response when model is not configured. */
export function buildModelError(): Response {
  return new Response(
    JSON.stringify({
      error: "Model not configured",
      message: "Please configure a model first",
    }),
    { status: 400, headers: { "Content-Type": "application/json" } },
  );
}

// ---------------------------------------------------------------------------
// URL normalization utilities
// ---------------------------------------------------------------------------

/** Decode each path segment; keeps `/` delimiters (including repeated `/`). */
function decodeUriPathSegments(path: string): string {
  return path
    .split("/")
    .map((segment) => {
      if (!segment) return segment;
      try {
        return decodeURIComponent(segment);
      } catch {
        return segment;
      }
    })
    .join("/");
}

/** Convert file URL to stored path for backend: keep full path after `/files/preview/`. */
export function toStoredName(v: string): string {
  const marker = "/files/preview/";
  const idx = v.indexOf(marker);
  if (idx !== -1) {
    let rest = v.slice(idx + marker.length);
    const q = rest.indexOf("?");
    if (q !== -1) rest = rest.slice(0, q);
    const h = rest.indexOf("#");
    if (h !== -1) rest = rest.slice(0, h);
    if (rest) {
      const decoded = decodeUriPathSegments(rest);
      // Windows absolute path: C:\... or C:/...
      const isWindowsAbsolute = /^[a-zA-Z]:[\\/]/.test(decoded);
      if (isWindowsAbsolute) return decoded;
      return decoded.startsWith("/") ? decoded : `/${decoded}`;
    }
  }
  return v;
}

/** Convert content part URLs to stored name format. */
export function normalizeContentUrls(part: any): any {
  const p = { ...part };
  if (p.type === "image" && typeof p.image_url === "string")
    p.image_url = toStoredName(p.image_url);
  if (p.type === "file" && typeof p.file_url === "string")
    p.file_url = toStoredName(p.file_url);
  if (p.type === "audio" && typeof p.data === "string")
    p.data = toStoredName(p.data);
  if (p.type === "video" && typeof p.video_url === "string")
    p.video_url = toStoredName(p.video_url);
  return p;
}

/** Turn a backend content URL (path or full URL) into a full URL for display.
 *
 *  三条路，按形态分流（本轮实测定的口径，每条都实测过 200）：
 *   1. 已是 http(s) / 已是 /api/ 开头的 API URL → 原样用。
 *   2. **真实绝对路径**（含 /workspaces/，后端持久化的媒体块就是
 *      `file:///apps/ai/coapis/workspaces/<user>/files/...` 形态）
 *      → /api/files/preview/{绝对路径}。file_preview.py 按
 *      `Path("/"+p).resolve()` 取文件，**只认绝对路径**。
 *   3. **工作区相对形态**（`/upload_test.png`、`media/x.png`）
 *      → /api/myfiles/download?path=&category=files（用户作用域 + 权限门控）。
 *      这类路径喂给 preview 端点必 404 —— 它当绝对磁盘路径解析，
 *      `/upload_test.png` 变成根目录下的 `/upload_test.png`。
 *
 *  第 3 条是原生上传通道的缩略图修复：后端 /api/myfiles/upload 返回的
 *  `url` 是 `/upload_test.png`（相对工作区），SDK 直接拿它当 `<img src>`
 *  （Request/Builder.js buildImageContent: `image_url: file.response.url`），
 *  浏览器取 `/upload_test.png` → 404 → 气泡里图片是空 src。
 *
 *  注意 `/workspaces/` 这个判据：dev/生产的挂载点不同
 *  （host /apps/ai/coapis-dev → 容器 /apps/ai/coapis），但两侧路径里
 *  `workspaces` 这一段都在，判据不依赖具体前缀。
 */
export function toDisplayUrl(url: string | undefined): string {
  if (!url) return "";
  if (url.startsWith("http://") || url.startsWith("https://")) return url;
  if (url.startsWith("file://")) url = url.replace("file://", "");
  if (url.startsWith("/api/")) return getApiUrl(url.slice(3));
  // 真实绝对路径：preview 端点能直接取到
  if (url.startsWith("/") && url.includes("/workspaces/")) {
    return chatApi.filePreviewUrl(url);
  }
  // 工作区相对形态：走我的空间下载端点
  return mySpaceDisplayUrl(url.replace(/^\/+/, ""));
}

/**
 * 「+ 资源菜单」选中的**我的空间**文件 → 浏览器可直读的展示 URL。
 *
 * 为什么不能用 chatApi.filePreviewUrl（这是本轮实测出来的坑）：
 * 它拼的是 `/api/files/preview/<路径>`，而那个端点（server/coapis/app/
 * routers/file_preview.py）把传入路径当**绝对磁盘路径**用 ——
 * `Path("/" + normalized).resolve()`。喂我的空间相对路径 `e2e_red_box.png`
 * 得到 `/e2e_red_box.png`，必 404（实测 404）。原生上传通道之所以能显示，
 * 是因为它带的是 media/ 下的完整形态，不是同一条路。
 *
 * 我的空间文件的取文件端点是 `/api/myfiles/download?path=<相对>&category=files`
 * —— 用户作用域 + 权限门控，实测 200 / image/png，`<img>` 可直读
 * （Content-Disposition: attachment 对图片子资源不生效，浏览器照渲染）。
 *
 * 只用于**展示**。发给后端的块保持原路径形态（`/x.png`），那边由
 * `_resolve_media_url` 按工作区解析，链路已验证可用 —— 两边不要混用。
 */
export function mySpaceDisplayUrl(
  relPath: string,
  category = "files",
): string {
  if (!relPath) return "";
  if (relPath.startsWith("http://") || relPath.startsWith("https://")) {
    return relPath;
  }
  const cleaned = relPath.replace(/^\/+/, "");
  const url = getApiUrl(
    `/myfiles/download?path=${encodeURIComponent(cleaned)}&category=${encodeURIComponent(
      category,
    )}`,
  );
  const token = getApiToken();
  return token ? `${url}&token=${encodeURIComponent(token)}` : url;
}


// ---------------------------------------------------------------------------
// Media type detection (会话引用 → 内容块类型)
// ---------------------------------------------------------------------------

// 判定逻辑的唯一权威在 components/Chat/mediaType.ts（组件层与页面层共用，
// 依赖方向保持 页面 → 组件，避免组件反向 import 页面）。
export { mediaTypeFromFilename } from "../../components/Chat/mediaType";
export type { ChatMediaType } from "../../components/Chat/mediaType";


// ---------------------------------------------------------------------------
// DOM utilities
// ---------------------------------------------------------------------------

/** Set textarea value and trigger input event for React state sync.
 * Uses native value setter to bypass React's internal value tracker.
 */
export function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const nativeValueSetter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  if (nativeValueSetter) {
    nativeValueSetter.call(textarea, value);
  } else {
    textarea.value = value;
  }
  textarea.selectionStart = textarea.selectionEnd = value.length;
  const event = new Event("input", { bubbles: true });
  textarea.dispatchEvent(event);
}

// ---------------------------------------------------------------------------
// Scene utilities
// ---------------------------------------------------------------------------

/** Parse the scene id from a scene session's sessionId (`scene:<scene_id>:<agent>`).
 * Returns "" for non-scene sessions. Scene ids contain dashes, so splitting on
 * `:` is safer than parsing the chat id (`scene-<scene_id>-<user>`). */
export function parseSceneId(sessionId?: string): string {
  if (!sessionId || !sessionId.startsWith("scene:")) return "";
  return sessionId.split(":")[1] ?? "";
}

// ---------------------------------------------------------------------------
// Scene name cache
// ---------------------------------------------------------------------------

let sceneNames: Record<string, string> = {};
let sceneNamesPromise: Promise<Record<string, string>> | null = null;

/** Load the scene id→name map once per page load (cached). Failures resolve to
 * an empty map and reset the cache so the next mount can retry. */
export function loadSceneNames(): Promise<Record<string, string>> {
  if (sceneNamesPromise) return sceneNamesPromise;
  sceneNamesPromise = api
    .get<{ scenes?: { id: string; name: string }[] }>("/scenes")
    .then((resp) => {
      const list = Array.isArray(resp) ? resp : (resp?.scenes ?? []);
      sceneNames = {};
      for (const s of list) {
        if (s?.id && s?.name) sceneNames[s.id] = s.name;
      }
      return sceneNames;
    })
    .catch(() => {
      sceneNamesPromise = null; // allow retry on next mount
      return {};
    });
  return sceneNamesPromise;
}

/** Synchronous lookup of a scene name from the cache ("" if not loaded/known). */
export function getCachedSceneName(sceneId: string): string {
  return sceneNames[sceneId] ?? "";
}
