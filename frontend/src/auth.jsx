import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { acting, api } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  // undefined while checking the session, null when signed out.
  const [user, setUser] = useState(undefined);
  const [profile, setProfile] = useState(null);

  const refresh = useCallback(async () => {
    try {
      // The member's own account, never a business they're working for.
      const [me, mine] = await Promise.all([api("/me"), api("/me/profile", { own: true })]);
      setUser(me);
      setProfile(mine);
    } catch {
      setUser(null);
      setProfile(null);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = async (email, password) => {
    await api("/auth/login", { method: "POST", body: { email, password } });
    await refresh();
  };

  const signup = async (fields) => {
    await api("/auth/signup", { method: "POST", body: fields });
    await refresh();
  };

  const logout = async () => {
    await api("/auth/logout", { method: "POST" });
    acting.set(null);
    setUser(null);
    setProfile(null);
  };

  return (
    <AuthContext.Provider value={{ user, profile, setProfile, refresh, login, signup, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);

// For tests: a signed-in member without network calls.
export function AuthStubProvider({ children, user = { id: "u1", email: "a@example.com", role: "contractor", tier: "free" } }) {
  return <AuthContext.Provider value={{ user, profile: { slug: "a", business_name: "Alpha" } }}>{children}</AuthContext.Provider>;
}
