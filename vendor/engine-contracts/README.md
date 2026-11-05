# vendor/engine-contracts — bản chép TẠM

Repo `engine-contracts` chưa tồn tại (05/11/2026). Thư mục này chép lại đúng phần hợp đồng chung trong brief
`video-engine-specs/engine-contracts/docs/spec.md` để `cartoon3d-engine` chạy và test được ngay.

- **Không sửa hợp đồng ở đây.** Khi repo `engine-contracts` lên GitHub: xoá cả thư mục `vendor/`, clone repo thật cạnh repo này
  (`$HOME/engine-contracts`) hoặc đặt biến `ENGINE_CONTRACTS_DIR`. `core/contracts.py` tự tìm theo thứ tự:
  `ENGINE_CONTRACTS_DIR` → `../engine-contracts` → `vendor/engine-contracts`.
- Phần brief không ghi chi tiết và ở đây phải tự chọn (cần chủ dự án chốt khi dựng repo thật):
  - giá trị `sensitivity`: brief chỉ có `none`; tạm dùng `none`, `low`, `medium`, `high`;
  - giá trị `speech_rate`: tạm `slow`, `normal`, `fast`; `emotion` để chuỗi tự do;
  - cấu trúc `qa_report` và `cost` trong `render_output`;
  - codec chuẩn trong `format.json`: tạm `h264` + `yuv420p`;
  - look `test_warm` chỉ có các nhóm token brief liệt kê; chưa có token nét viền (`stroke.width_scale` là tuỳ chọn).
