"""
Shared velocity filters: median and trimmed-mean for noise reduction.
Used by build_hud_overlay (HUD display) and export_velocity_csv (CSV export).
"""

MEDIAN_WINDOW = 7
TRIMMED_WINDOW = 21
TRIM = 0  # 0 = use TRIMMED_WINDOW // 5


def median_filter(values: list[float | None], window: int) -> list[float | None]:
    """
    Apply median filter. Rejects spikes and fills short zero/low runs.
    Uses only valid (non-None) values in each window; output None if window has no valid values.
    """
    if window < 1:
        return list(values)
    half = window // 2
    out: list[float | None] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        win = [v for v in values[lo:hi] if v is not None]
        if win:
            win_sorted = sorted(win)
            out.append(win_sorted[len(win_sorted) // 2])
        else:
            out.append(None)
    return out


def trimmed_mean_filter(
    values: list[float | None], window: int, trim: int
) -> list[float | None]:
    """
    Trimmed mean: drop trim highest and trim lowest in each window, average the rest.
    Produces nearly constant velocity in steady stretches by rejecting spikes and dips.
    """
    if window < 1 or trim < 0:
        return list(values)
    half = window // 2
    out: list[float | None] = []
    for i in range(len(values)):
        lo = max(0, i - half)
        hi = min(len(values), i + half + 1)
        win = sorted([v for v in values[lo:hi] if v is not None])
        k = min(trim, len(win) // 2)
        if len(win) > 2 * k:
            trimmed = win[k : len(win) - k]
            out.append(sum(trimmed) / len(trimmed))
        elif win:
            out.append(sum(win) / len(win))
        else:
            out.append(None)
    return out


def apply_velocity_filter(values: list[float | None]) -> list[float | None]:
    """
    Apply default velocity filter: median then trimmed mean (same as export_velocity_csv default).
    """
    result = median_filter(values, MEDIAN_WINDOW)
    k = TRIM if TRIM > 0 else max(1, TRIMMED_WINDOW // 5)
    result = trimmed_mean_filter(result, TRIMMED_WINDOW, k)
    return result


def apply_vertical_velocity_filter(values: list[float | None]) -> list[float | None]:
    """
    Filter for vertical (climb) velocity. No median (it zeroes when zeros dominate).
    Only output 0.0 if many consecutive zeros (genuine hover); else carry forward last non-zero.
    """
    ZERO_THRESH = 0.15  # m/s; treat as zero
    MIN_ZEROS_FOR_REAL = 30  # ~1 s at 30 fps; end-of-descent can have many zeros in a row
    out: list[float | None] = []
    last_nonzero: float | None = None
    consecutive_zeros = 0
    for v in values:
        if v is None:
            out.append(None)
            continue
        if abs(v) <= ZERO_THRESH:
            consecutive_zeros += 1
            if consecutive_zeros >= MIN_ZEROS_FOR_REAL:
                out.append(0.0)
            else:
                out.append(last_nonzero if last_nonzero is not None else 0.0)
        else:
            consecutive_zeros = 0
            last_nonzero = v
            out.append(v)
    return out
