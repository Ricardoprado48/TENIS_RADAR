import { Route, Routes } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import HomePage from "./pages/HomePage";
import CalendarPage from "./pages/CalendarPage";
import RadarPage from "./pages/RadarPage";
import ScreenshotUploadPage from "./pages/ScreenshotUploadPage";
import ForwardPage from "./pages/ForwardPage";
import ForwardPredictionDetailPage from "./pages/ForwardPredictionDetailPage";
import PlaceholderPage from "./pages/PlaceholderPage";

function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<HomePage />} />
        <Route path="/calendario" element={<CalendarPage />} />
        <Route path="/radar" element={<RadarPage />} />
        <Route path="/prints/:matchKey" element={<ScreenshotUploadPage />} />
        <Route path="/forward" element={<ForwardPage />} />
        <Route path="/forward/:predictionId" element={<ForwardPredictionDetailPage />} />
        <Route path="/configuracoes" element={<PlaceholderPage title="Configurações" />} />
      </Route>
    </Routes>
  );
}

export default App;
