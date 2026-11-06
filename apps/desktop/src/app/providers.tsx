import * as React from "react";
import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";

/** App-wide providers. Feature state lives in the zustand stores, not here. */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <TooltipProvider delay={400}>{children}</TooltipProvider>
    </ThemeProvider>
  );
}
