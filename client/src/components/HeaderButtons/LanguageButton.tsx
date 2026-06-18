
import { Dropdown, Button } from 'antd';
import { GlobalOutlined } from '@ant-design/icons';
import { useTranslation } from 'react-i18next';
import { languageApi } from '../../api/modules/language';

export default function LanguageButton() {
  const { i18n } = useTranslation();

  const currentLanguage = i18n.resolvedLanguage || i18n.language;
  const currentLangKey = currentLanguage.split('-')[0];

  const changeLanguage = (lang: string) => {
    i18n.changeLanguage(lang);
    localStorage.setItem('language', lang);
    languageApi
      .updateLanguage(lang)
      .catch((err) =>
        console.error('Failed to save language preference:', err),
      );
  };

  const items = [
    {
      key: 'en',
      label: 'English',
      onClick: () => changeLanguage('en'),
    },
    {
      key: 'zh',
      label: '简体中文',
      onClick: () => changeLanguage('zh'),
    },
    {
      key: 'ja',
      label: '日本語',
      onClick: () => changeLanguage('ja'),
    },
    {
      key: 'ru',
      label: 'Русский',
      onClick: () => changeLanguage('ru'),
    },
  ];

  return (
    <Dropdown
      menu={{ items, selectedKeys: [currentLangKey] }}
      placement="bottomRight"
    >
      <Button
        type="text"
        icon={<GlobalOutlined />}
        title={i18n.t('header.language.title')}
        style={{ fontSize: '16px' }}
      />
    </Dropdown>
  );
}
