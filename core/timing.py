"""Quy đổi mili-giây ↔ khung hình. Cả render và cổng G3 dùng chung để không lệch nhau."""
from __future__ import annotations

import math


def round_half_up(x: float) -> int:
    """Làm tròn kiểu Math.round của JS (0.5 lên), không dùng round() của Python (banker's)."""
    return int(math.floor(x + 0.5))


def frames_for(duration_ms: int, fps: int) -> int:
    """Số khung của một đoạn: làm tròn(duration_ms × fps / 1000), tối thiểu 1."""
    return max(1, round_half_up(duration_ms * fps / 1000.0))


def allocate_frames(durations_ms: list[int], fps: int) -> list[int]:
    """Chia tổng số khung của chunk cho từng shot sao cho tổng khớp đúng G3.

    Mỗi shot nhận phần nguyên; phần dư rải theo phần lẻ lớn nhất (largest remainder).
    """
    total = frames_for(sum(durations_ms), fps)
    raw = [d * fps / 1000.0 for d in durations_ms]
    base = [max(1, int(math.floor(r))) for r in raw]
    remainder = total - sum(base)
    if remainder < 0:
        # Quá nhiều shot rất ngắn: bớt dần từ shot dài nhất.
        order = sorted(range(len(base)), key=lambda i: -base[i])
        k = 0
        while remainder < 0:
            i = order[k % len(order)]
            if base[i] > 1:
                base[i] -= 1
                remainder += 1
            k += 1
    else:
        order = sorted(range(len(raw)), key=lambda i: -(raw[i] - math.floor(raw[i])))
        for i in order[:remainder]:
            base[i] += 1
    assert sum(base) == total
    return base


def ms_to_frame(ms_rel: int, fps: int) -> int:
    """Mốc mili-giây tương đối (so với đầu chunk) → chỉ số khung."""
    return round_half_up(ms_rel * fps / 1000.0)


def frame_time(i: int, n: int) -> float:
    """Tham số t ∈ [0, 1] của khung i trong n khung: khung đầu = 0, khung cuối = 1."""
    if n <= 1:
        return 0.0
    return i / (n - 1)
