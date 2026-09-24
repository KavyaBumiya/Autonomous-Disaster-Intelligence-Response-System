import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ensureAuth } from "./services/api";
import "./index.css";

const queryClient = new QueryClient();

// Bootstrap JWT before the first data fetch (best-effort; fails open to login prompt on backend offline)
void ensureAuth();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </BrowserRouter>
  </React.StrictMode>
);
