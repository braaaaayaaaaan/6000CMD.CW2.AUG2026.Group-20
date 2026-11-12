import { Provider } from "@/styles/ui/provider";
import "../styles/globals.css";

export const metadata = { title: "ManticAI | Digital Asset Management" };

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body><Provider>{children}</Provider></body>
    </html>
  );
}
