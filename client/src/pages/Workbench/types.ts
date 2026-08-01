// Scene-related types

export interface SceneConfig {
  id: string;
  name: string;
  icon: string;
  description: string;
  short_description: string;
  
  // Tag association (new fields)
  primary_tag_id?: string;
  tag_ids: string[];
  
  // Capabilities
  skills: string[];
  system_prompt: string;
  welcome_message: string;
  
  // Status and statistics
  status: 'active' | 'disabled' | 'deleted';
  usage_count: number;
  
  // Timestamps
  created_at: string;
  updated_at: string;
  created_by?: string;
  
  // Backward compatibility (deprecated)
  category: string;
  tags: string[];
}

export interface SceneInfo {
  id: string;
  icon: string;
  category: string;
  tags: string[];
  status: string;
}

export interface EnterSceneResponse {
  chat_id: string;
  session_id: string;
  scene: SceneInfo;
  agent: {
    id: string;
    type: string;
    scene_agent_id: string;
    user_id: string;
  };
  welcome_message: string;
}

export interface SceneListResponse {
  scenes: SceneConfig[];
  total: number;
}

// Workbench menu item
export interface WorkbenchMenuItem {
  id: string;
  name: string;
  icon: string;
  scene_count: number;
}

// Workbench section
export interface WorkbenchSection {
  tag: {
    id: string;
    name: string;
    icon: string;
    description: string;
  };
  scenes: SceneConfig[];
}
