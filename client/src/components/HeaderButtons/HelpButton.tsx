
import { Dropdown, Button } from 'antd';
import { QuestionCircleOutlined, GlobalOutlined, GithubOutlined, BookOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import {
  getDocsUrl,
  getFaqUrl,
  GITHUB_URL,
  getReleaseNotesUrl,
} from '../../layouts/constants';

interface HelpButtonProps {
  onClick?: (url: string) => void;
}

export default function HelpButton({ onClick }: HelpButtonProps) {
  const { t, i18n } = useTranslation();

  const handleNavClick = (url: string) => {
    if (onClick) {
      onClick(url);
      return;
    }
    const pywebview = (window as any).pywebview;
    if (pywebview?.api) {
      pywebview.api.open_external_link(url);
    } else {
      window.open(url, '_blank');
    }
  };

  const items = [
    {
      key: 'docs',
      icon: <BookOutlined />,
      label: t('header.help.docs'),
      onClick: () => handleNavClick(getDocsUrl(i18n.language)),
    },
    {
      key: 'faq',
      icon: <QuestionCircleOutlined />,
      label: t('header.help.faq'),
      onClick: () => handleNavClick(getFaqUrl(i18n.language)),
    },
    {
      key: 'github',
      icon: <GithubOutlined />,
      label: t('header.help.github'),
      onClick: () => handleNavClick(GITHUB_URL),
    },
    {
      key: 'release',
      icon: <GlobalOutlined />,
      label: t('header.help.release'),
      onClick: () => handleNavClick(getReleaseNotesUrl(i18n.language)),
    },
  ];

  return (
    <Dropdown menu={{ items }} placement="bottomRight">
      <Button
        type="text"
        icon={<QuestionCircleOutlined />}
        title={t('header.help.title')}
        style={{ fontSize: '16px' }}
      />
    </Dropdown>
  );
}
