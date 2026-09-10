import numpy as np
from datetime import datetime, timedelta, timezone


METERS_PER_DEGREE_LAT = 110540.0
METERS_PER_DEGREE_LON = 111320.0


def _parse_iso8601(time_iso):
    """Convert an ISO8601 timestamp into a timezone-aware UTC datetime."""
    if not isinstance(time_iso, str) or not time_iso.strip():
        raise ValueError("t0_iso must be a non-empty ISO8601 string")

    value = time_iso.strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        raise ValueError(
            "t0_iso must include a timezone, for example ...Z"
        )

    return dt.astimezone(timezone.utc)


def _finite_float(value, name):
    """Convert a value to float and reject NaN/infinite values."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a finite number")

    if not np.isfinite(result):
        raise ValueError(f"{name} must be a finite number")

    return result


def _effective_current(u_ms, v_ms, wind):
    """
    Add 3% of the supplied wind vector to the surface-current vector.
    """
    if not hasattr(wind, "__len__") or len(wind) != 2:
        raise ValueError(
            "wind must contain exactly two components: (u, v)"
        )

    wind_u = _finite_float(wind[0], "wind[0]")
    wind_v = _finite_float(wind[1], "wind[1]")

    current_u = _finite_float(u_ms, "u_ms")
    current_v = _finite_float(v_ms, "v_ms")

    return (
        current_u + 0.03 * wind_u,
        current_v + 0.03 * wind_v,
    )


def _step(
    lon,
    lat,
    current_time,
    step_min,
    u_ms,
    v_ms,
    direction=-1,
):
    """
    Move one timestep along the supplied current vector.

    direction = -1 walks BACKWARD in time towards the discharge point, which
    is what attribution needs. direction = +1 walks FORWARD, which is what
    response needs: where the slick will be when a vessel gets there.

    Both are the same integration; only the sign of the displacement and of
    the clock differ, so they cannot drift apart as the model is tuned.

    u_ms = east/west velocity in m/s
    v_ms = north/south velocity in m/s
    """
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 (backward) or +1 (forward)")

    step_seconds = float(step_min) * 60.0

    # Forward displacement during this timestep.
    dx_m = u_ms * step_seconds
    dy_m = v_ms * step_seconds

    # Longitude conversion depends on latitude.
    meters_per_degree_lon = (
        METERS_PER_DEGREE_LON * np.cos(np.radians(lat))
    )

    if abs(meters_per_degree_lon) < 1e-12:
        raise ValueError(
            "longitude conversion became numerically unstable"
        )

    delta_lon = dx_m / meters_per_degree_lon
    delta_lat = dy_m / METERS_PER_DEGREE_LAT

    # Backward advection subtracts the displacement and rewinds the clock;
    # forward advection adds it and advances the clock.
    next_lon = lon + direction * delta_lon
    next_lat = lat + direction * delta_lat

    next_time = current_time + timedelta(
        minutes=direction * step_min
    )

    return (
        float(next_lon),
        float(next_lat),
        next_time,
    )


def _backward_step(lon, lat, current_time, step_min, u_ms, v_ms):
    """Kept so anything already importing this name still works."""
    return _step(
        lon=lon,
        lat=lat,
        current_time=current_time,
        step_min=step_min,
        u_ms=u_ms,
        v_ms=v_ms,
        direction=-1,
    )


def _iso8601_z(dt):
    """Format a UTC datetime as an ISO8601 string ending in Z."""
    return (
        dt.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _run_trajectory(
    head,
    t0,
    hours,
    step_min,
    u_ms,
    v_ms,
    direction=-1,
):
    """Run one deterministic trajectory. direction -1 back, +1 forward."""
    lon = float(head[0])
    lat = float(head[1])
    current_time = t0

    path = [[lon, lat, _iso8601_z(current_time)]]

    n_steps = int(round(hours * 60.0 / step_min))

    for _ in range(n_steps):
        lon, lat, current_time = _step(
            lon=lon,
            lat=lat,
            current_time=current_time,
            step_min=step_min,
            u_ms=u_ms,
            v_ms=v_ms,
            direction=direction,
        )

        path.append(
            [lon, lat, _iso8601_z(current_time)]
        )

    return path


def _run_perturbed_trajectory(
    head,
    t0,
    hours,
    step_min,
    speed,
    heading_rad,
    rng,
    direction=-1,
):
    """
    Run one ensemble trajectory.

    Speed gets Gaussian noise with sigma = 20% of speed.
    Heading gets Gaussian noise with sigma = 15 degrees.
    """
    lon = float(head[0])
    lat = float(head[1])
    current_time = t0

    path = [[lon, lat]]

    n_steps = int(round(hours * 60.0 / step_min))

    speed_sigma = 0.20 * speed
    heading_sigma_rad = np.radians(15.0)

    # Each ensemble member gets one perturbed current.
    perturbed_speed = speed + rng.normal(
        0.0,
        speed_sigma,
    )
    perturbed_speed = max(0.0, perturbed_speed)

    perturbed_heading = (
        heading_rad
        + rng.normal(0.0, heading_sigma_rad)
    )

    perturbed_u = (
        perturbed_speed
        * np.cos(perturbed_heading)
    )
    perturbed_v = (
        perturbed_speed
        * np.sin(perturbed_heading)
    )

    for _ in range(n_steps):
        lon, lat, current_time = _step(
            lon=lon,
            lat=lat,
            current_time=current_time,
            step_min=step_min,
            u_ms=perturbed_u,
            v_ms=perturbed_v,
            direction=direction,
        )

        path.append([lon, lat])

    return path


def _endpoint_uncertainty_km(endpoints):
    """
    Calculate the 90th-percentile distance from ensemble endpoints
    to their mean endpoint.
    """
    points = np.asarray(endpoints, dtype=float)

    mean_lon = float(points[:, 0].mean())
    mean_lat = float(points[:, 1].mean())

    mean_lat_rad = np.radians(mean_lat)

    meters_per_degree_lon = (
        METERS_PER_DEGREE_LON
        * np.cos(mean_lat_rad)
    )

    dx_m = (
        (points[:, 0] - mean_lon)
        * meters_per_degree_lon
    )

    dy_m = (
        (points[:, 1] - mean_lat)
        * METERS_PER_DEGREE_LAT
    )

    distances_km = np.hypot(dx_m, dy_m) / 1000.0

    return float(np.percentile(distances_km, 90))


def back_advect(
    head,
    t0_iso,
    hours=12,
    step_min=30,
    u_ms=-0.25,
    v_ms=-0.12,
    wind=(0.0, 0.0),
    n_ensemble=25,
    seed=0,
    _direction=-1,
):
    """
    Backward-advection estimate of the oil slick's origin.

    _direction is private: forecast() below reuses this whole function with
    +1 so the forward and backward models can never diverge. Call forecast()
    rather than passing it yourself.

    Parameters
    ----------
    head : [lon, lat]
        Current position of the slick head.

    t0_iso : str
        Observation time in ISO8601 format.

    hours : float
        How far backward to trace.

    step_min : float
        Size of each timestep.

    u_ms, v_ms : float
        Surface-current components in m/s.

    wind : (u, v)
        Wind vector in m/s. Three percent of this vector is added
        to the surface current.

    n_ensemble : int
        Number of perturbed trajectories.

    seed : int
        Random seed for reproducible ensemble results.
    """

    # ----------------------------- input validation

    if not hasattr(head, "__len__") or len(head) != 2:
        raise ValueError(
            "head must contain exactly [lon, lat]"
        )

    lon = _finite_float(head[0], "longitude")
    lat = _finite_float(head[1], "latitude")

    if not (-180.0 <= lon <= 180.0):
        raise ValueError(
            "longitude must be between -180 and 180"
        )

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(
            "latitude must be between -90 and 90"
        )

    hours = _finite_float(hours, "hours")
    step_min = _finite_float(step_min, "step_min")

    if hours < 0:
        raise ValueError("hours must be >= 0")

    if step_min <= 0:
        raise ValueError("step_min must be > 0")

    if isinstance(n_ensemble, bool) or not isinstance(
        n_ensemble,
        (int, np.integer),
    ):
        raise ValueError(
            "n_ensemble must be an integer"
        )

    n_ensemble = int(n_ensemble)

    if n_ensemble < 1:
        raise ValueError(
            "n_ensemble must be >= 1"
        )

    total_minutes = hours * 60.0
    step_count = total_minutes / step_min

    if not np.isclose(
        step_count,
        round(step_count),
    ):
        raise ValueError(
            "hours must be evenly divisible by step_min"
        )

    # ----------------------------- time

    t0 = _parse_iso8601(t0_iso)

    # ----------------------------- effective current

    effective_u, effective_v = _effective_current(
        u_ms,
        v_ms,
        wind,
    )

    # ----------------------------- deterministic path

    path = _run_trajectory(
        head=[lon, lat],
        t0=t0,
        hours=hours,
        step_min=step_min,
        u_ms=effective_u,
        v_ms=effective_v,
        direction=_direction,
    )

    # The final point is the estimated origin.
    origin = [
        float(path[-1][0]),
        float(path[-1][1]),
    ]

    origin_time_iso = path[-1][2]

    # ----------------------------- ensemble current

    speed = float(
        np.hypot(
            effective_u,
            effective_v,
        )
    )

    if speed > 0:
        heading_rad = float(
            np.arctan2(
                effective_v,
                effective_u,
            )
        )
    else:
        heading_rad = 0.0

    rng = np.random.default_rng(seed)

    ensemble = []

    for _ in range(n_ensemble):
        trajectory = _run_perturbed_trajectory(
            head=[lon, lat],
            t0=t0,
            hours=hours,
            step_min=step_min,
            speed=speed,
            heading_rad=heading_rad,
            rng=rng,
            direction=_direction,
        )

        ensemble.append(trajectory)

    # ----------------------------- endpoint uncertainty

    endpoints = [
        trajectory[-1]
        for trajectory in ensemble
    ]

    uncertainty_km = _endpoint_uncertainty_km(
        endpoints
    )

    # ----------------------------- output

    forcing = {
        "u_ms": float(u_ms),
        "v_ms": float(v_ms),
        "wind_ms": [float(wind[0]), float(wind[1])],
        "effective_u_ms": float(effective_u),
        "effective_v_ms": float(effective_v),
        "n_ensemble": int(n_ensemble),
    }

    if _direction == 1:
        # Forward: the last point is where the slick is heading, not where
        # it came from, so it is named for what it is.
        return {
            "method": "forward-advection",
            "endpoint": origin,
            "endpoint_time_iso": origin_time_iso,
            "uncertainty_km": uncertainty_km,
            "path": path,
            "ensemble": ensemble,
            "forcing": forcing,
        }

    return {
        "method": "back-advection",
        "origin": origin,
        "origin_time_iso": origin_time_iso,
        "uncertainty_km": uncertainty_km,
        "path": path,
        "ensemble": ensemble,
        "forcing": forcing,
    }


def forecast(
    head,
    t0_iso,
    hours=12,
    step_min=30,
    u_ms=-0.25,
    v_ms=-0.12,
    wind=(0.0, 0.0),
    n_ensemble=25,
    seed=0,
):
    """
    Forward-advection forecast of where the slick will drift.

    Same integration as back_advect, same ensemble, sign flipped. Returns
    "endpoint" and "endpoint_time_iso" instead of "origin", plus the 90th
    percentile spread of the ensemble endpoints as uncertainty_km.

    Attribution needs the origin; response needs this. The problem statement
    asks for both directions.
    """
    return back_advect(
        head=head,
        t0_iso=t0_iso,
        hours=hours,
        step_min=step_min,
        u_ms=u_ms,
        v_ms=v_ms,
        wind=wind,
        n_ensemble=n_ensemble,
        seed=seed,
        _direction=1,
    )


if __name__ == "__main__":
    result = back_advect(
        head=[-89.9, 28.9],
        t0_iso="2026-09-09T12:00:00Z",
    )

    print("origin:", result["origin"])
    print(
        "uncertainty_km:",
        result["uncertainty_km"],
    )
    print(
        "number of path points:",
        len(result["path"]),
    )

    ahead = forecast(
        head=[-89.9, 28.9],
        t0_iso="2026-09-09T12:00:00Z",
    )

    print("endpoint:", ahead["endpoint"])
    print("endpoint_time_iso:", ahead["endpoint_time_iso"])
    print(
        "forecast uncertainty_km:",
        ahead["uncertainty_km"],
    )