# cartoon3d-engine

Engine sinh video hoạt hình 3D **dựng bằng code** trong roster của video engine. Nhận `chunk_input` từ nhạc trưởng, trả
`render_output` + video đúng thời lượng chunk, đã qua 6 cổng chung và 8 cổng riêng. **Không in phụ đề**: phụ đề in một lần ở
khâu ghép.

- Spec: [docs/spec.md](docs/spec.md) · hợp đồng chung: `engine-contracts/docs/spec.md` · luật repo: [AGENTS.md](AGENTS.md)
- Thẻ năng lực cho nhạc trưởng: [capability_card.json](capability_card.json)
- Giai đoạn hiện tại: **P1 Lõi engine** (P0 thử nghiệm đã xong).

## Chạy

Cần Python ≥ 3.11, Node ≥ 18 có `playwright` (Chromium), `ffmpeg`/`ffprobe`, `tesseract-ocr` (+ `tesseract-ocr-vie`) cho
cổng không-phụ-đề.

```bash
pip install -e ".[dev]"
(cd backends/threejs && npm ci)
cp providers.example.yaml providers.yaml      # chọn adapter cho port llm_provider (tuỳ máy)

pytest -q                                                        # 62 test, gồm 2 lần render 1080p (~2 phút trên CPU)
python -m core.pipeline run --chunk tests/fixtures/cheese_bank/chunk_input.json            # 1920x1080, ~45 s
python -m core.pipeline run --chunk tests/fixtures/cheese_bank/chunk_input.json --preview  # 1/3 độ phân giải, ~10 s
python -m core.pipeline run --chunk ... --shots out/<chunk_id>/shots                       # render từ shot đã sửa tay
python -m core.pipeline plan --chunk ...                                                   # chỉ lập shot
```

Kết quả trong `out/<chunk_id>/`: `<chunk_id>.mp4`, `render_output.json`, `contact_sheet.png`, `shots/*.json`.
Mã thoát: `0` done · `2` failed (trượt cổng) · `3` rejected · `4` preview.

## Hợp đồng chung (engine-contracts)

`chunk_input`, `render_output`, `capability_card`, `format.json`, `looks/` và `ports/` thuộc repo `engine-contracts`. Repo đó
chưa có, nên tạm dùng bản chép từ brief trong `vendor/engine-contracts/` (đọc [README](vendor/engine-contracts/README.md) của
nó). `core/contracts.py` tìm theo thứ tự `ENGINE_CONTRACTS_DIR` → `../engine-contracts` → `vendor/engine-contracts`.

| Hợp đồng | Trường chính | Ai viết |
| --- | --- | --- |
| `chunk_input` | `chunk_id`, `start_ms`, `end_ms`, `text`, `words[]`, `emotion`, `speech_rate`, `sensitivity`, `aspect`, `look_id`, `cast_refs`, `data_refs` | Nhạc trưởng |
| `render_output` | `chunk_id`, `engine_id`, `status`, `video_path`, `frames`, `fps`, `duration_ms`, `qa_report`, `cost` | Engine |
| `shot` (riêng, `specs/`) | `shot_id`, `duration_ms`, `style`, `set`, `cast[]`, `camera`, `look_id`, `sensitivity_device` | `shot_planner` |
| `asset` (riêng, `specs/`) | `asset_id`, `kind`, `source`, `license`, `commercial_ok`, `redistribute_ok`, `path`, `version` | Người dựng tài sản |

`format.json` tạm: 30 fps, 1920×1080 cho 16:9, 1080×1920 cho 9:16, h264/yuv420p.

## Luồng và module

```
chunk_input ─► thẻ năng lực ─(ngoài phạm vi)─► render_output status=rejected
     │
     ▼ shot_planner: bản nháp tất định ─► port llm_provider (Claude; mock trong test) ─► shots/*.json
     ▼ scene_bundle: tài sản + phong cách + look_adapter + track máy quay/nhân vật từng khung
     ▼ cổng trước render: C-license G1 G2 G4 G5 G7 ──trượt──► failed, không render
     ▼ backend threejs (Chromium headless) | blender (bpy) ─► khung .png
     ▼ ffmpeg .mp4 theo format.json (không phụ đề)
     ▼ cổng sau render: C-duration C-format C-visual C-no-captions G3 G6 G8, rồi C-schema trên render_output
     ▼ render_output status=done | failed
```

| Module | Input | Output | Công cụ |
| --- | --- | --- | --- |
| `core/shot_planner` | `chunk_input.json` | danh sách `shot.json` | luật tất định + Claude qua port `llm_provider` + `camera_library` |
| `core/look_adapter` | `looks/<look_id>.json`, `emotion` | màu vật liệu, nền, nét viền, nội suy mặc định | Python |
| `core/scene_bundle.py` | `shot.json`, `assets/`, `styles/`, look | `scene_bundle.json` (kèm track từng khung) | Python |
| `backends/threejs` | `scene_bundle.json` | khung `.png` | Three.js 0.170 trong Chromium headless (Playwright) |
| `backends/blender` | `scene_bundle.json` | khung `.png` | Blender `--background` (`bpy`) — giai đoạn P2, chưa chạy CI |
| `core/qa_gates` | khung + shot + video | `qa_report` trong `render_output.json`, `contact_sheet.png` | jsonschema, ffprobe, Pillow, tesseract |
| `core/pipeline.py` | khung đã qua cổng | `.mp4` + `render_output.json` | ffmpeg |
| `core/providers.py` | `providers.yaml` | `PortClient` cho từng port | ports của engine-contracts |

## Cổng kiểm

| Cổng | Kiểm gì | Cách kiểm |
| --- | --- | --- |
| C-schema | `chunk_input` và `render_output` đúng schema chung | jsonschema |
| C-duration | Số khung = làm tròn(`duration_ms` × fps / 1000), lệch 0 khung | ffprobe `-count_frames` |
| C-format | fps, độ phân giải theo `aspect`, codec, pix_fmt khớp `format.json` | ffprobe |
| C-visual | Không khung đen/trắng | thống kê khung mẫu + contact sheet |
| C-no-captions | OCR khung giữa không ra chữ nào của `text` | tesseract `eng+vie` |
| C-license | Mọi tài sản dùng thương mại được | registry |
| G1 Schema | Shot đúng `shot.schema.json`, mang `chunk_id` và `look_id` của chunk, tổng thời lượng khớp | jsonschema |
| G2 Giấy phép | Mọi dòng registry đúng schema; tài sản dùng có `commercial_ok = true` | đối chiếu registry |
| G3 Thời lượng | Khung từng shot, khung trên đĩa và trong video đều đúng số | ffprobe |
| G4 Hình khối | Vật tròn ≥ 32 mặt; crease cố định 140° | đọc bundle trước render |
| G5 Máy quay | Máy cách tâm nhân vật ≥ 0,5 m; chủ thể trong khung | đo track từng khung |
| G6 Hình ảnh | Soát mọi khung không đen/trắng | thống kê khung + agent tự xem contact sheet |
| G7 Nhạy cảm | `sensitivity_device` khớp mức `sensitivity` của chunk | `core/sensitivity/table.json` |
| G8 Không phụ đề | OCR 5 khung mẫu không ra chữ của lời thoại | tesseract |

## Thư viện máy quay, nhạy cảm, phong cách

- Bốn chuyển động: `dolly`, `orbit`, `track_to`, `cut`. Mỗi set khai `camera_presets` nên shot chỉ cần ghi `move`.
- Cảm xúc → chuyển động mặc định trong `core/camera_library/moves.json` (cảm xúc lạ → `dolly`).
- `sensitivity` của chunk → thủ pháp: `none` → `none` · `low` → `cut_away` · `medium` → `silhouette` · `high` → `offscreen_sound`.
- Ba phong cách cắm rời trong `styles/`: `voxel` (mặc định cho dòng vụ án, chốt 05/11/2026), `toon`, `pixel3d`. Đổi theo máy bằng biến `CARTOON3D_STYLE`.
- Giới hạn hiện tại của `voxel`: mới đổi cách đổ bóng (tô phẳng, không viền) và nhân vật lưới voxel như `rat_voxel`. Bối cảnh, đồ vật và nhân vật khối vẫn giữ hình tròn trơn; khối hoá toàn cảnh (`voxelize_sets` trong `styles/voxel.json`) chưa làm, thuộc P3.
- Bối cảnh: `default_set` của nhân vật đầu tiên; chunk không có nhân vật thì khớp `keywords` của set với lời thoại.

## Cấu trúc thư mục

```
cartoon3d-engine/
├── AGENTS.md · README.md · capability_card.json · providers.example.yaml
├── docs/spec.md
├── specs/                 # shot.schema.json, asset.schema.json
├── core/
│   ├── shot_planner/      # chunk → shot (qua port llm_provider)
│   ├── camera_library/    # dolly, orbit, track_to, cut + nội suy tên Blender
│   ├── sensitivity/       # mức nhạy cảm → thủ pháp hình ảnh
│   ├── look_adapter/      # dịch look token sang vật liệu, nét viền
│   ├── qa_gates/          # 6 cổng chung + 8 cổng riêng + contact sheet
│   ├── contracts.py       # tìm và đọc engine-contracts
│   ├── providers.py       # providers.yaml → PortClient
│   ├── capability.py      # thẻ năng lực, trả rejected sớm
│   ├── motion.py · scene_bundle.py · timing.py · registry.py
│   └── pipeline.py        # CLI: run · plan
├── backends/
│   ├── threejs/           # index.html, scene_builder.js, capture.cjs, capture.py
│   └── blender/           # build_scene.py, render.py
├── styles/                # toon.json, voxel.json, pixel3d.json
├── assets/                # registry.json, characters/ (4), sets/ (3), props/ (3), external/
├── vendor/engine-contracts/  # bản chép tạm — xoá khi repo engine-contracts có thật
├── tests/                 # pytest; fixtures/cheese_bank
└── out/                   # render — trong .gitignore
```

## Lộ trình

| Giai đoạn | Nội dung | Cổng sang giai đoạn sau | Trạng thái |
| --- | --- | --- | --- |
| P0 Thử nghiệm | Three.js, 3 shot cảnh ngân hàng phô mai | Giống bản tham chiếu ≥ 50% (đạt ~55%) | xong |
| P1 Lõi engine | schema, planner, camera_library, qa_gates, 3 bối cảnh, 4 nhân vật | 1 tập 3 phút qua đủ 8 cổng | **đang làm**: lõi + test xanh, chưa chạy tập 3 phút |
| P2 Blender | backend thứ hai: Line Art, DOF, rig Mixamo, cùng spec shot | Giống bản tham chiếu ≥ 75% (mốc đề xuất) | có khung `backends/blender`, chưa chạy |
| P3 Mở rộng | voxel, pixel3d, bối cảnh vụ án, thêm nhân vật | Kênh có view và dòng tiền | voxel là mặc định nhưng chưa khối hoá toàn cảnh; pixel3d bản đầu |

## Câu hỏi mở

- [ ] File nặng để Git LFS hay ổ NAS chung? (`.gitattributes` đang khai LFS cho `assets/external/`)
- [x] Dòng vụ án dùng `voxel` làm mặc định (anh chốt 05/11/2026).
- [ ] Giá trị `sensitivity`, `speech_rate` của `chunk_input` (brief chỉ có `none`, `normal`; đang tạm `none/low/medium/high`, `slow/normal/fast`).
- [ ] Look chưa có token độ dày nét viền; đang đọc `stroke.width_scale` tuỳ chọn.
- [ ] `capture.py` dùng chung với chart-engine đặt ở đâu (engine-contracts hay package riêng)? Trang hiện đã dùng API trung tính `window.capture`.
