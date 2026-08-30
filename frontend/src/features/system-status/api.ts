import { request } from "@/lib/http";
import type { SystemStatus } from "@/features/system-status/types";

export function getSystemStatus(section?: string, checkServices = false): Promise<SystemStatus> {
  const parameters = new URLSearchParams();
  if (section) parameters.set("section", section);
  if (checkServices) parameters.set("check_services", "true");
  const suffix = parameters.size ? `?${parameters.toString()}` : "";
  return request<SystemStatus>(`/api/v1/system/status${suffix}`);
}
