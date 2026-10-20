// 会话引用 → 内容块类型判定（唯一权威）
//
// 为什么需要它：聊天输入框有两条附件通道（原生上传 / 「+ 资源菜单」），
// 原生通道按 MIME 产出 image/video/audio 块，「+ 菜单」过去一律写死 "file"。
// 后端只对 image/video/audio 块送真正的媒体数据，file 块会被 formatter 压成
// 一句 "File 'x.png' is available at: /path" 纯文本 —— 模型收不到像素；
// 前端 Images 卡片也只认 type:"image" + image_url，file 只剩文件名 chip。
// 所以「选了一张图」必须落成 image 才有缩略图 + 模型真能看到。
//
// 扩展名表**必须**与后端逐字对齐：
//   图片/视频 → server/coapis/agents/model_factory.py
//     _SUPPORTED_IMAGE_EXTENSIONS / _SUPPORTED_VIDEO_EXTENSIONS
//     （Anthropic 家族遇到表外扩展名会抛 ModelFormatterError，整条请求崩）
//   音频 → server/coapis/agents/utils/message_processing.py
//     _FORMATTER_SUPPORTED_AUDIO_EXTS + ffmpeg 可转码集合
// 表外的一律按 file 走文本占位符（现状最优，不猜）。

/** 会话引用可产出的内容块类型。 */
export type ChatMediaType = "image" | "video" | "audio" | "file";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp"]);
const VIDEO_EXTS = new Set(["mp4", "webm", "mpeg", "mov", "avi", "mkv"]);
const AUDIO_EXTS = new Set([
  "wav",
  "mp3",
  "m4a",
  "aac",
  "ogg",
  "opus",
  "flac",
  "amr",
  "amr-wb",
]);

/** 按扩展名判定内容块类型（大小写无关，取最后一个点后的段）。 */
export function mediaTypeFromFilename(
  name: string | undefined,
): ChatMediaType {
  if (!name) return "file";
  const base = name.split(/[\\/]/).pop() ?? name;
  const dot = base.lastIndexOf(".");
  if (dot <= 0 || dot === base.length - 1) return "file";
  const ext = base.slice(dot + 1).toLowerCase();
  if (IMAGE_EXTS.has(ext)) return "image";
  if (VIDEO_EXTS.has(ext)) return "video";
  if (AUDIO_EXTS.has(ext)) return "audio";
  return "file";
}
