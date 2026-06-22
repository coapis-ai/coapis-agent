/**
 * 弹出系统"另存为"对话框获取文件句柄。
 * 仅在安全上下文（HTTPS / localhost）下可用。
 * 返回 FileHandle 或 null（不支持或用户取消）。
 */
export async function requestSaveHandle(defaultName: string): Promise<FileSystemFileHandle | null> {
  if ("showSaveFilePicker" in window) {
    try {
      return await (window as any).showSaveFilePicker({
        suggestedName: defaultName,
        types: [
          {
            description: "ZIP Archive",
            accept: { "application/zip": [".zip"] },
          },
        ],
      });
    } catch (e: any) {
      // 用户点取消
      if (e?.name === "AbortError") return null;
      throw e;
    }
  }
  return null;
}

/**
 * 将 Blob 写入已获取的 FileHandle，或 fallback 为 <a> 下载。
 */
export async function writeBlobToHandle(
  blob: Blob,
  handle: FileSystemFileHandle | null,
  fallbackName: string,
): Promise<void> {
  if (handle) {
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return;
  }
  // Fallback: 传统 <a> 下载（HTTP 环境或不支持 File System Access API 的浏览器）
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fallbackName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
