import { useState } from "react";
import { Modal, Button, Input, Table, Popconfirm, message } from "@agentscope-ai/design";
import { Space } from "antd";
import { PlusOutlined, EditOutlined, DeleteOutlined } from "@ant-design/icons";
import type { CategorySpec } from "../../../../api/types";
import api from "../../../../api";

interface CategoryManagerProps {
  open: boolean;
  onClose: () => void;
  categories: CategorySpec[];
  onRefresh: () => void;
}

export function CategoryManager({ open, onClose, categories, onRefresh }: CategoryManagerProps) {
  const [editing, setEditing] = useState<CategorySpec | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState({ key: "", label: "", emoji: "" });

  const openAdd = () => {
    setEditing(null);
    setForm({ key: "", label: "", emoji: "" });
    setEditOpen(true);
  };

  const openEdit = (cat: CategorySpec) => {
    setEditing(cat);
    setForm({ key: cat.key, label: cat.label, emoji: cat.emoji || "" });
    setEditOpen(true);
  };

  const handleSave = async () => {
    if (!form.key.trim() || !form.label.trim()) {
      message.warning("分类标识和名称不能为空");
      return;
    }
    try {
      if (editing) {
        await api.updateCategory(editing.key, {
          label: form.label,
          emoji: form.emoji,
          new_key: form.key !== editing.key ? form.key : undefined,
        });
        message.success("分类已更新");
      } else {
        await api.createCategory({ key: form.key, label: form.label, emoji: form.emoji });
        message.success("分类已创建");
      }
      setEditOpen(false);
      onRefresh();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "操作失败");
    }
  };

  const handleDelete = async (key: string) => {
    try {
      await api.deleteCategory(key);
      message.success("分类已删除");
      onRefresh();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "删除失败");
    }
  };

  const columns = [
    {
      title: "标识",
      dataIndex: "key",
      width: 150,
    },
    {
      title: "图标",
      dataIndex: "emoji",
      width: 60,
      render: (emoji: string) => <span style={{ fontSize: 20 }}>{emoji}</span>,
    },
    {
      title: "名称",
      dataIndex: "label",
    },
    {
      title: "排序",
      dataIndex: "sort_order",
      width: 80,
    },
    {
      title: "操作",
      width: 120,
      render: (_: unknown, record: CategorySpec) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确认删除此分类？" onConfirm={() => handleDelete(record.key)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <Modal
        title="管理技能分类"
        open={open}
        onCancel={onClose}
        footer={null}
        width={600}
      >
        <div style={{ marginBottom: 12 }}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openAdd}>
            添加分类
          </Button>
        </div>
        <Table
          dataSource={categories}
          columns={columns}
          rowKey="key"
          size="small"
          pagination={false}
        />
      </Modal>

      <Modal
        title={editing ? "编辑分类" : "添加分类"}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        onOk={handleSave}
        okText="保存"
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 12, padding: "8px 0" }}>
          <div>
            <label style={{ display: "block", marginBottom: 4 }}>分类标识（英文唯一键）</label>
            <Input
              value={form.key}
              onChange={(e) => setForm({ ...form, key: e.target.value })}
              placeholder="如: system, browser"
              disabled={!!editing}
            />
          </div>
          <div>
            <label style={{ display: "block", marginBottom: 4 }}>显示名称</label>
            <Input
              value={form.label}
              onChange={(e) => setForm({ ...form, label: e.target.value })}
              placeholder="如: 系统, 浏览器"
            />
          </div>
          <div>
            <label style={{ display: "block", marginBottom: 4 }}>图标 Emoji</label>
            <Input
              value={form.emoji}
              onChange={(e) => setForm({ ...form, emoji: e.target.value })}
              placeholder="如: ⚙️ 🌐 📄"
            />
          </div>
        </div>
      </Modal>
    </>
  );
}
