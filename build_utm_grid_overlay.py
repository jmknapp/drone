#!/usr/bin/env python3
"""
Overlay a perspective-correct UTM grid (100 ft intervals) on DJI drone video
using SRT telemetry and OpenCV. Projects a 3D ground grid into each frame
based on camera pose (position + gimbal orientation).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

try:
    import utm
    _HAS_UTM = True
except ImportError:
    _HAS_UTM = False

# Reuse SRT parsing and Euler conversion from HUD overlay
from build_hud_overlay import parse_srt_block, quat_to_euler_deg

# Grid spacing: 100 ft ≈ 30.48 m
GRID_SPACING_M = 30.48

# DJI NEO2: ~119.8° diagonal FOV. For 1920×1080, estimate fx from diagonal FOV.
# diag = sqrt(1920² + 1080²) ≈ 2203; f = diag / (2*tan(59.9°)) ≈ 637
DEFAULT_FX = 637.0
DEFAULT_FY = 637.0


# ENU (East-North-Up) to NED (North-East-Down). DJI uses NED for gimbal quaternion.
# ENU: X=East, Y=North, Z=Up. NED: X=North, Y=East, Z=Down.
# So NED_x=ENU_y, NED_y=ENU_x, NED_z=-ENU_z.
T_ENU_TO_NED = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]], dtype=np.float64)


def quat_to_rotation_matrix(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    """Quaternion (w,x,y,z) to 3×3 rotation matrix (camera-to-body)."""
    R = np.array([
        [1 - 2 * (qy**2 + qz**2), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx**2 + qz**2), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx**2 + qy**2)],
    ], dtype=np.float64)
    return R


def get_telemetry_at_time(records: list[dict], t_sec: float) -> dict | None:
    """Return telemetry record whose [start,end) contains t_sec, or nearest."""
    for rec in records:
        if rec["start"] <= t_sec < rec["end"]:
            return rec
    # Fallback: nearest by start time
    if not records:
        return None
    best = min(records, key=lambda r: abs(r["start"] - t_sec))
    return best


def rotation_z_rad(angle_rad: float) -> np.ndarray:
    """Right-handed rotation about Z axis by angle_rad radians."""
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def compute_headings_rad(records: list[dict]) -> list[float | None]:
    """
    Estimate heading (radians from North, NED convention) for each record from
    position deltas. Needed because pp_target is gimbal-in-body; body yaw is missing.
    """
    if not _HAS_UTM:
        return [None] * len(records)
    out: list[float | None] = [None] * len(records)
    utm_cache: list[tuple[float, float] | None] = [None] * len(records)
    for i, r in enumerate(records):
        try:
            lat = float(r["lat"])
            lon = float(r["lon"])
            e, n, _, _ = utm.from_latlon(lat, lon)
            utm_cache[i] = (e, n)
        except (ValueError, TypeError):
            pass
    for i in range(1, len(records) - 1):
        prev = utm_cache[i - 1]
        curr = utm_cache[i]
        next_ = utm_cache[i + 1]
        if prev is None or curr is None or next_ is None:
            continue
        # Use symmetric derivative for stability
        de = (next_[0] - prev[0]) / 2.0
        dn = (next_[1] - prev[1]) / 2.0
        if de * de + dn * dn < 1e-6:
            out[i] = out[i - 1] if out[i - 1] is not None else 0.0
            continue
        # NED: North=X, East=Y. heading = atan2(East, North) = atan2(de, dn)
        out[i] = float(np.arctan2(de, dn))
    if len(records) >= 2 and out[1] is not None:
        out[0] = out[1]
    if len(records) >= 2 and out[-2] is not None:
        out[-1] = out[-2]
    return out


def build_utm_grid(
    center_e: float, center_n: float, ground_alt: float,
    half_extent_m: float, spacing_m: float
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """
    Build 3D UTM grid lines on ground plane.
    Returns (east_lines, north_lines) where each is a list of (p0, p1) as (e,n,u) arrays.
    """
    east_lines: list[tuple[np.ndarray, np.ndarray]] = []
    north_lines: list[tuple[np.ndarray, np.ndarray]] = []

    # Snap to grid
    base_e = np.floor(center_e / spacing_m) * spacing_m
    base_n = np.floor(center_n / spacing_m) * spacing_m
    e_min = base_e - half_extent_m
    e_max = base_e + half_extent_m
    n_min = base_n - half_extent_m
    n_max = base_n + half_extent_m

    # East-west lines (constant northing)
    n_val = base_n
    while n_val <= n_max:
        east_lines.append((
            np.array([e_min, n_val, ground_alt]),
            np.array([e_max, n_val, ground_alt]),
        ))
        n_val += spacing_m
    n_val = base_n - spacing_m
    while n_val >= n_min:
        east_lines.append((
            np.array([e_min, n_val, ground_alt]),
            np.array([e_max, n_val, ground_alt]),
        ))
        n_val -= spacing_m

    # North-south lines (constant easting)
    e_val = base_e
    while e_val <= e_max:
        north_lines.append((
            np.array([e_val, n_min, ground_alt]),
            np.array([e_val, n_max, ground_alt]),
        ))
        e_val += spacing_m
    e_val = base_e - spacing_m
    while e_val >= e_min:
        north_lines.append((
            np.array([e_val, n_min, ground_alt]),
            np.array([e_val, n_max, ground_alt]),
        ))
        e_val -= spacing_m

    return east_lines, north_lines


def project_utm_to_pixel_nadir(
    easting: float, northing: float,
    cam_easting: float, cam_northing: float, cam_alt: float, ground_alt: float,
    heading_rad: float, fx: float, fy: float, cx: float, cy: float,
    width: int, height: int,
) -> tuple[int, int] | None:
    """
    Orthographic projection for nadir (straight-down) view.
    Image center = drone UTM position. Scale = fx/h. Image 'up' = heading direction.
    """
    de = easting - cam_easting
    dn = northing - cam_northing
    h = cam_alt - ground_alt
    if h < 0.1:
        return None
    scale = fx / h
    c, s = np.cos(heading_rad), np.sin(heading_rad)
    u = cx + scale * (de * c - dn * s)
    v = cy - scale * (de * s + dn * c)
    if -width * 0.2 <= u <= width * 1.2 and -height * 0.2 <= v <= height * 1.2:
        return (int(round(u)), int(round(v)))
    return None


def horizon_row(u: float, cx: float, cy: float, fx: float, fy: float, R_w2c: np.ndarray, height: int) -> float:
    """
    Return the v-coordinate of the horizon at column u. Points with v < this are sky.
    When looking straight down, returns large negative (all points below horizon).
    """
    r02, r12, r22 = R_w2c[0, 2], R_w2c[1, 2], R_w2c[2, 2]
    if abs(r12) < 1e-6:
        return -1e6  # Looking down/up: no horizon, treat all as ground
    v_h = cy - fy * ((u - cx) / fx * r02 + r22) / r12
    return v_h


def project_line(
    p_world: np.ndarray, cam_pos: np.ndarray, R_w2c: np.ndarray,
    fx: float, fy: float, cx: float, cy: float,
    width: int, height: int,
    z_flip: bool = False,
) -> list[tuple[int, int]]:
    """
    Project 3D points to 2D image coords. Returns list of (u,v) that are in front
    of camera, below the horizon (not sky), and within frame. z_flip: if True,
    treat negative Z as in-front (camera convention variant).
    """
    pts = []
    for p in p_world:
        p_cam = R_w2c @ (p - cam_pos)
        z = -p_cam[2] if z_flip else p_cam[2]
        if z <= 1e-6:
            continue
        u = fx * p_cam[0] / z + cx
        v = fy * p_cam[1] / z + cy
        v_h = horizon_row(u, cx, cy, fx, fy, R_w2c, height)
        if v < v_h + 2:
            continue  # Above horizon (sky)
        if -width * 0.2 <= u <= width * 1.2 and -height * 0.2 <= v <= height * 1.2:
            pts.append((int(round(u)), int(round(v))))
    return pts


def draw_grid_on_frame(
    frame: np.ndarray,
    records: list[dict],
    headings: list[float | None],
    use_heading: bool,
    frame_idx: int,
    fps: float,
    cx: float, cy: float, fx: float, fy: float,
    ground_alt: float,
    half_extent_m: float,
    zone_num: int, zone_letter: str,
    color: tuple[int, int, int] = (0, 255, 0),
    thickness: int = 1,
) -> np.ndarray:
    """Draw UTM grid on a single frame."""
    t_sec = frame_idx / fps if fps > 0 else 0.0
    rec = get_telemetry_at_time(records, t_sec)
    if not rec or not rec.get("lat") or not rec.get("lon") or rec.get("quat_w") is None:
        return frame

    try:
        lat = float(rec["lat"])
        lon = float(rec["lon"])
        alt = float(rec["abs_alt"]) if rec["abs_alt"] else 0.0
    except (ValueError, TypeError):
        return frame

    if not _HAS_UTM:
        return frame

    try:
        easting, northing, zn, zl = utm.from_latlon(lat, lon)
    except Exception:
        return frame

    R_c2w = quat_to_rotation_matrix(
        rec["quat_w"], rec["quat_x"], rec["quat_y"], rec["quat_z"]
    )
    _, pitch_deg, _ = quat_to_euler_deg(
        rec["quat_w"], rec["quat_x"], rec["quat_y"], rec["quat_z"]
    )
    rec_idx = records.index(rec) if rec in records else 0
    heading = headings[rec_idx] if rec_idx < len(headings) and headings[rec_idx] is not None else 0.0

    east_lines, north_lines = build_utm_grid(
        easting, northing, ground_alt, half_extent_m, GRID_SPACING_M
    )

    h, w = frame.shape[:2]

    # Compute R_w2c for horizon (and tilted path). Draw red horizon line when visible.
    if use_heading:
        R_ned2body = rotation_z_rad(heading)
        R_w2c = (R_c2w.T) @ R_ned2body @ T_ENU_TO_NED
    else:
        R_w2c = (R_c2w.T) @ T_ENU_TO_NED
    r02, r12, r22 = R_w2c[0, 2], R_w2c[1, 2], R_w2c[2, 2]
    if abs(r12) >= 1e-6:
        v0 = horizon_row(0, cx, cy, fx, fy, R_w2c, h)
        v1 = horizon_row(w - 1, cx, cy, fx, fy, R_w2c, h)
        pt0 = (0, int(round(np.clip(v0, 0, h - 1))))
        pt1 = (w - 1, int(round(np.clip(v1, 0, h - 1))))
        cv2.line(frame, pt0, pt1, (0, 0, 255), 2, cv2.LINE_AA)

    # Use simple 2D orthographic projection when looking straight down (pitch < -80°)
    if pitch_deg < -80:
        def project_nadir(p: np.ndarray) -> tuple[int, int] | None:
            return project_utm_to_pixel_nadir(
                p[0], p[1], easting, northing, alt, ground_alt,
                heading, fx, fy, cx, cy, w, h,
            )

        for (p0, p1) in east_lines + north_lines:
            pt0 = project_nadir(p0)
            pt1 = project_nadir(p1)
            if pt0 is not None and pt1 is not None:
                cv2.line(frame, pt0, pt1, color, thickness, cv2.LINE_AA)
        return frame

    # Tilted view: use 3D perspective projection (R_w2c already computed above)
    z_flip = pitch_deg < -75
    cam_pos = np.array([easting, northing, alt], dtype=np.float64)

    def clip_to_frame(pts: list[tuple[int, int]]) -> list[tuple[int, int]]:
        out = []
        for (u, v) in pts:
            u_clip = max(0, min(w - 1, u))
            v_clip = max(0, min(h - 1, v))
            out.append((u_clip, v_clip))
        return out

    def draw_lines(lines: list) -> None:
        for (p0, p1) in lines:
            pts = project_line(
                np.array([p0, p1]), cam_pos, R_w2c, fx, fy, cx, cy, w, h, z_flip
            )
            if len(pts) == 2:
                cv2.line(frame, pts[0], pts[1], color, thickness, cv2.LINE_AA)
            elif len(pts) == 1:
                # One endpoint behind camera: extend to frame edge
                p0_cam = R_w2c @ (np.array(p0) - cam_pos)
                p1_cam = R_w2c @ (np.array(p1) - cam_pos)
                z0 = -p0_cam[2] if z_flip else p0_cam[2]
                z1 = -p1_cam[2] if z_flip else p1_cam[2]
                if z0 > 1e-6 and z1 <= 1e-6:
                    t = (1e-6 - z1) / (z0 - z1)
                    p_mid = p0_cam * t + p1_cam * (1 - t)
                    zm = -p_mid[2] if z_flip else p_mid[2]
                    u = fx * p_mid[0] / zm + cx
                    v = fy * p_mid[1] / zm + cy
                    if 0 <= u < w and 0 <= v < h:
                        cv2.line(frame, pts[0], (int(u), int(v)), color, thickness, cv2.LINE_AA)
                elif z1 > 1e-6 and z0 <= 1e-6:
                    t = (1e-6 - z0) / (z1 - z0)
                    p_mid = p1_cam * t + p0_cam * (1 - t)
                    zm = -p_mid[2] if z_flip else p_mid[2]
                    u = fx * p_mid[0] / zm + cx
                    v = fy * p_mid[1] / zm + cy
                    if 0 <= u < w and 0 <= v < h:
                        cv2.line(frame, (int(u), int(v)), pts[0], color, thickness, cv2.LINE_AA)

    draw_lines(east_lines)
    draw_lines(north_lines)

    return frame


def load_srt_records(srt_path: Path) -> list[dict]:
    """Parse SRT file into list of telemetry records."""
    content = srt_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\n+", content)
    records: list[dict] = []
    for block in blocks:
        if not block.strip():
            continue
        rec = parse_srt_block(block)
        if rec:
            records.append(rec)
    return records


def run(
    video_path: Path,
    srt_path: Path,
    out_path: Path,
    *,
    ground_alt: float | None = None,
    half_extent_m: float = 200.0,
    fx: float = DEFAULT_FX,
    fy: float = DEFAULT_FY,
    color: tuple[int, int, int] = (0, 255, 0),
    thickness: int = 1,
    use_heading: bool = True,
    progress: bool = True,
) -> None:
    """Process video and write output with UTM grid overlay."""
    if not _HAS_UTM:
        raise SystemExit("utm package required. Install with: pip install utm")

    records = load_srt_records(srt_path)
    if not records:
        raise SystemExit(f"No telemetry records found in {srt_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    cx = w / 2.0
    cy = h / 2.0

    # Infer ground altitude if not provided. Must be below camera so projected points
    # have positive Z in camera frame. Use min(AGL=0 level) minus small offset so
    # grid is always below camera, even when drone is on ground (rel_alt=0).
    if ground_alt is None:
        min_ground = float("inf")
        for r in records:
            try:
                alt = float(r["abs_alt"]) if r.get("abs_alt") else 0.0
                rel = float(r["rel_alt"]) if r.get("rel_alt") else 0.0
                min_ground = min(min_ground, alt - rel)
            except (ValueError, TypeError):
                pass
        ground_alt = min_ground - 0.5 if min_ground != float("inf") else 0.0

    # Get UTM zone from first valid position
    zone_num, zone_letter = 17, "T"
    if records[0].get("lat") and records[0].get("lon"):
        try:
            _, _, zone_num, zone_letter = utm.from_latlon(
                float(records[0]["lat"]), float(records[0]["lon"])
            )
        except Exception:
            pass

    headings = compute_headings_rad(records)

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.0",
        "-an", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    frame_idx = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frame = draw_grid_on_frame(
                frame, records, headings, use_heading, frame_idx, fps,
                cx, cy, fx, fy, ground_alt, half_extent_m,
                zone_num, zone_letter, color, thickness,
            )
            proc.stdin.write(frame.tobytes())
            if progress and total_frames > 0 and (frame_idx + 1) % 30 == 0:
                pct = 100 * (frame_idx + 1) / total_frames
                print(f"\r  Frame {frame_idx + 1}/{total_frames} ({pct:.1f}%)", end="", file=sys.stderr)
            frame_idx += 1
    finally:
        try:
            proc.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass
        proc.wait()
        stderr = proc.stderr.read() if proc.stderr else b""
        if proc.stderr:
            proc.stderr.close()
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise SystemExit(f"ffmpeg failed (exit {proc.returncode}):\n{err[-2000:]}")

    cap.release()
    if progress:
        print(file=sys.stderr)
    print(f"Wrote {frame_idx} frames to {out_path}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Overlay perspective UTM grid (100 ft) on DJI video using SRT telemetry.",
    )
    p.add_argument("base", type=str, help="Base name (script uses .srt, .mp4); output: BASE_utm_grid.mp4")
    p.add_argument("-o", "--output", type=str, help="Output path (default: BASE_utm_grid.mp4)")
    p.add_argument("--ground-alt", type=float, help="Ground plane altitude in m (default: first frame AGL=0)")
    p.add_argument("--extent", type=float, default=200, help="Half extent of grid in m (default: 200)")
    p.add_argument("--fx", type=float, default=DEFAULT_FX, help=f"Camera focal length x (default: {DEFAULT_FX})")
    p.add_argument("--fy", type=float, default=DEFAULT_FY, help=f"Camera focal length y (default: {DEFAULT_FY})")
    p.add_argument("--thickness", type=int, default=1, help="Line thickness (default: 1)")
    p.add_argument("--no-heading", action="store_true", help="Don't add heading from velocity (try if grid rotates wrongly)")
    p.add_argument("-q", "--quiet", action="store_true", help="Suppress progress output")
    args = p.parse_args()

    base = Path(args.base)
    srt_path = base.with_suffix(".srt")
    if not srt_path.exists():
        srt_path = base.with_suffix(".SRT")
    if not srt_path.exists():
        raise SystemExit(f"SRT not found: {base.with_suffix('.srt')}")

    mp4_path = base.with_suffix(".mp4")
    if not mp4_path.exists():
        mp4_path = base.with_suffix(".MP4")
    if not mp4_path.exists():
        raise SystemExit(f"MP4 not found: {base.with_suffix('.mp4')}")

    out_path = Path(args.output) if args.output else base.with_name(base.stem + "_utm_grid.mp4")

    run(
        mp4_path,
        srt_path,
        out_path,
        ground_alt=args.ground_alt,
        half_extent_m=args.extent,
        fx=args.fx,
        fy=args.fy,
        thickness=args.thickness,
        use_heading=not args.no_heading,
        progress=not args.quiet,
    )


if __name__ == "__main__":
    main()
