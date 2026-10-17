import type { Metadata, Viewport } from "next";
import React from "react";

export const metadata: Metadata = {
  title: "MedLearn AI — Interactive Medical Education & Anatomy Explorer",
  description:
    "AI-powered medical education platform for students and educators. Explore pathophysiology, 3D anatomical models, and cellular mechanisms. Educational only — not medical advice.",
  keywords: [
    "medical education",
    "pathophysiology",
    "anatomy",
    "AI tutor",
    "medical student",
    "interactive 3D body",
  ],
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;0,8..60,700;1,8..60,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body
        style={{
          margin: 0,
          padding: 0,
          backgroundColor: "#fcfbf7",
          color: "#121b28",
          fontFamily:
            'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
          WebkitFontSmoothing: "antialiased",
          MozOsxFontSmoothing: "grayscale",
        }}
      >
        {children}
      </body>
    </html>
  );
}
