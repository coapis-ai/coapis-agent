import { Fragment, type ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { Button } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import styles from "./index.module.less";

export type PageHeaderBreadcrumbItem = {
  title: ReactNode;
};

export interface PageHeaderProps {
  /** When omitted, `parent` and `current` build the trail. */
  items?: PageHeaderBreadcrumbItem[];
  parent?: ReactNode;
  current?: ReactNode;
  center?: ReactNode;
  extra?: ReactNode;
  /** Same row as the breadcrumb (e.g. workspace path chip). */
  afterBreadcrumb?: ReactNode;
  subRow?: ReactNode;
  className?: string;
  /** 强制显示返回按钮（覆盖自动检测） */
  showBack?: boolean;
  /** 自定义返回路径（默认返回到来源页面） */
  backTo?: string;
}

function buildItemsFromParentCurrent(
  parent: ReactNode | undefined,
  current: ReactNode | undefined,
): PageHeaderBreadcrumbItem[] {
  const out: PageHeaderBreadcrumbItem[] = [];
  if (parent != null && parent !== "") out.push({ title: parent });
  if (current != null && current !== "") out.push({ title: current });
  return out;
}

export function PageHeader({
  items: itemsProp,
  parent,
  current,
  center,
  extra,
  afterBreadcrumb,
  subRow,
  className,
  showBack: showBackProp,
  backTo,
}: PageHeaderProps) {
  const navigate = useNavigate();
  const location = useLocation();
  
  // 自动检测是否从设置页面跳转
  const autoShowBack = location.state?.from === '/settings';
  const showBack = showBackProp ?? autoShowBack;
  
  const handleBack = () => {
    navigate(backTo || location.state?.from || '/settings');
  };
  
  const items =
    itemsProp !== undefined
      ? itemsProp
      : buildItemsFromParentCurrent(parent, current);

  return (
    <div className={`${styles.pageHeader} ${className ?? ""}`.trim()}>
      <div className={styles.leading}>
        <div className={styles.leadingTop}>
          <div className={styles.breadcrumbHeader}>
            {showBack && (
              <Button 
                type="text" 
                icon={<ArrowLeftOutlined />}
                onClick={handleBack}
                className={styles.backButton}
              >
                返回
              </Button>
            )}
            {items.map((item, index) => (
              <Fragment key={index}>
                {index > 0 || showBack ? (
                  <span className={styles.breadcrumbSeparator}>/</span>
                ) : null}
                <span
                  className={
                    index === items.length - 1
                      ? styles.breadcrumbCurrent
                      : styles.breadcrumbParent
                  }
                >
                  {item.title}
                </span>
              </Fragment>
            ))}
            {afterBreadcrumb}
          </div>
        </div>
        {subRow}
      </div>
      {center ? <div className={styles.center}>{center}</div> : null}
      {extra ? <div className={styles.extra}>{extra}</div> : null}
    </div>
  );
}
