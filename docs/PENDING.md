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
  - [x] Lưu trữ của dự án không đổi được sau khi tạo (mục 8.5) — spec v2.1: đổi được qua migration (Plan 3c).

## 2. Quyết định cần xác nhận (owner: Connor / IT)

- [x] Nền tảng CI: GitHub Actions (`.github/workflows/ci.yml`), chốt 2026-10-01.
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
- [x] Lập kế hoạch Plan 2 (local ingestion): `docs/superpowers/plans/2026-10-01-plan-2-local-ingestion.md`; roadmap đổi thứ tự (Plan 3 = cloud storage).
- [x] Thực thi Plan 2 (owner: Claude; review: Connor) — merged PR #3.
- [x] Lập kế hoạch Plan 3a (UI shell + storage settings): `docs/superpowers/plans/2026-10-01-plan-3a-ui-storage-settings.md`; Plan 3 tách thành 3a/3b/3c.
- [x] Thực thi Plan 3a (owner: Claude; review: Connor) — merged PR #4.
- [x] Lập kế hoạch Plan 5 (upload + document UI, chạy trước Plan 4 vì chưa có API key): `docs/superpowers/plans/2026-10-02-plan-5-upload-documents-ui.md`.
- [x] Thực thi Plan 5 (owner: Claude; review: Connor) — merged PR #6.
- [ ] Lập kế hoạch Plan 4 (agent): nhận thêm màn hình duyệt bản nháp chuẩn hóa và badge "normalised" từ Plan 5.
- [ ] Lập kế hoạch Plan 3b (SharePoint + Google Drive; cần site test của IT) và Plan 3c (đổi lưu trữ có migration).
- [ ] Thực thi Plan 0, spike Agent SDK (cần API key): chạy song song, `setting_sources=[]`, `CLAUDE_CONFIG_DIR`, chi phí trên 10 tài liệu mẫu.
- [ ] Thực thi Plan 0, spike lưu trữ (cần IT chuẩn bị site SharePoint và Shared Drive test): upload và phiên bản trên SharePoint (Graph) và Google Drive.

## 5. Việc mang sang từ review Plan 1 (owner: Claude)

- [x] Plan 2, việc đầu tiên: đặt `EXPOSE_DOCS=false` trong `backend/tests/conftest.py`. Hiện test ẩn API docs sẽ fail nếu `.env` bật `EXPOSE_DOCS=true` như `.env.example`.
- [x] Plan 2, việc đầu tiên: tăng `failed_logins` bằng câu `UPDATE ... SET failed_logins = failed_logins + 1 RETURNING` để không mất lượt đếm khi có nhiều lần sai cùng lúc.
- [ ] Plan 2: một thay đổi schema `ProjectSettings` phải kèm migration dữ liệu cho `projects.settings`.
- [ ] Plan 6: uvicorn chạy với `--proxy-headers` và `FORWARDED_ALLOW_IPS` trỏ tới Caddy.
- [ ] Plan 6: rate limiter quét toàn bộ key mỗi request khi có trên 100k IP còn hoạt động; giới hạn tần suất quét hoặc loại key cũ nhất.
- [ ] Plan 6: job dọn `auth_sessions` đã hết hạn hoặc bị thu hồi.
- [ ] Plan 6: runbook ghi rõ xoay `SESSION_SECRET` sẽ làm mất hiệu lực mọi phiên và mã khôi phục MFA.
- [x] Cập nhật Global Constraints của Plan 1: giới hạn auth mặc định 100 request mỗi 5 phút, khóa chỉ reset sau MFA thành công.
- [ ] Plan 3b: chính sách version cho gap report và `project.yaml` trên SharePoint/Drive (mỗi lần publish hiện tạo 3 version); bản gốc của file `.md` upload chỉ xem được qua lịch sử phiên bản.
- [ ] Plan 6: giới hạn request body ở Caddy (`request_body` `max_size`).
- [ ] Plan 6: requeue khi chạy nhiều worker (chỉ reset item quá thời gian chờ) hoặc giữ một worker.
- [ ] Plan 6: test lifespan wiring (requeue khi khởi động, hủy task nền khi tắt).
- [ ] Plan 6: xóa thư mục `mkdtemp` của test và ghi chú `QC_SKIP_DB`.
- [ ] Ghi nhận: lần đầu publish của dự án cũ (chưa provision) tạo rồi xóa stub cho chính loại đang publish (vô hại).
- [ ] Plan 6: khi commit lỗi mơ hồ (server đã commit nhưng client nhận lỗi), bước hoàn tác có thể xóa file của tài liệu đã publish; kiểm tra DocumentVersion trong session mới trước khi hoàn tác.
- [ ] Theo dõi giới hạn tỉ lệ nén 50× của file Office: file xlsx lớn, lặp nhiều có thể bị từ chối; điều chỉnh nếu người dùng gặp.
- [ ] Plan 5: 401 trong `useLoad` hiện Alert một nhịp trước khi chuyển về `/login`; bỏ qua set error khi status là 401.
- [x] Plan 5: tab trên trang dự án dùng `role="tablist"`/`role="tab"` nhưng thiếu tabpanel, `aria-controls` và điều hướng bằng phím mũi tên; hoàn thiện hoặc đổi sang button thường — Plan 5: component Tabs (tabpanel, aria-controls, phím mũi tên).
- [ ] Plan 3b: thêm index hàm trên `(storage->>'connection_id', lower(storage->>'root'))` khi số dự án tăng.
- [ ] Quy ước backend: một route commit một lần; các service gọi liên tiếp dùng chung transaction.
- [ ] Plan 5: `/auth/mfa/verify` trả 401 cho cả mã sai lẫn phiên hết hạn; đổi mã sai sang 400 để màn MFA phân biệt được mà không phải gọi thêm `/auth/me`.
- [ ] Plan 3b/3c: PATCH kết nối lưu trữ ghi audit cả khi không có gì đổi; và không thể vừa kích hoạt vừa đặt mặc định trong một lần gọi (set_default chạy trước).
- [ ] Plan 6: Caddy phải không buffer phản hồi `text/event-stream` (`flush_interval -1` cho `/api/v1/uploads/*/events`) và giữ kết nối lâu hơn 30 giây; backend gửi `: ping` mỗi 15 giây vì rewrite proxy của Next đóng phản hồi im lặng sau 30 giây (`experimental.proxyTimeout`).
- [ ] Theo dõi: id của bảng `events` là identity, hai giao dịch có thể commit ngược thứ tự id nên một client đang stream có thể bỏ lỡ một trạng thái trung gian; client làm mới toàn bộ upload khi nhận `upload.settled` nên trạng thái cuối luôn đúng. Nếu cần tuyệt đối, chuyển sang khóa advisory theo upload khi ghi event.
- [ ] Plan 4: tiêu đề loại tài liệu trên trang tài liệu (`DocumentPage.tsx`, `TYPE_TITLES`) lặp lại taxonomy để tránh thêm một request; khi taxonomy đổi phải cập nhật cả hai.
- [ ] Plan 5 (nếu người dùng cần): tìm kiếm trong dropdown loại tài liệu hiện dựa vào type-ahead của `<select>` gốc; cân nhắc combobox có tìm kiếm nếu phản hồi người dùng yêu cầu.

- [ ] **Giới hạn tài nguyên của SSE (chặn trước khi mở ra ngoài nội bộ).** Stream `/api/v1/uploads/{id}/events` không có thời gian sống tối đa và không giới hạn số listener trên mỗi người dùng. Mỗi listener chạy vòng lặp `POLL_INTERVAL = 0.5s`, mỗi vòng mở một session và chạy 2 query, tức 2N query và 2N lần mượn connection mỗi giây với N listener. Pool production là mặc định của SQLAlchemy (`backend/app/db/session.py` chỉ truyền `pool_pre_ping`), tức 5 + 10 = 15 connection. Ở mức vài trăm listener, request API thường bắt đầu xếp hàng sau các poll của stream và cuối cùng chạm `pool_timeout`. Một item kẹt ở `converting` vì task pipeline chết giữa chừng sẽ giữ stream của mọi người xem mở vô hạn, chỉ lành lại khi `requeue_stale_items` chạy lúc khởi động tiến trình. Cần: (a) thời gian sống tối đa cho stream, ví dụ 10 phút rồi kết thúc response để `EventSource` tự kết nối lại; (b) trần số listener đồng thời trên mỗi người dùng; (c) đặt `pool_size`/`max_overflow` tường minh theo số listener dự kiến. Đánh giá: rủi ro từ chối dịch vụ có thật nhưng vừa phải, cần kẻ tấn công có chủ đích hoặc một pipeline kẹt chứ không phải lưu lượng thường; chấp nhận được cho Phase 1 nội bộ.
- [ ] Phân quyền của stream SSE chỉ kiểm tra một lần lúc kết nối. Cùng với việc không có thời gian sống tối đa, người dùng bị thu hồi quyền thành viên dự án vẫn nhận frame `item.status` cho upload đó tới khi stream kết thúc. Các frame chỉ mang id, trạng thái và giải thích kiểm tra của chính upload họ tải lên nên mức lộ nhỏ, nhưng đây là thêm một lý do để chặn thời gian sống của stream.

## 6. Ràng buộc xác thực cho Plan 4 (tra cứu 2026-10-01)

- [ ] Xin API key Anthropic riêng cho QC-Agent, kèm trần chi tiêu hàng tháng trên Console (owner: Connor / IT).
- Không được dùng subscription Claude (Pro/Max) cho server: tài liệu Agent SDK nêu rõ Anthropic không cho phép bên thứ ba dùng đăng nhập hoặc hạn mức claude.ai cho sản phẩm của họ, kể cả agent xây trên Claude Agent SDK, trừ khi được duyệt trước. Nguồn: https://code.claude.com/docs/en/agent-sdk/overview.md
- Lý do kỹ thuật kèm theo: token OAuth của subscription hết hạn khoảng một ngày và cần đăng nhập lại bằng trình duyệt, server headless không làm được; hạn mức subscription tính theo tuần và dùng chung với Claude Code của chính người dùng.
- Dev local: lập trình viên có thể dùng `claude setup-token` rồi đặt `CLAUDE_CODE_OAUTH_TOKEN` cho máy mình, nhưng không đưa lên server.
- Plan 4 không bị chặn hoàn toàn: lớp agent nằm sau interface `Analyzer` (SkipAnalyzer cho production, FakeAnalyzer cho test), nên chỉ nhóm test gọi API thật mới cần key.

