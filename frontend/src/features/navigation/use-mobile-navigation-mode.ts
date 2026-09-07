import { useEffect, useState } from "react";

const mobileNavigationMediaQuery = "(max-width: 899px)";

function mobileNavigationMatches() {
  if (typeof window === "undefined") return false;
  if (typeof window.matchMedia === "function") {
    return window.matchMedia(mobileNavigationMediaQuery).matches;
  }
  return window.innerWidth <= 899;
}

function useMobileNavigationMode() {
  const [isMobile, setIsMobile] = useState(mobileNavigationMatches);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") {
      const update = () => setIsMobile(mobileNavigationMatches());
      window.addEventListener("resize", update);
      return () => window.removeEventListener("resize", update);
    }

    const query = window.matchMedia(mobileNavigationMediaQuery);
    const update = () => setIsMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return isMobile;
}

export {
  mobileNavigationMediaQuery,
  mobileNavigationMatches,
  useMobileNavigationMode,
};
