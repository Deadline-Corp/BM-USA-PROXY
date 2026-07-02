import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

// All providers (QueryClient, AuthProvider, ToastProvider, BrowserRouter)
// are composed inside App.tsx — keep this entry point a thin mount point.
const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
