import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";
import { actionGuidance } from "./decisionLabels";

/**
 * An explicit unavailable or error result.
 *
 * The server's reason is shown verbatim and its `action` token is translated
 * into something the traveler can act on; the raw token is never printed.
 */
export function UnavailableNotice({
  reason,
  code,
  action,
  children,
}: {
  reason?: string;
  code?: string;
  action?: string | null;
  children?: ReactNode;
}) {
  return (
    <section className="setup-outcome unavailable" role="alert">
      <AlertTriangle size={24} />
      <div>
        <h2>Trip analysis unavailable</h2>
        <p>{reason ?? "The analysis could not be completed."}</p>
        {action && <p className="action-guidance">{actionGuidance(action)}</p>}
        {code && <p className="unavailable-code">Reported code: {code}</p>}
        {children}
      </div>
    </section>
  );
}
