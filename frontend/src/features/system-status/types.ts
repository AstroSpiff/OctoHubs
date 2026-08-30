export type Severity = "ok" | "warning" | "error" | "unknown";

export type SystemMetric = { label: string; value: string };

export type SystemItem = {
  id: string;
  label: string;
  severity: Severity;
  status_code: string;
  status_label: string;
  summary: string;
  detail: string;
  href: string;
  metrics: SystemMetric[];
};

export type SystemSection = {
  id: string;
  title: string;
  severity: Severity;
  status_code: string;
  status_label: string;
  href: string;
  check_label?: string;
  refresh_interval_seconds?: number;
  updated_at?: string;
  checked_at?: string;
  items: SystemItem[];
};

export type SystemStatus = {
  ok: boolean;
  generated_at: string;
  sections: SystemSection[];
  section?: SystemSection;
};
