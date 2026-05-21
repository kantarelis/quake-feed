import { Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { ApiKeyProvider } from "./context/ApiKeyProvider";
import { AlertConfig } from "./pages/AlertConfig";
import { MapView } from "./pages/MapView";
import { RecentEvents } from "./pages/RecentEvents";

export default function App() {
  return (
    <ApiKeyProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<MapView />} />
          <Route path="recent" element={<RecentEvents />} />
          <Route path="alerts" element={<AlertConfig />} />
        </Route>
      </Routes>
    </ApiKeyProvider>
  );
}
