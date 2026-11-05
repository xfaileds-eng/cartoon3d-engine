# AGENTS.md — luật riêng của `cartoon3d-engine`

Kế thừa luật chung ở repo `agent-rules` (`$HOME/agent-rules/AGENTS.md`). File này chỉ ghi phần riêng của repo.
Nguồn sự thật về phạm vi: [`docs/spec.md`](docs/spec.md) (spec cartoon3d) và `engine-contracts/docs/spec.md` (hợp đồng chung).

**Ngoại lệ so với luật chung:**
- Tên file dữ liệu dùng `snake_case` thay cho slug gạch nối khi tên file chính là id tra cứu: `chunk_input.schema.json`,
  `capability_card.json`, `cheese_vault.json` (= `asset_id`), `test_warm.json` (= `look_id`). Lý do: tên do brief
  `engine-contracts` chốt, và id trong JSON là `snake_case` theo mục 2.2 nên tên file phải trùng id.
- Thư mục `vendor/engine-contracts/` là bản chép tạm của repo khác (xem mục dưới), không phải code của repo này.

## Vai trò của repo

- Một engine trong roster của video engine: nhận `chunk_input` từ nhạc trưởng, trả `render_output` + video hoạt hình 3D
  dựng bằng code, **đúng thời lượng chunk**. Không chia SRT, không lồng tiếng, không ghép chunk, không quét lời thoại.
- **Không in phụ đề.** Phụ đề in một lần ở khâu ghép (luật chung chốt 05/11/2026). Cổng C-no-captions và G8 dùng OCR để chặn.
- Bản gốc của mọi thứ là file chữ (JSON + script). Video, khung hình, contact sheet nằm trong `out/`, không đưa lên Git.

## Hợp đồng dữ liệu (không tự ý đổi)

- `chunk_input`, `render_output`, `capability_card`, `format.json`, `looks/`, `ports/` thuộc repo **`engine-contracts`**, không copy
  vào `specs/`. `core/contracts.py` tìm theo thứ tự `ENGINE_CONTRACTS_DIR` → `../engine-contracts` → `vendor/engine-contracts`.
- `vendor/engine-contracts/` là bản chép tạm từ brief vì repo thật chưa có. **Không sửa hợp đồng ở đó**; khi repo thật lên
  GitHub thì xoá cả `vendor/` và chạy lại `pytest -q`.
- Hai schema riêng nằm trong `specs/`: `shot` (engine tự lập) và `asset` (sổ tài sản). Đổi trường = đổi schema + fixture + test
  cùng một commit.
- `chunk_id` = mốc mili-giây 9 chữ số + `_` + số thứ tự 3 chữ số; `shot_id` = `chunk_id` + `_s<n>`.
- `interp` dùng **tên của Blender**; lưu ý "Ease In" của Blender = chậm ở đầu đoạn, ngược nghĩa "Easy Ease In" của After Effects.
- `sensitivity_device` chỉ nhận 6 giá trị trong `specs/shot.schema.json`; mức nào dùng thủ pháp nào nằm ở `core/sensitivity/table.json`.
- fps, độ phân giải, codec lấy từ `format.json` theo `aspect`, không hard-code trong engine.
- Hai backend (`threejs`, `blender`) cùng ăn một `scene_bundle.json`. Track máy quay, vị trí nhân vật và màu đã dịch look đều do
  Python tính; backend chỉ đọc, không tự nội suy hay tự đổi màu.

## Ports — không gọi thẳng dịch vụ ngoài

- Mọi lời gọi ra ngoài đi qua port của `engine-contracts` (`PortClient`). `shot_planner` nhờ Claude qua port `llm_provider`;
  thiếu adapter hoặc câu trả lời sai schema thì dùng bản nháp tất định và ghi log.
- Adapter chọn trong `providers.yaml` theo từng máy (mẫu: `providers.example.yaml`); khoá API trong `.env`. Cả hai không lên Git.
- **Test không gọi dịch vụ thật**: luôn cắm `adapters_mock`.

## Look system

- `core/look_adapter` chỉ dịch: nền ← `palette.bg`, xoay sắc độ vật liệu ← `emotion_map.<emotion>.hue_shift`, nét viền ←
  `palette.shadow` và `stroke.width_scale` (tuỳ chọn), nội suy mặc định ← `motion.default_interp`.
- LUT, hạt, vignette, chuyển cảnh và phụ đề là việc của `look_pass` ở khâu ghép; engine không áp lại.

## Tài sản và giấy phép

- Mọi tài sản phải có dòng trong `assets/registry.json` (đúng `specs/asset.schema.json`); `commercial_ok = false` bị G2/C-license chặn.
- `asset_id` giữ cố định qua mọi tập; đổi ngoại hình thì tăng `version`.
- Ưu tiên tài sản tự dựng bằng script, rồi CC0. Mô hình 3D sinh bằng AI chỉ lấy qua port `model3d_provider`.
- File nặng (`.glb`, `.blend`, `.vox`) chỉ nằm trong `assets/external/`, đi qua Git LFS hoặc NAS.

## Cổng kiểm — không giao video lỗi

- Thứ tự: 6 cổng chung (C-schema, C-duration, C-format, C-visual, C-no-captions, C-license) rồi 8 cổng riêng (G1–G8).
- `render_output.status`: `done` chỉ khi qua cả 14 cổng; `rejected` khi chunk ngoài thẻ năng lực (không render); `failed` khi
  trượt cổng (`video_path = null`). Không giao `done` với `qa_report.passed = false` (schema chặn).
- Cổng trượt → tự sửa (shot, preset máy quay của set, tài sản) rồi chạy lại; không hạ ngưỡng, không bỏ cổng.
- Sau mỗi lần render, **mở `out/<chunk_id>/contact_sheet.png` và tự xem**: cổng chỉ bắt lỗi đo được, không thay được mắt.

## Cách làm việc trong repo

- **Test trước:** viết test, chạy thấy đỏ, rồi mới viết code cho đến khi `pytest -q` xanh.
- Xem nhanh: `python -m core.pipeline run --chunk <file> --preview` (1/3 độ phân giải, ~10 s, không ghi `render_output.json`).
- Trước khi commit: `pytest -q` (gồm 2 lần render 1080p, ~2 phút trên CPU).
- Commit message: `feat: …`, `fix: …`, `docs: …` + nội dung tiếng Việt (luật chung mục 2.3).
- Thêm module mới thì thêm dòng vào bảng module trong README.
- Backend Blender là giai đoạn P2: giữ cùng hợp đồng bundle, không để backend Three.js phụ thuộc vào nó.
