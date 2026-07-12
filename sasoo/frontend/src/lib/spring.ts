/**
 * Critically-damped spring animator (Apple "fluid interface" style), no dependencies.
 *
 * Integrates a mass-spring-damper system with a semi-implicit ("symplectic") Euler
 * step, driven by requestAnimationFrame. `response` follows Apple's convention: the
 * approximate time (in seconds) for the spring to reach the target, and `dampingRatio`
 * of 1.0 is critically damped (no overshoot). Pass a release `velocity` (in value
 * units per second) to hand off momentum from a gesture so motion continues smoothly
 * instead of snapping to a stop.
 */
export interface AnimateSpringOptions {
  /** Starting value. */
  from: number;
  /** Target value the spring settles at. */
  to: number;
  /** Initial velocity in value-units per second (e.g. gesture release velocity). Default 0. */
  velocity?: number;
  /** Apple-style response time in seconds — smaller is snappier. Default 0.3. */
  response?: number;
  /** Damping ratio. 1.0 = critically damped (no overshoot), <1 = bouncy, >1 = sluggish. Default 1.0. */
  dampingRatio?: number;
  /** Settle threshold for |value - to|. Default 0.01. */
  restDisplacement?: number;
  /** Settle threshold for |velocity|. Default 0.01. */
  restVelocity?: number;
  /** Called every animation frame with the current value. */
  onUpdate: (value: number) => void;
  /** Called once when the spring settles at `to`. */
  onSettle?: () => void;
}

/** Starts a critically-damped spring animation. Returns a cancel function. */
export function animateSpring(opts: AnimateSpringOptions): () => void {
  const {
    from,
    to,
    velocity = 0,
    response = 0.3,
    dampingRatio = 1.0,
    restDisplacement = 0.01,
    restVelocity = 0.01,
    onUpdate,
    onSettle,
  } = opts;

  const angularFrequency = (2 * Math.PI) / response;
  const stiffness = angularFrequency * angularFrequency;
  const damping = dampingRatio * 2 * Math.sqrt(stiffness);

  let x = from;
  let v = velocity;
  let lastTime: number | null = null;
  let rafId: number | null = null;
  let cancelled = false;

  const MAX_DT = 1 / 30;

  const step = (time: number) => {
    if (cancelled) return;

    if (lastTime === null) {
      lastTime = time;
    }
    const dt = Math.min((time - lastTime) / 1000, MAX_DT);
    lastTime = time;

    // Semi-implicit (symplectic) Euler: update velocity first, then position
    // using the updated velocity. More stable than explicit Euler for springs.
    const displacement = x - to;
    const acceleration = -stiffness * displacement - damping * v;
    v += acceleration * dt;
    x += v * dt;

    const settled = Math.abs(x - to) < restDisplacement && Math.abs(v) < restVelocity;

    if (settled) {
      onUpdate(to);
      onSettle?.();
      return;
    }

    onUpdate(x);
    rafId = requestAnimationFrame(step);
  };

  rafId = requestAnimationFrame(step);

  return () => {
    cancelled = true;
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  };
}
