"use client";

/* eslint-disable react-hooks/set-state-in-effect */

import { createContext, useContext, useState, useEffect, ReactNode } from "react";

type Theme = "light" | "dark";

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  accentColor: string;
  setAccentColor: (color: string) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

const ACCENT_COLORS = [
  { name: "Violet", value: "#8B5CF6" },
  { name: "Blue", value: "#3B82F6" },
  { name: "Green", value: "#10B981" },
  { name: "Amber", value: "#F59E0B" },
];

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>("dark");
  const [accentColor, setAccentColorState] = useState("#8B5CF6");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const savedTheme = localStorage.getItem("nima-theme") as Theme;
    const savedAccent = localStorage.getItem("nima-accent-color");
    
    if (savedTheme) {
      setThemeState(savedTheme);
      document.documentElement.classList.toggle("dark", savedTheme === "dark");
      document.documentElement.classList.toggle("light", savedTheme === "light");
    } else {
      document.documentElement.classList.add("dark");
    }
    
    if (savedAccent) {
      setAccentColorState(savedAccent);
      document.documentElement.style.setProperty("--accent-color", savedAccent);
    } else {
      document.documentElement.style.setProperty("--accent-color", "#8B5CF6");
    }
  }, []);

  const setTheme = (newTheme: Theme) => {
    setThemeState(newTheme);
    localStorage.setItem("nima-theme", newTheme);
    document.documentElement.classList.toggle("dark", newTheme === "dark");
    document.documentElement.classList.toggle("light", newTheme === "light");
  };

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  const setAccentColor = (color: string) => {
    setAccentColorState(color);
    localStorage.setItem("nima-accent-color", color);
    document.documentElement.style.setProperty("--accent-color", color);
  };

  const contextValue = {
    theme,
    setTheme,
    accentColor: mounted ? accentColor : "#8B5CF6",
    setAccentColor,
    toggleTheme,
  };

  return (
    <ThemeContext.Provider value={contextValue}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}

export { ACCENT_COLORS };
