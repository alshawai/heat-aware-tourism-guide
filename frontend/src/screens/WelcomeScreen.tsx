import { ArrowRight, Footprints, Hotel, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

export function WelcomeScreen() {
  return (
    <section className="welcome screen">
      <div className="welcome-copy">
        <span className="step-label">
          Heat-aware decisions for outdoor plans
        </span>
        <h1>Plan time outside with clearer heat context.</h1>
        <p>
          Choose a place, inspect the available evidence, and make a more
          informed walking or hotel decision.
        </p>
      </div>
      <div className="feature-grid">
        <Link className="feature-card" to="/walk/location">
          <span className="feature-icon">
            <Footprints />
          </span>
          <div>
            <h2>Plan a walk</h2>
            <p>
              Find a better time, then compare the walking routes returned for
              your trip.
            </p>
          </div>
          <ArrowRight />
        </Link>
        <Link className="feature-card" to="/hotels/location">
          <span className="feature-icon">
            <Hotel />
          </span>
          <div>
            <h2>Rank hotels</h2>
            <p>
              Compare nearby hotels by their modeled outdoor heat exposure
              components.
            </p>
          </div>
          <ArrowRight />
        </Link>
      </div>
      <div className="trust-note">
        <ShieldCheck size={19} />
        <span>
          Local demonstration data only. Results show coverage and confidence so
          limitations stay visible.
        </span>
      </div>
    </section>
  );
}
