export interface ActiveHoursConfig {
  start: string;
  end: string;
}

export interface HeartbeatConfig {
  enabled: boolean;
  interval_seconds: number;
  target: string;
  active_hours?: ActiveHoursConfig | null;
  timeout_seconds: number;
  updated_at?: string | null;
}
