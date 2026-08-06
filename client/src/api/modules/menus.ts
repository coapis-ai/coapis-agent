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
  children?: MenuItem[];
}

export interface MenuResponse {
  items: MenuItem[];
}

// Menu API
export const menusApi = {
  // Get main menu configuration from /menus endpoint
  getMainMenu: () => request<MenuResponse>("/menus"),
};
