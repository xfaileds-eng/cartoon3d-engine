"""Chạy bộ test chung của engine-contracts trên engine này (fixture chunk_sample: 4,2 s, 30 fps = 126 khung)."""
from common.contract_suite import (  # noqa: F401
    test_format,
    test_frame_count_exact,
    test_input_schema_valid,
    test_no_black_frames,
    test_no_burned_captions,
    test_output_schema_valid,
    test_port_mock_roundtrip,
    test_port_rate_limit_policy,
)
