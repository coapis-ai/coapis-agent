import { useState, useEffect } from "react";
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Modal,
  Form,
  Input,
  Switch,
  message,
} from "antd";
import {
  PlusOutlined,
  GlobalOutlined,
  DeleteOutlined,
  EditOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import api from "@/api";
import type { ColumnsType } from "antd/es/table";
import styles from "./index.module.less";

interface SSOProvider {
  name: string;
  issuer: string;
  client_id: string;
  enabled: boolean;
  auto_provision: boolean;
  default_role: string;
  scopes: string[];
}

function SSOPage() {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [providers, setProviders] = useState<SSOProvider[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<SSOProvider | null>(null);
  const [form] = Form.useForm();

  const fetchProviders = async () => {
    setLoading(true);
    try {
      const res = await api.get("/sso/providers");
      setProviders((res as any).data || []);
    } catch (error) {
      message.error(t("sso.fetchFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProviders();
  }, []);

  const handleAdd = () => {
    setEditingProvider(null);
    form.resetFields();
    setModalOpen(true);
  };

  const handleEdit = (provider: SSOProvider) => {
    setEditingProvider(provider);
    form.setFieldsValue(provider);
    setModalOpen(true);
  };

  const handleDelete = (name: string) => {
    Modal.confirm({
      title: t("sso.confirmDelete"),
      content: t("sso.deleteMessage", { name }),
      onOk: async () => {
        try {
          await api.delete(`/sso/providers/${name}`);
          message.success(t("sso.deleteSuccess"));
          fetchProviders();
        } catch {
          message.error(t("sso.deleteFailed"));
        }
      },
    });
  };

  const handleSubmit = async (values: any) => {
    try {
      if (editingProvider) {
        await api.put(`/sso/providers/${editingProvider.name}`, values);
        message.success(t("sso.updateSuccess"));
      } else {
        await api.post("/sso/providers", values);
        message.success(t("sso.createSuccess"));
      }
      setModalOpen(false);
      fetchProviders();
    } catch {
      message.error(t("sso.saveFailed"));
    }
  };

  const columns: ColumnsType<SSOProvider> = [
    {
      title: t("sso.name"),
      dataIndex: "name",
      render: (name: string) => (
        <Space>
          <GlobalOutlined className={styles.providerIcon} />
          <strong>{name}</strong>
        </Space>
      ),
    },
    {
      title: t("sso.issuer"),
      dataIndex: "issuer",
      ellipsis: true,
    },
    {
      title: t("sso.status"),
      dataIndex: "enabled",
      render: (enabled: boolean) => (
        <Tag color={enabled ? "success" : "error"}>
          {enabled ? t("sso.enabled") : t("sso.disabled")}
        </Tag>
      ),
    },
    {
      title: t("sso.role"),
      dataIndex: "default_role",
      render: (role: string) => <Tag>{role}</Tag>,
    },
    {
      title: t("sso.actions"),
      key: "actions",
      render: (_: any, record: SSOProvider) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            {t("common.edit")}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.name)}
          >
            {t("common.delete")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div className={styles.container}>
      <PageHeader
        parent={t("nav.sso")}
        current={t("sso.title")}
        center={
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            {t("sso.addProvider")}
          </Button>
        }
        subRow={t("sso.subtitle")}
      />

      <Card>
        <Table
          columns={columns}
          dataSource={providers}
          loading={loading}
          rowKey="name"
          locale={{ emptyText: t("sso.noProviders") }}
        />
      </Card>

      <Modal
        title={
          editingProvider
            ? t("sso.editProvider")
            : t("sso.addProvider")
        }
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={null}
      >
        <Form form={form} onFinish={handleSubmit} layout="vertical">
          <Form.Item
            name="name"
            label={t("sso.name")}
            rules={[{ required: true, message: t("sso.nameRequired") }]}
          >
            <Input placeholder={t("sso.namePlaceholder")} />
          </Form.Item>

          <Form.Item
            name="issuer"
            label={t("sso.issuer")}
            rules={[{ required: true, message: t("sso.issuerRequired") }]}
          >
            <Input placeholder="https://accounts.google.com" />
          </Form.Item>

          <Form.Item
            name="client_id"
            label={t("sso.clientId")}
            rules={[{ required: true, message: t("sso.clientIdRequired") }]}
          >
            <Input placeholder={t("sso.clientIdPlaceholder")} />
          </Form.Item>

          <Form.Item
            name="client_secret"
            label={t("sso.clientSecret")}
            rules={[{ required: true, message: t("sso.clientSecretRequired") }]}
          >
            <Input.Password placeholder={t("sso.clientSecretPlaceholder")} />
          </Form.Item>

          <Form.Item name="enabled" label={t("sso.enabled")} valuePropName="checked">
            <Switch />
          </Form.Item>

          <Form.Item
            name="auto_provision"
            label={t("sso.autoProvision")}
            valuePropName="checked"
            initialValue={true}
          >
            <Switch />
          </Form.Item>

          <Form.Item name="default_role" label={t("sso.defaultRole")}>
            <Input defaultValue="user" />
          </Form.Item>

          <Form.Item>
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button onClick={() => setModalOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button type="primary" htmlType="submit">
                {t("common.save")}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

export default SSOPage;
