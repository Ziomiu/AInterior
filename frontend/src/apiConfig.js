export const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");
export const API_BASE = API_ORIGIN || "/api";

export function configureApiClient(axios) {
  if (!API_ORIGIN) return;

  axios.defaults.baseURL = API_ORIGIN;
  axios.interceptors.request.use((config) => {
    if (config.url?.startsWith("/api/")) {
      config.url = config.url.slice(4);
    }
    return config;
  });
}