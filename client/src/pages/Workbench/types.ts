// Scene-related types

export interface SceneConfig {
  id: string;
  name: string;
  icon: string;
  description: string;
  category: string;
  tags: string[];
  skills: string[];
  system_prompt: string;
  welcome_message: string;
  status: 'active' | 'disabled' | 'deleted';
  created_at: string;
  updated_at: string;
  created_by?: string;
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
