// Server state through TanStack Query. Network layers never change while the app runs (a
// rebuild needs a reload), so they are cached for the session.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  Accessibility,
  CityDetail,
  Network,
  RouteDetail,
  RouteList,
  Scenario,
  ScenarioRecord,
  ScenarioSummary,
  Simulation,
  StopCollection,
  Zones,
} from "./types";

const forever = { staleTime: Infinity, gcTime: Infinity } as const;
const base = (city: string) => `/api/cities/${city}`;

export const useCity = (city: string) =>
  useQuery({ queryKey: ["city", city], queryFn: () => api<CityDetail>(base(city)), ...forever });

export const useRoutes = (city: string) =>
  useQuery({
    queryKey: ["routes", city],
    queryFn: () => api<RouteList>(`${base(city)}/routes`),
    ...forever,
  });

export const useRoute = (city: string, routeIdx: number | null) =>
  useQuery({
    queryKey: ["route", city, routeIdx],
    queryFn: () => api<RouteDetail>(`${base(city)}/routes/${routeIdx}`),
    enabled: routeIdx !== null,
    ...forever,
  });

export const useStops = (city: string) =>
  useQuery({
    queryKey: ["stops", city],
    queryFn: () => api<StopCollection>(`${base(city)}/stops`),
    ...forever,
  });

export const useNetwork = (city: string) =>
  useQuery({
    queryKey: ["network", city],
    queryFn: () => api<Network>(`${base(city)}/network`),
    ...forever,
  });

export const useZones = (city: string) =>
  useQuery({
    queryKey: ["zones", city],
    queryFn: () => api<Zones>(`${base(city)}/zones`),
    ...forever,
  });

export const useAccessibility = (
  city: string,
  result: string,
  percentile: number,
  thresholdMin: number,
  enabled = true,
) =>
  useQuery({
    queryKey: ["accessibility", city, result, percentile, thresholdMin],
    queryFn: () =>
      api<Accessibility>(
        `${base(city)}/results/${result}/accessibility?percentile=${percentile}&threshold_min=${thresholdMin}`,
      ),
    enabled,
    ...forever,
  });

export const useScenarios = (city: string) =>
  useQuery({
    queryKey: ["scenarios", city],
    queryFn: () => api<ScenarioSummary[]>(`${base(city)}/scenarios`),
  });

export const useScenario = (city: string, id: string | null) =>
  useQuery({
    queryKey: ["scenario", city, id],
    queryFn: () => api<ScenarioRecord>(`${base(city)}/scenarios/${id}`),
    enabled: id !== null,
  });

/** Create the scenario, or replace the user's copy of it if it already exists. */
export function useSaveScenario(city: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ scenario, exists }: { scenario: Scenario; exists: boolean }) =>
      exists
        ? api<ScenarioRecord>(`${base(city)}/scenarios/${scenario.scenario_id}`, {
            method: "PATCH",
            // A merge patch with every field replaces the document; dropped optional fields
            // are sent as null so they are removed.
            body: JSON.stringify({ description: null, expected_change: null, ...scenario }),
          })
        : api<ScenarioRecord>(`${base(city)}/scenarios`, {
            method: "POST",
            body: JSON.stringify(scenario),
          }),
    onSuccess: (record) => {
      void client.invalidateQueries({ queryKey: ["scenarios", city] });
      client.setQueryData(["scenario", city, record.scenario.scenario_id], record);
    },
  });
}

export function useStartSimulation(city: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (scenarioId: string) =>
      api<{ job_id: string; status: string }>("/api/simulations", {
        method: "POST",
        body: JSON.stringify({ city, scenario_id: scenarioId }),
      }),
    onSuccess: () => void client.invalidateQueries({ queryKey: ["simulations"] }),
  });
}

const FINISHED = new Set(["completed", "failed", "cancelled"]);

/** Polls every two seconds until the simulation finishes. */
export const useSimulation = (id: string | null) =>
  useQuery({
    queryKey: ["simulation", id],
    queryFn: () => api<Simulation>(`/api/simulations/${id}`),
    enabled: id !== null,
    refetchInterval: (query) =>
      query.state.data && FINISHED.has(query.state.data.status) ? false : 2000,
  });

export function useCancelSimulation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api<Simulation>(`/api/simulations/${id}/cancel`, { method: "POST" }),
    onSuccess: (sim) => client.setQueryData(["simulation", sim.id], sim),
  });
}
