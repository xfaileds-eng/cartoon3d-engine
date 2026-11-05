# AGENTS.md — luật riêng của `cartoon3d-engine`

Kế thừa `agent-rules` chung của video engine; file này chỉ ghi phần riêng của repo. Spec gốc: *Spec cartoon3d — module hoạt hình 3D trong video engine*.

## Vai trò của repo

- Là **một engine trong roster** của video engine: nhận một chunk đã có timeline SRT từ nhạc trưởng, trả về video 3D dựng bằng code, **đúng thời lượng chunk**. Không chia SRT, không lồng tiếng, không ghép chunk, không quét lời thoại nhạy cảm — những việc đó ở thượng nguồn/hạ nguồn.
- **Bản gốc của mọi thứ là file chữ** (JSON + script). Video, khung hình, contact sheet là sản phẩm sinh ra, nằm trong `out/` và không bao giờ đưa lên Git.

## Hợp đồng dữ liệu (không tự ý đổi)

- Ba hợp đồng với bên ngoài nằm trong `specs/`: `chunk_input` (nhạc trưởng viết), `shot` (engine tự lập), `render_output` (engine trả). Đổi trường = đổi schema + fixture + test cùng một commit, và báo nhạc trưởng.
- `chunk_id` = mốc mili-giây 9 chữ số + `_` + số thứ tự 3 chữ số (`000004200_002`); `shot_id` = `chunk_id` + `_s<n>`.
- `interp` dùng **tên của Blender** (`linear`, `ease_in`, `ease_out`, `ease_in_out`, `constant`, `bounce`), không dùng tên của After Effects.
- `sensitivity_device` chỉ nhận: `none`, `cut_away`, `silhouette`, `symbol_object`, `top_down_diagram`, `offscreen_sound`; mức nào được dùng thủ pháp nào nằm ở `core/sensitivity/table.json`.
- Hai backend (`threejs`, `blender`) **cùng ăn một `scene_bundle.json`**. Track máy quay và vị trí nhân vật từng khung do Python tính (`core/camera_library`, `core/motion.py`); backend chỉ đọc, không tự nội suy lại.

## Tài sản và giấy phép

- Mọi tài sản phải có dòng trong `assets/registry.json` (đúng `specs/asset.schema.json`) thì mới được render; `commercial_ok = false` bị cổng G2 chặn.
- `asset_id` giữ cố định qua mọi tập; đổi ngoại hình thì tăng `version`, không tạo id mới.
- Ưu tiên tài sản tự dựng bằng script (nhân vật `toon` = bộ tham số khối, `voxel` = lưới `(x, y, z, màu)`), rồi CC0. Meshy/Tripo chỉ gói trả phí; Mixamo không đóng gói file gốc; BlenderKit ghi giấy phép từng tài sản.
- File nặng (`.glb`, `.blend`, `.vox`) chỉ nằm trong `assets/external/` và đi qua Git LFS hoặc NAS (xem `.gitattributes`).

## Cổng kiểm — không giao video lỗi

- Một chunk chỉ được trả về khi qua đủ **8 cổng** (`core/qa_gates`): G1 schema · G2 giấy phép · G3 thời lượng · G4 hình khối (vật tròn ≥ 32 mặt, crease 140°) · G5 máy quay · G6 hình ảnh · G7 nhạy cảm · G8 phụ đề.
- Cổng trượt → **tự sửa rồi chạy lại** (sửa shot.json, preset camera của set, tài sản…), không hạ ngưỡng cổng, không bỏ cổng, không giao `render_output.json` có `passed = false`.
- G3 là cổng chặn quan trọng nhất với khâu ghép: số khung = làm tròn(`duration_ms` × fps / 1000), đếm bằng ffprobe.
- Sau mỗi lần render, **mở `out/<chunk_id>/contact_sheet.png` và tự xem** trước khi kết luận; cổng G6 chỉ bắt khung đen/trắng, không thay được mắt.

## Cách làm việc trong repo

- Chạy nhanh: `python -m core.pipeline run --chunk tests/fixtures/cheese_bank/chunk_input.json --width 640 --height 360`. Độ phân giải thật (1920×1080) chỉ khi đã qua cổng ở độ phân giải nhỏ.
- Trước khi commit: `python -m pytest` (test e2e tự bỏ qua khi thiếu Chromium/ffmpeg) và `python -m core.pipeline run … --skip-render` trên cả hai fixture.
- Mỗi tầng một thư mục (`core/`, `backends/`, `styles/`, `assets/`); thêm module mới thì thêm dòng vào bảng module trong README.
- Không commit `out/`, `node_modules/`, file render. Không ghi đường dẫn tuyệt đối của máy vào JSON.
- Backend Blender là giai đoạn P3: giữ cùng hợp đồng bundle, không được làm backend Three.js phụ thuộc vào nó.
