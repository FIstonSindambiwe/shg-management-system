import { createContext, useContext, useMemo, useState } from "react";
import { api, tokens } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(tokens.user);

  const value = useMemo(() => ({
    user,
    async login(username, password) {
      const { data } = await api.post("/auth/login/", { username, password });
      tokens.save({ access: data.access, refresh: data.refresh, user: data.user });
      setUser(data.user);
      return data.user;
    },
    logout() {
      tokens.clear();
      setUser(null);
    },
  }), [user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
