import * as React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/app";
import { Providers } from "./app/providers";
import "./index.css";
// Applies the stored accent, fonts and motion before the first render.
import "./stores/appearance-store";

function bootstrap() {
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <Providers>
        <App />
      </Providers>
    </React.StrictMode>,
  );
}

void bootstrap();
