import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { App } from "./App";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "sonner";
import { ensureAuth } from "./services/api";
import "./index.css";

const queryClient = new QueryClient();

async function bootstrap() {
  // Await JWT before first paint so protected queries do not race as 401
  await ensureAuth();
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <App />
          <Toaster
            theme="dark"
            position="top-right"
            toastOptions={{
              style: {
                background: "#102238",
                border: "1px solid rgba(151,171,199,0.15)",
                color: "#e8edf5",
              },
            }}
          />
        </QueryClientProvider>
      </BrowserRouter>
    </React.StrictMode>
  );
}

void bootstrap();

