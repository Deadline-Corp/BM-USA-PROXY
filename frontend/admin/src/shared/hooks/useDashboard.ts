import { useQuery } from "@tanstack/react-query";
import { dashboardApi } from "@/shared/api/endpoints";

export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard", "summary"],
    queryFn: dashboardApi.summary,
    refetchInterval: 60_000,
  });
}

export function useDashboardRevenue(days = 30) {
  return useQuery({
    queryKey: ["dashboard", "revenue", days],
    queryFn: () => dashboardApi.revenue(days),
  });
}
