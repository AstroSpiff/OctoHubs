import { request } from "@/lib/http";

import type { PersistedTabOrderEntry } from "@/features/navigation/tab-order";
import type { UiTabOrderRequest, UiTabOrderResponse } from "@/lib/ui-api-contracts";

async function getTabOrder(page: string): Promise<PersistedTabOrderEntry[]> {
  const response = await request<UiTabOrderResponse>(`/api/ui/tab-order?page=${encodeURIComponent(page)}`);
  return Array.isArray(response.order) ? response.order : [];
}

async function saveTabOrder(page: string, order: Array<{ tab_key: string; position: number }>) {
  const payload: UiTabOrderRequest = { page, order };
  return request<UiTabOrderResponse>("/api/ui/tab-order", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export { getTabOrder, saveTabOrder };
