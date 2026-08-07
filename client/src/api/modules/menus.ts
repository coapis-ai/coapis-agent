import { request } from "../request";

export interface MenuItem {
  key: string;
  label: string;
  icon: string;
  path: string;
  permission?: string;
  sortOrder: number;
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
