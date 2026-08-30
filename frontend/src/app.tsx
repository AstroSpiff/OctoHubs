import { lazy, Suspense, type ComponentType } from "react";
import { createBrowserRouter, createRoutesFromElements, Navigate, Outlet, Route, RouterProvider, useLocation } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { configurationPath, configurationTabFromHash } from "@/features/configuration/configuration-navigation";
import { probePath, probeScopeFromHash } from "@/features/probe/probe-navigation";
import { researchPath, researchTabFromHash } from "@/features/research/research-navigation";

const CollectionsPage = lazyPage(() => import("@/pages/collections-page"), "CollectionsPage");
const ConfigurationPage = lazyPage(() => import("@/pages/configuration-page"), "ConfigurationPage");
const LibrariesPage = lazyPage(() => import("@/pages/libraries-page"), "LibrariesPage");
const LatestPage = lazyPage(() => import("@/pages/latest-page"), "LatestPage");
const EmbyLivePage = lazyPage(() => import("@/pages/emby-live-page"), "EmbyLivePage");
const ProbePage = lazyPage(() => import("@/pages/probe-page"), "ProbePage");
const ResearchPage = lazyPage(() => import("@/pages/research-page"), "ResearchPage");
const StreamStatsPage = lazyPage(() => import("@/pages/stream-stats-page"), "StreamStatsPage");
const TranscodeGuardPage = lazyPage(() => import("@/pages/transcode-guard-page"), "TranscodeGuardPage");
const TranscodeGuardSettingsPage = lazyPage(() => import("@/pages/transcode-guard-settings-page"), "TranscodeGuardSettingsPage");
const UsersPage = lazyPage(() => import("@/pages/users-page"), "UsersPage");
const UserIconsPage = lazyPage(() => import("@/pages/user-icons-page"), "UserIconsPage");

const router = createBrowserRouter(
  createRoutesFromElements(
    <Route element={<AppShell />}>
      <Route element={<Suspense fallback={<div className="route-loading" role="status">Caricamento sezione...</div>}><Outlet /></Suspense>}>
        <Route index element={<Navigate replace to="/emby-live" />} />
        <Route path="emby-live" element={<EmbyLivePage />} />
        <Route path="operations" element={<Navigate replace to="/emby-live" />} />
        <Route path="event-bridge" element={<Navigate replace to={configurationPath("event-bridge")} />} />
        <Route path="transcode-guard" element={<TranscodeGuardPage />} />
        <Route path="transcode-guard/rules" element={<TranscodeGuardSettingsPage />} />
        <Route path="stream-stats" element={<StreamStatsPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="users/icons" element={<UserIconsPage />} />
        <Route path="collections" element={<CollectionsPage />} />
        <Route path="libraries" element={<LibrariesPage />} />
        <Route path="latest" element={<LatestPage />} />
        <Route path="probe">
          <Route index element={<LegacySectionRedirect toPath={(hash) => probePath(probeScopeFromHash(hash))} />} />
          <Route path=":scope" element={<ProbePage />} />
        </Route>
        <Route path="research">
          <Route index element={<LegacySectionRedirect toPath={(hash) => researchPath(researchTabFromHash(hash))} />} />
          <Route path=":tab" element={<ResearchPage />} />
        </Route>
        <Route path="configuration">
          <Route index element={<LegacySectionRedirect toPath={(hash) => configurationPath(configurationTabFromHash(hash))} />} />
          <Route path=":tab" element={<ConfigurationPage />} />
        </Route>
        <Route path="*" element={<Navigate replace to="/emby-live" />} />
      </Route>
    </Route>,
  ),
  { basename: "/app" },
);

function App() {
  return <RouterProvider router={router} />;
}

function LegacySectionRedirect({ toPath }: { toPath: (hash: string) => string }) {
  const { hash, search } = useLocation();
  return <Navigate replace to={{ pathname: toPath(hash), search }} />;
}

function lazyPage<Module, Key extends keyof Module>(load: () => Promise<Module>, exportName: Key) {
  return lazy(async () => ({ default: (await load())[exportName] as ComponentType }));
}

export { App };
