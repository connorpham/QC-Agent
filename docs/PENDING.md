# Pending Items — QC-Agent

Việc còn nợ, tạm dừng ngày 2026-10-01 để xử lý task khác. Đánh dấu `[x]` khi xong.

## 1. Review spec Giai đoạn 1 (owner: Connor)

- [x] Đọc và duyệt `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` (nhánh `docs/phase1-ingestion-spec`).
- [ ] Spec đã lên v2 (người dùng chọn loại khi upload, SharePoint + Google Drive, khách hàng dùng web app, MFA). Kiểm tra các điểm tôi tự quyết khi viết v2:
  - [ ] Stub chỉ tạo cho loại tài liệu bắt buộc (mục 5.5).
  - [ ] Loại `api-spec`, `repo-structure`, `test-cases` không chuẩn hóa template (cờ `normalize: false`, mục 5.2).
  - [ ] Bản mới chỉ thay bản chuẩn hóa cũ sau khi bản nháp mới được duyệt (mục 5.4).
  - [ ] Kiểm tra loại bị lỗi thì vẫn công bố theo loại người dùng chọn (mục 7.6).
  - [ ] Khách hàng được xem lịch sử phiên bản của tài liệu chia sẻ (giả định, mục 18.3).
  - [ ] Lưu trữ của dự án không đổi được sau khi tạo (mục 8.5).

## 2. Quyết định cần xác nhận (owner: Connor / IT)

- [ ] Nền tảng CI: GitHub Actions, GitLab CI, Azure DevOps hay khác.
- [ ] Câu chữ xin khách hàng xác nhận việc gửi nội dung tài liệu lên Claude API.
- [ ] Nhà cung cấp cloud, cấu hình VM và nơi lưu backup.

## 3. Chuẩn bị môi trường (owner: Connor / IT)

- [ ] Cài Docker Desktop hoặc OrbStack trên máy dev.
- [ ] API key Anthropic riêng cho hệ thống, có hạn mức chi tiêu.
- [ ] VM cloud có tên miền công khai (thay cho VM nội bộ).
- [ ] IT đăng ký app Entra ID với quyền `Sites.Selected` và cấp quyền cho từng site SharePoint.
- [ ] IT tạo service account Google Cloud, bật Drive API, thêm vào các Shared Drive.
- [ ] Site SharePoint và Shared Drive dùng để test.
- [ ] Python 3.12 qua uv (máy hiện có Python 3.9 hệ thống).

## 4. Triển khai (owner: Claude)

- [x] Spec v2 được duyệt (2026-10-01).
- [x] Lập kế hoạch triển khai: `docs/superpowers/plans/2026-10-01-phase1-roadmap.md`.
- [ ] Review Plan 0 và Plan 1, chọn cách thực thi (owner: Connor).
- [x] Thực thi Plan 1 (backend foundation). Cần Docker trước.
- [ ] Thực thi Plan 0, spike Agent SDK (cần API key): chạy song song, `setting_sources=[]`, `CLAUDE_CONFIG_DIR`, chi phí trên 10 tài liệu mẫu.
- [ ] Thực thi Plan 0, spike lưu trữ (cần IT chuẩn bị site SharePoint và Shared Drive test): upload và phiên bản trên SharePoint (Graph) và Google Drive.

## 5. Việc mang sang từ review Plan 1 (owner: Claude)

- [ ] Plan 2, việc đầu tiên: đặt `EXPOSE_DOCS=false` trong `backend/tests/conftest.py`. Hiện test ẩn API docs sẽ fail nếu `.env` bật `EXPOSE_DOCS=true` như `.env.example`.
- [ ] Plan 2, việc đầu tiên: tăng `failed_logins` bằng câu `UPDATE ... SET failed_logins = failed_logins + 1 RETURNING` để không mất lượt đếm khi có nhiều lần sai cùng lúc.
- [ ] Plan 2: một thay đổi schema `ProjectSettings` phải kèm migration dữ liệu cho `projects.settings`.
- [ ] Plan 6: uvicorn chạy với `--proxy-headers` và `FORWARDED_ALLOW_IPS` trỏ tới Caddy.
- [ ] Plan 6: rate limiter quét toàn bộ key mỗi request khi có trên 100k IP còn hoạt động; giới hạn tần suất quét hoặc loại key cũ nhất.
- [ ] Plan 6: job dọn `auth_sessions` đã hết hạn hoặc bị thu hồi.
- [ ] Plan 6: runbook ghi rõ xoay `SESSION_SECRET` sẽ làm mất hiệu lực mọi phiên và mã khôi phục MFA.
- [x] Cập nhật Global Constraints của Plan 1: giới hạn auth mặc định 100 request mỗi 5 phút, khóa chỉ reset sau MFA thành công.
