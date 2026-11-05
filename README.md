# cartoon3d-engine

Engine sinh video hoạt hình 3D **dựng bằng code** cho video engine. Nhận một chunk đã có timeline SRT từ nhạc trưởng, trả về video đúng thời lượng chunk, đã qua 8 cổng kiểm. Bản gốc của mọi thứ là file chữ (JSON + script); video chỉ là sản phẩm sinh ra, không đưa lên Git.

Spec gốc: *Spec cartoon3d — module hoạt hình 3D trong video engine* (Claude Docs). Luật riêng của repo: [AGENTS.md](AGENTS.md).

## Chạy thử

Cần Python ≥ 3.11, Node ≥ 18 có `playwright` (Chromium), `ffmpeg`/`ffprobe`.

```bash
pip install -e ".[dev]"
(cd backends/threejs && npm ci)

# trọn luồng trên cảnh mẫu, độ phân giải nhỏ cho nhanh (~10 s)
python -m core.pipeline run --chunk tests/fixtures/cheese_bank/chunk_input.json --width 640 --height 360

# kết quả
out/000004200_002/000004200_002.mp4      # video
out/000004200_002/render_output.json     # hợp đồng trả nhạc trưởng (kèm qa_report)
out/000004200_002/contact_sheet.png      # lưới khung để tự xem
out/000004200_002/shots/*.json           # shot đã lập — sửa tay rồi chạy lại với --shots
```

Lệnh khác:

```bash
python -m core.pipeline plan --chunk <chunk_input.json>                # chỉ lập shot
python -m core.pipeline run  --chunk ... --skip-render                 # lập shot + bundle + 5 cổng trước render
python -m core.pipeline run  --chunk ... --shots out/<chunk_id>/shots  # render từ shot đã sửa tay
python -m core.pipeline run  --chunk ... --backend blender             # cần Blender ≥ 4.0 (giai đoạn P3)
python -m core.pipeline qa   --chunk ... --shots ... --frames ... --video ... --captions-plan ...
python -m pytest                                                       # test; e2e tự bỏ qua khi thiếu Chromium/ffmpeg
```

Mã thoát `2` = có cổng trượt; chi tiết trong `out/<chunk_id>/qa_report.json`.

## Vị trí trong video engine

```
SRT tập ──► srt-chunker ──► nhạc trưởng ──► [engine 1..4] + cartoon3d-engine ──► khâu ghép (lồng tiếng, nhạc, co giãn)
                                              chunk_input.json ──► render_output.json + .mp4
```

Repo này chỉ thay một ô trong roster: cùng hợp đồng chunk vào và video ra như các engine còn lại, nên nhạc trưởng và khâu ghép không phải sửa.

## Luồng pipeline

```
chunk_input.json
   │ shot_planner (luật tất định; Claude sửa tay được)        ┐
   ▼                                                           │ camera_library · sensitivity
shots/*.json                                                   ┘
   │ scene_bundle: tài sản + phong cách + track máy quay/nhân vật từng khung
   ▼
scene_bundle.json ──► cổng trước render G1 G2 G4 G5 G7 ──trượt──► sửa shot/preset, chạy lại
   │ backend threejs (Chromium headless) | blender (bpy)
   ▼
frames/*.png ──► captions (Pillow, từng chữ) ──► ffmpeg .mp4 ──► cổng sau render G3 G6 G8
   ▼
render_output.json + qa_report.json + contact_sheet.png
```

| Module | Input | Output | Công cụ |
| --- | --- | --- | --- |
| `core/shot_planner` | `chunk_input.json` | danh sách `shot.json` | luật tất định + `camera_library` (Claude sửa tay) |
| `core/scene_bundle.py` | `shot.json`, `assets/`, `styles/` | `scene_bundle.json` (kèm track từng khung) | Python |
| `backends/threejs` | `scene_bundle.json` | khung `.png` | Three.js 0.170 trong Chromium headless (Playwright) |
| `backends/blender` | `scene_bundle.json` | khung `.png` | Blender `--background` (`bpy`), giai đoạn P3 |
| `core/captions` | word-level SRT trong chunk | lớp phụ đề vẽ vào khung + `captions_plan.json` | Pillow |
| `core/qa_gates` | khung + shot + bundle | `qa_report.json`, `contact_sheet.png` | jsonschema, ffprobe, Pillow |
| đóng gói (`core/pipeline.py`) | khung đã qua cổng | `.mp4` + `render_output.json` | ffmpeg |

## Cấu trúc thư mục

```
cartoon3d-engine/
├── AGENTS.md              # luật riêng của repo
├── specs/                 # hợp đồng dữ liệu: chunk_input, shot, render_output, asset
├── core/
│   ├── shot_planner/      # chunk → danh sách shot
│   ├── camera_library/    # dolly, orbit, track_to, cut + nội suy tên Blender
│   ├── sensitivity/       # mức nhạy cảm → thủ pháp hình ảnh (table.json)
│   ├── captions/          # phụ đề từng chữ
│   ├── qa_gates/          # 8 cổng kiểm + contact sheet
│   ├── motion.py          # vị trí nhân vật theo đường đi, từng khung
│   ├── scene_bundle.py    # gom shot + tài sản + track thành một file cho backend
│   ├── timing.py          # ms ↔ khung, chia khung cho shot
│   └── pipeline.py        # CLI: plan · run · qa
├── backends/
│   ├── threejs/           # index.html, scene_builder.js, capture.cjs, capture.py
│   └── blender/           # build_scene.py, render.py
├── styles/                # toon.json, voxel.json, pixel3d.json
├── assets/
│   ├── registry.json      # sổ tài sản + giấy phép (G2)
│   ├── characters/        # toon = bộ tham số khối; voxel = lưới (x, y, z, màu)
│   ├── sets/              # cheese_vault, bank_hall, police_station: khối + điểm + đường đi + preset máy quay
│   ├── props/
│   └── external/          # file nặng — Git LFS hoặc NAS
├── tests/                 # pytest; fixtures/cheese_bank là cảnh mẫu
└── out/                   # render — trong .gitignore
```

`episodes/` không nằm trong repo: input của từng tập do video engine giữ, repo chỉ nhận chunk.

## Schema dữ liệu

| Hợp đồng | Trường chính | Ai viết |
| --- | --- | --- |
| `chunk_input` | `chunk_id`, `start_ms`, `end_ms`, `text`, `words[]`, `emotion`, `sensitivity` (0–3), `style`, `cast_refs`, `set_hint` | Nhạc trưởng |
| `shot` | `shot_id`, `duration_ms`, `style`, `set`, `cast[]`, `camera`, `captions`, `sensitivity_device` | `shot_planner` |
| `render_output` | `chunk_id`, `video_path`, `frames`, `duration_ms`, `fps`, `backend`, `qa_report` | Backend + `qa_gates` |
| `asset` | `asset_id`, `kind`, `source`, `license`, `commercial_ok`, `redistribute_ok`, `path`, `version` | Người dựng tài sản |

Ví dụ shot (cảnh phô mai): [tests/fixtures/cheese_bank/shot_example.json](tests/fixtures/cheese_bank/shot_example.json). `interp` dùng tên của Blender; `sensitivity_device` một trong `none`, `cut_away`, `silhouette`, `symbol_object`, `top_down_diagram`, `offscreen_sound`.

## Thư viện máy quay và thủ pháp nhạy cảm

- Bốn chuyển động có tên: `dolly` (từ → đến), `orbit` (quay quanh tâm), `track_to` (bám nhân vật với offset), `cut` (cắt giữa nhiều góc). Mỗi set khai `camera_presets` nên shot chỉ cần ghi `move`; planner điền phần còn lại để `shot.json` tự đứng được.
- Cảm xúc → chuyển động mặc định: `neutral`/`calm` → dolly, `tense`/`sad` → orbit, `reveal`/`funny` → track_to, `chaos` → cut (`core/camera_library/moves.json`).
- Mức nhạy cảm 0–3 → thủ pháp được phép và mặc định (`core/sensitivity/table.json`): 0 `none` · 1 `cut_away` · 2 `silhouette` · 3 `offscreen_sound`. Thủ pháp sai mức bị cổng G7 chặn.

## Cổng kiểm chất lượng

| Cổng | Kiểm gì | Cách kiểm |
| --- | --- | --- |
| G1 Schema | chunk, shot, render_output đúng schema; tổng `duration_ms` shot = chunk | jsonschema |
| G2 Giấy phép | mọi tài sản có trong registry, `commercial_ok = true`, file tồn tại | đối chiếu registry |
| G3 Thời lượng | số khung = làm tròn(`duration_ms` × fps / 1000), trên đĩa và trong `.mp4` | ffprobe `-count_frames` |
| G4 Hình khối | vật tròn ≥ 32 mặt; crease 140° | đọc bundle trước render |
| G5 Máy quay | máy cách tâm nhân vật ≥ 0,5 m; chủ thể trong khung (trừ cut_away/offscreen/symbol) | đo track từng khung |
| G6 Hình ảnh | không khung đen/trắng; chữ không bị cắt | thống kê khung mẫu + contact sheet để agent tự xem |
| G7 Nhạy cảm | `sensitivity_device` khớp mức của chunk | bảng quy đổi |
| G8 Phụ đề | chữ trong vùng an toàn 5 %; từng từ bắt đầu đúng khung của SRT | so `captions_plan.json` với `words[]` |

Cổng trước render (G1 G2 G4 G5 G7) chạy trên bundle, trượt thì dừng ngay không tốn render. Cổng sau render (G3 G6 G8) chạy trên khung và video. Trượt cổng nào thì sửa (shot, preset máy quay của set, tài sản) rồi chạy lại; không giao video lỗi.

## Lộ trình

| Giai đoạn | Nội dung | Trạng thái |
| --- | --- | --- |
| P0 | Hợp đồng dữ liệu, cảnh mẫu `cheese_bank`, backend Three.js, 8 cổng, phụ đề từng chữ | **xong** (repo này) |
| P1 | Một tập 3 phút đi trọn luồng qua nhạc trưởng; thêm nhân vật/bối cảnh cho dòng vụ án | tiếp theo |
| P2 | Chất lượng hình: rig tay chân khớp hành động, nhiều `camera_presets`, ≥ 75 % chunk qua cổng ngay lần đầu (mốc đề xuất) | |
| P3 | Backend Blender thay Three.js cho bản phát hành | `backends/blender` giữ cùng hợp đồng, chưa chạy CI |

## Câu hỏi mở (theo spec)

- [ ] cartoon3d là engine thứ 5 hay thứ 6 trong roster?
- [ ] Tên repo chốt `cartoon3d-engine` hay theo quy ước đặt tên engine?
- [ ] File nặng để Git LFS hay ổ NAS chung? (`.gitattributes` đang khai LFS cho `assets/external/`)
- [ ] Phụ đề từng chữ do engine này vẽ (hiện tại) hay khâu ghép vẽ chung cho mọi engine? (`captions.mode = none` tắt được)
- [ ] Dòng vụ án dùng `toon` hay `voxel` làm mặc định?
