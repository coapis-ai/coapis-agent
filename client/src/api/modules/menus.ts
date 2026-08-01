import { request } from "../request";

export interface MenuItem {
  key: string;
  label: string;
  labelKey: string;
  icon: string;
  path: string;
  permission?: string;
  sortOrder: number;
  isActive: boolean;
  childrenSource?: string;
}

export interface MenuResponse {
  items: MenuItem[];
}

// Menu API
export const menusApi = {
  // Get main menu configuration from tags with type='menu'
  getMainMenu: () => request<MenuResponse>("/menus"),
};
