import axios from "axios";

const ACCESS = "shg.access";
const REFRESH = "shg.refresh";
const USER = "shg.user";

export const tokens = {
  get access() { return localStorage.getItem(ACCESS); },
  get refresh() { return localStorage.getItem(REFRESH); },
  get user() {
    try { return JSON.parse(localStorage.getItem(USER)); } catch { return null; }
  },
  save({ access, refresh, user }) {
    if (access) localStorage.setItem(ACCESS, access);
    if (refresh) localStorage.setItem(REFRESH, refresh);
    if (user) localStorage.setItem(USER, JSON.stringify(user));
  },
  clear() { [ACCESS, REFRESH, USER].forEach((k) => localStorage.removeItem(k)); },
};

export const api = axios.create({ baseURL: "/api", headers: { "Content-Type": "application/json" } });

api.interceptors.request.use((config) => {
  if (tokens.access) config.headers.Authorization = `Bearer ${tokens.access}`;
  return config;
});

// One silent retry with a refreshed token before sending the leader back to the login screen.
api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config || {};
    const isLogin = original.url?.includes("/auth/");
    if (error.response?.status === 401 && !original._retried && !isLogin && tokens.refresh) {
      original._retried = true;
      try {
        const { data } = await axios.post("/api/auth/refresh/", { refresh: tokens.refresh });
        tokens.save({ access: data.access, refresh: data.refresh });
        original.headers.Authorization = `Bearer ${data.access}`;
        return api(original);
      } catch {
        tokens.clear();
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

/** Readable message from a DRF error body. */
export function errorText(error) {
  const d = error?.response?.data;
  if (!d) return error?.message || "Network error";
  if (typeof d === "string") return d;
  if (d.detail) return d.detail;
  const parts = [];
  for (const [field, value] of Object.entries(d)) {
    if (field === "rows") continue;
    parts.push(Array.isArray(value) ? `${field}: ${value.join(" ")}` : `${field}: ${value}`);
  }
  return parts.join(" | ") || "Something went wrong";
}
