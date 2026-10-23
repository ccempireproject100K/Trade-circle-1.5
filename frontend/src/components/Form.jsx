// Small form pieces shared by the dashboard screens.

export function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  );
}

export function Notice({ error, ok }) {
  if (error) return <p className="notice notice-error" role="alert">{error}</p>;
  if (ok) return <p className="notice notice-ok" role="status">{ok}</p>;
  return null;
}
