import type { ReactNode } from "react";
import "../../styles/globals.css";

export default function LoginLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body className="m-0 min-h-screen font-sans bg-background-primary text-text-primary px-6">
        {children}
      </body>
    </html>
  );
}
