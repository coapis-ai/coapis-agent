p = "client/src/pages/Chat/components/ChatSessionResources/index.tsx"
s = open(p, encoding="utf-8").read()

# 1) 表头排序接线：分页由外部 Pagination 管，这里只管换尺子
old1 = '''  const handleTableChange: NonNullable<
    TableProps<ChatResourceItem>["onChange"]
  > = (pag, _filters, sorter) => {
      const s = Array.isArray(sorter) ? sorter[0] : sorter;
      const key = String(s?.columnKey ?? "");
      if (s?.order && key && key !== sort) setSort(key);
      const pageSize = (pag?.pageSize as number) || PAGE_SIZE;
      const nextOffset = ((pag?.current as number) || 1) * pageSize - pageSize;
      if (nextOffset !== offset) setOffset(nextOffset);
    };
'''
new1 = '''  const handleTableChange: NonNullable<
    TableProps<ChatResourceItem>["onChange"]
  > = (_pag, _filters, sorter) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    const key = String(s?.columnKey ?? "");
    if (s?.order && key && key !== sort) setSort(key);
  };
'''
assert old1 in s, "handleTableChange not found"
s = s.replace(old1, new1, 1)

# 2) 排序下拉下线（表头是唯一控制点，避免两把尺子）
old2 = '''        <Select
          size="small"
          style={{ width: 120 }}
          getPopupContainer={(node) =>
            (node.parentElement as HTMLElement) ?? document.body
          }
          value={sort}
          onChange={setSort}
          options={[
            { value: "time_desc", label: t("chat.resources.sortTimeDesc") },
            { value: "time_asc", label: t("chat.resources.sortTimeAsc") },
            { value: "name", label: t("chat.resources.sortName") },
            { value: "size", label: t("chat.resources.sortSize") },
          ]}
        />
'''
assert old2 in s, "sort select not found"
s = s.replace(old2, "", 1)

# 3) 刷新按钮此前写 setOffset(0)：已在第 1 页时是空操作 = 刷新无效
old3 = '''        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => setOffset(0)}
        />'''
new3 = '''        {/* v17 · F7：刷新此前写的是 `setOffset(0)` —— 已在第 1 页时是空操作，
            按了等于没按。改成显式重拉当前页。 */}
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={() => setTick((v) => v + 1)}
        />'''
assert old3 in s, "refresh button not found"
s = s.replace(old3, new3, 1)

open(p, "w", encoding="utf-8").write(s)
print("ok")
