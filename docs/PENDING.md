# Pending Items — QC-Agent

Việc còn nợ, tạm dừng ngày 2026-10-01 để xử lý task khác. Đánh dấu `[x]` khi xong.

## 1. Review spec Giai đoạn 1 (owner: Connor)

- [ ] Đọc và duyệt `docs/superpowers/specs/2026-10-01-qc-agent-phase1-ingestion-design.md` (nhánh `docs/phase1-ingestion-spec`).
- [ ] Kiểm tra 4 điểm được thêm khi viết spec, chưa trao đổi trong chat:
  - [ ] Stub chỉ tạo cho loại tài liệu bắt buộc (cờ `required` trong taxonomy, mục 5.2).
  - [ ] Thêm bảng `auth_sessions` để thu hồi phiên đăng nhập.
  - [ ] File `unclassified` phải được chọn thư mục và loại trước khi Apply.
  - [ ] Ghi nhận xác nhận của khách hàng trước lần nạp dữ liệu thật đầu tiên.

## 2. Quyết định cần xác nhận (owner: Connor / IT)

- [ ] Nền tảng CI: GitHub Actions, GitLab CI, Azure DevOps hay khác.
- [ ] Câu chữ xin khách hàng xác nhận việc gửi nội dung tài liệu lên Claude API.
- [ ] Cấu hình server nội bộ và nơi lưu backup.

## 3. Chuẩn bị môi trường (owner: Connor / IT)

- [ ] Cài Docker Desktop hoặc OrbStack trên máy dev.
- [ ] API key Anthropic riêng cho hệ thống, có hạn mức chi tiêu.
- [ ] VM Linux nội bộ, tên miền nội bộ, chứng chỉ TLS.
- [ ] Python 3.12 qua uv (máy hiện có Python 3.9 hệ thống).

## 4. Bước tiếp theo sau khi spec được duyệt (owner: Claude)

- [ ] Lập kế hoạch triển khai bằng skill writing-plans.
- [ ] Spike Agent SDK: chạy song song, `setting_sources=[]`, `CLAUDE_CONFIG_DIR`, chi phí trên 10 tài liệu mẫu.
