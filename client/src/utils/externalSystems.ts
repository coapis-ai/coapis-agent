/**
 * 外部系统管理 - 前端工具函数
 */

/**
 * 将图片文件压缩为 96×96 dataURL (PNG)
 * 用于外部系统 icon 上传
 */
export async function compressImageToDataUrl(
  file: File,
  size = 96,
): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  ctx.drawImage(bitmap, 0, 0, size, size);
  bitmap.close();
  return canvas.toDataURL("image/png");
}

/**
 * 校验 dataURL 大小是否合理（< 100KB）
 */
export function isValidIconDataUrl(dataUrl: string): boolean {
  if (!dataUrl || !dataUrl.startsWith("data:image/")) return false;
  // base64 部分约占 4/3 原始大小；100KB base64 ≈ 133333 chars
  return dataUrl.length < 133333;
}
