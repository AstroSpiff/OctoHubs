import { request } from "@/lib/http";

import type { PersistedTabOrderEntry } from "@/features/navigation/tab-order";

type TabOrderResponse = {
  success?: boolean;
  order?: PersistedTabOrderEntry[];
};

async function getTabOrder(page: string): Promise<PersistedTabOrderEntry[]> {
  const response = await request<TabOrderResponse>(`/api/ui/tab-order?page=${encodeURIComponent(page)}`);
  return response.success === false || !Array.isArray(response.order) ? [] : response.order;
}

async function saveTabOrder(page: string, order: Array<{ tab_key: string; position: number }>) {
  return request<TabOrderResponse>("/api/ui/tab-order", {
    method: "POST",
    body: JSON.stringify({ page, order }),
  });
}

export { getTabOrder, saveTabOrder };
