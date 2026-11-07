import { useMemo, useState } from "react";
import { Checkbox, Dropdown, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import { skillApi } from "../../../api/modules/skill";
import type { SkillSpec } from "../../../api/types";

/**
 * 本轮指定技能（v19 P1-5 / 拍板 D6）
 * ─────────────────────────────────────
 * 判断层判技能靠关键词与判官，判错了要等一轮才发现。这里给用户一个**逐条
 * 消息点名**的入口：选中的技能本轮直装，跳过关键词层与判官（台账
 * origin=user_picked 单列，不计入判断命中率——人工点名不该拿去给判断层
 * 刷成绩）。
 *
 * 只在**本轮**有效：消息发出后由调用处清空选择，下一条消息不受牵连。
 */
interface Props {
  agentId: string;
  value: string[];
  onChange: (names: string[]) => void;
}

export default function ChatSkillPicker({ agentId, value, onChange }: Props) {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = () => {
    if (loaded) return;
    void skillApi
      .listSkills(agentId)
      .then((list: SkillSpec[]) => {
        setSkills(Array.isArray(list) ? list : []);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  };

  const toggle = (name: string) => {
    onChange(value.includes(name) ? value.filter((n) => n !== name) : [...value, name]);
  };

  const items = useMemo<MenuProps["items"]>(() => {
    const pool = skills.filter((s) => s.enabled !== false);
    if (pool.length === 0) {
      return [
        {
          key: "__empty",
          disabled: true,
          label: t("chat.skillPicker.empty", "该智能体暂无可用技能"),
        },
      ];
    }
    return pool.map((s) => ({
      key: s.name,
      label: (
        <Checkbox
          checked={value.includes(s.name)}
          onChange={() => toggle(s.name)}
          style={{ width: "100%" }}
        >
          {s.emoji ? `${s.emoji} ` : ""}
          {s.name}
        </Checkbox>
      ),
    }));
  }, [skills, value, t]);

  const count = value.length;
  return (
    <Dropdown
      trigger={["click"]}
      onOpenChange={(open) => open && load()}
      menu={{ items, style: { maxHeight: 320, overflowY: "auto" } }}
    >
      <Tooltip
        title={t(
          "chat.skillPicker.tip",
          "本轮指定技能：选中的技能本轮直装，跳过关键词与判官（只影响这一条消息）",
        )}
      >
        <button
          type="button"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            border: "1px solid #d9d9d9",
            borderRadius: 6,
            background: count > 0 ? "#f0f7ff" : "transparent",
            borderColor: count > 0 ? "#1677ff" : "#d9d9d9",
            color: count > 0 ? "#1677ff" : "inherit",
            padding: "2px 8px",
            fontSize: 12,
            lineHeight: "18px",
            cursor: "pointer",
          }}
        >
        <span aria-hidden>⚡</span>
          {count > 0
            ? t("chat.skillPicker.picked", "技能 {{count}}", { count })
            : t("chat.skillPicker.label", "指定技能")}
        </button>
      </Tooltip>
    </Dropdown>
  );
}
