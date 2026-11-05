import pytest

from core.timing import allocate_frames, frames_for, ms_to_frame, round_half_up


def test_round_half_up_matches_js_math_round():
    assert round_half_up(100.5) == 101
    assert round_half_up(101.5) == 102
    assert round_half_up(0.4) == 0


def test_frames_for_sample_chunk():
    assert frames_for(4200, 30) == 126  # chunk_sample của engine-contracts
    assert frames_for(1000, 30) == 30
    assert frames_for(1, 30) == 1


@pytest.mark.parametrize("durs", [[4200], [1500, 2700], [1333, 1333, 1334], [700, 700, 700, 2100]])
def test_allocate_frames_sums_to_chunk_total(durs):
    alloc = allocate_frames(durs, 30)
    assert sum(alloc) == frames_for(sum(durs), 30)
    assert all(a >= 1 for a in alloc)


def test_ms_to_frame():
    assert ms_to_frame(0, 30) == 0
    assert ms_to_frame(1000, 30) == 30
