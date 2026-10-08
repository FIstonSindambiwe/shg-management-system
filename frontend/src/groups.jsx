import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { useAuth } from "./auth.jsx";

const GroupsContext = createContext(null);

/** The list of groups for the sidebar; leaders only ever receive their own group(s) from the API. */
export function GroupsProvider({ children }) {
  const { user } = useAuth();
  const [groups, setGroups] = useState([]);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(async () => {
    if (!user) { setGroups([]); setLoaded(false); return; }
    const { data } = await api.get("/shgs/?page_size=200");
    setGroups(data.results);
    setLoaded(true);
  }, [user]);

  useEffect(() => { reload().catch(() => setLoaded(true)); }, [reload]);

  return <GroupsContext.Provider value={{ groups, loaded, reload }}>{children}</GroupsContext.Provider>;
}

export function useGroups() {
  return useContext(GroupsContext);
}
