p = "client/src/pages/Chat/components/FloatingWindow.tsx"
lines = open(p, encoding="utf-8").read().split("\n")

start = next(k for k, l in enumerate(lines) if "打开时解析宿主" in l)
# 该 effect 的收尾行（缩进 2 的 "}, [...]);"）
end = next(k for k in range(start, start + 60) if lines[k].startswith("  }, ["))
print("effect", start + 1, "->", end + 1, repr(lines[end]))

ins = '''
  /**
   * v17 · F9：把"收起 / 铺满"**写**回记忆。此前 `coapis.<key>.min/.max`
   * 只有读、没有写 —— 上面注释写着"跨开窗恢复"，实际每次开都回到默认态。
   * 移动网页版与内嵌抽屉本就整页铺满，不参与这两个记忆。
   */
  useEffect(() => {
    if (!open || isMobile || !storageKey) return;
    try {
      localStorage.setItem(`coapis.${storageKey}.min`, minimized ? "1" : "0");
      localStorage.setItem(`coapis.${storageKey}.max`, maximized ? "1" : "0");
    } catch {
      /* 隐私模式禁存储：记忆退化为"本次会话内生效" */
    }
  }, [open, storageKey, isMobile, minimized, maximized]);'''.split("\n")
lines[end + 1 : end + 1] = ins
open(p, "w", encoding="utf-8").write("\n".join(lines))
print("inserted")
