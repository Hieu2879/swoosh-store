# Swoosh Store - Cửa Hàng Giày Thể Thao Trực Tuyến

Trang web thương mại điện tử chuyên cung cấp các mẫu giày thể thao đỉnh cao (Air Jordan, Dunk Low, Air Force 1). Dự án bao gồm giao diện người dùng hiện đại (Single Page Application), giỏ hàng, quy trình đặt hàng, cùng trang quản trị dành riêng cho Administrator và Staff (nhân viên).

---

> **Hướng dẫn tạo Admin trên Render theo 3 cách Gemini:** xem [HUONG_DAN_GEMINI_RENDER_ADMIN.md](HUONG_DAN_GEMINI_RENDER_ADMIN.md). Cách được khuyên dùng là `SWOOSH_ADMIN_USERNAME`/`SWOOSH_ADMIN_PASSWORD` trong Render Environment.

## 🚀 Các Tối Ưu Hóa Đã Thực Hiện Để Đăng Lên Web Công Khai

1. **Tối ưu hiệu năng & dung lượng (Giảm 97% kích thước trang)**:
   - Tách bỏ các chuỗi base64 nhúng trùng lặp trong file HTML, chuyển sang tải ảnh trực tiếp từ thư mục tĩnh `images/shoes/` với cơ chế SVG fallback mượt mà.
   - Dung lượng file HTML giảm từ **~2.38 MB** xuống còn **~76 KB**, giúp tốc độ tải trang (FCP / LCP) đạt mức tức thì trên cả thiết bị di động và mạng 3G/4G.
   - Bổ sung `index.html` làm trang chủ chuẩn (tương thích mọi web server như Nginx, Caddy, Vercel, Netlify, Cloudflare).
   - Thêm cache header `Cache-Control: public, max-age=604800` cho tài nguyên ảnh tĩnh.

2. **Khắc phục lỗ hổng bảo mật nghiêm trọng**:
   - **Chặn truy cập file nhạy cảm**: Áp dụng cơ chế whitelist kiểm duyệt đường dẫn tĩnh. Chặn tuyệt đối việc tải trực tiếp cơ sở dữ liệu `swoosh.sqlite3`, mã nguồn `store_server.py`, file cấu hình `.env`, thư mục `__pycache__` hay file ẩn.
   - **Bảo mật Cookie & Session**: Tự động nhận diện HTTPS hoặc cờ `SWOOSH_COOKIE_SECURE=1` để bật thuộc tính `Secure`, `HttpOnly`, `SameSite=Lax`.
   - **Chống Brute-force & Hỗ trợ Reverse Proxy**: Rate-limiting tự động nhận diện IP gốc người dùng qua header `X-Forwarded-For` (khi đứng sau Cloudflare, Nginx, Render load balancer), tránh tình trạng 1 người đăng nhập sai làm khóa toàn bộ người dùng khác.

3. **Tối ưu hóa cơ sở dữ liệu (SQLite Concurrency)**:
   - Kích hoạt chế độ **WAL (Write-Ahead Logging)** và `PRAGMA synchronous = NORMAL`, cho phép nhiều khách hàng cùng lúc xem sản phẩm, tạo phiên và đặt hàng mà không bị lỗi nghẽn khóa database (`database is locked`).

4. **SEO & Mạng Xã Hội**:
   - Tích hợp thẻ meta Open Graph (Facebook / Zalo preview), Twitter Card, mô tả sản phẩm và favicon SVG sắc nét.
   - Bổ sung sẵn endpoint chuẩn cho công cụ tìm kiếm: `/robots.txt` và `/sitemap.xml`.

5. **Sẵn sàng triển khai đa nền tảng (Cloud / Docker / VPS)**:
   - Tự động nhận diện cổng `$PORT` và biến `$HOST` trên các nền tảng Cloud (Render, Railway, Fly.io, Heroku, Docker).
   - Bổ sung endpoint kiểm tra sức khỏe hệ thống: `/api/health`.
   - Lệnh `create-admin` hỗ trợ cả giao diện đồ họa (GUI) lẫn terminal (CLI / Headless Linux) qua `getpass` và tham số dòng lệnh mà không bị crash.

---

## 💻 1. Chạy Thử Nghiệm Tại Máy Cục Bộ (Local)

Yêu cầu: Python 3.10 trở lên (không cần cài thêm thư viện ngoài).

### Bước 1: Tạo tài khoản Quản trị viên (Admin)
Mở cửa sổ dòng lệnh (Terminal / PowerShell) tại thư mục dự án và chạy:
```powershell
python store_server.py create-admin
```
Nhập tên đăng nhập và mật khẩu (tối thiểu 12 ký tự). Mật khẩu được ẩn an toàn khi nhập.

*(Hoặc có thể tạo nhanh qua tham số: `python store_server.py create-admin --username admin --password "MatKhauBaoMat123!"`)*

### Bước 2: Khởi động máy chủ
```powershell
python store_server.py
```

Mở trình duyệt truy cập: <http://127.0.0.1:8000>

---

## Use case theo phân công Nguyễn Đức Tuấn Đạt

Website hiện triển khai các chức năng được giao trên giao diện quản trị và cửa hàng:

- Voucher: quản trị mã giảm giá, thời hạn, giá trị đơn tối thiểu, giới hạn lượt dùng; khách hàng có thể áp mã ở bước thanh toán. Máy chủ luôn tính lại mức giảm khi tạo đơn.
- Khách hàng: Admin tra cứu danh sách khách từ đơn hàng theo tên/số điện thoại, xem số đơn, tổng giá trị đơn chưa hủy, điểm và hạng thành viên.
- Thống kê doanh thu: Admin chọn khoảng ngày tối đa 366 ngày, xem doanh thu ròng và giá trị đơn trung bình theo các đơn hoàn tất; đơn đã xác nhận/đang giao được hiển thị riêng, chưa cộng vào doanh thu. Ngày thống kê theo múi giờ Việt Nam.
- Nhật ký hoạt động: lưu các lần đăng nhập, thay đổi quản trị, cập nhật đơn, tải/xóa ảnh và cảnh báo đơn hàng rủi ro; chỉ Admin được tra cứu.
- Vai trò nhân viên: tạo vai trò và phân quyền xem/cập nhật đơn hàng; quyền được kiểm tra lại ở API, không chỉ ẩn nút trên giao diện.
- Thành viên & điểm: đơn được cộng điểm khi chuyển sang hoàn tất; Admin cấu hình các hạng/mốc điểm. Khách tra cứu bằng số điện thoại cùng mã đơn đã hoàn tất.
- Danh sách yêu thích được lưu trong trình duyệt; hướng dẫn quy đổi size EU/US/UK/CM; danh sách đơn có bộ lọc tìm kiếm và trạng thái.
- Thư viện ảnh nhận PNG/JPEG/WebP tối đa 700 KB, lưu vào `images/products/`; Admin có thể xem và xóa ảnh.
- Sản phẩm bán chạy được tổng hợp từ các đơn đã xác nhận, đang giao hoặc hoàn tất.
- Chống gian lận cơ bản: giới hạn gửi lại đơn cùng số điện thoại trong thời gian ngắn và ghi cảnh báo cho đơn giá trị/số lượng cao hoặc có tần suất bất thường. Đây là quy tắc nội bộ mẫu, chưa tích hợp dịch vụ chống gian lận bên thứ ba.

Cơ sở dữ liệu được bổ sung bảng/cột tự động khi máy chủ khởi động, không cần chạy migration thủ công. Hãy sao lưu `data/swoosh.sqlite3` trước khi nâng cấp dữ liệu đang sử dụng.

---

## ☁️ 2. Triển Khai Lên Nền Tảng Cloud (Miễn phí / Tự Động)

Dự án đã có sẵn `Dockerfile`, `Procfile` và biến cấu hình chuẩn cho các dịch vụ Cloud:

### Cách triển khai lên Render (Python + tài khoản Admin tự động):
1. **Giải nén** thư mục dự án và đẩy **các file bên trong** (như `store_server.py`, `index.html`, `render.yaml`) lên GitHub. Không đẩy `data/swoosh.sqlite3` hoặc `.env` lên GitHub vì chứa dữ liệu nhạy cảm.
2. Vào [Render](https://dashboard.render.com/) → **New → Blueprint**, kết nối kho GitHub có file `render.yaml` ở thư mục gốc.
3. Khi Render yêu cầu `SWOOSH_ADMIN_PASSWORD`, nhập **mật khẩu riêng tối thiểu 12 ký tự** (không đặt mật khẩu trực tiếp trong mã nguồn hay GitHub).
4. Render tạo dịch vụ Web với `startCommand: python store_server.py`. Tên tài khoản mặc định là **`admin`** (có thể đổi bằng `SWOOSH_ADMIN_USERNAME` trong Render Environment).
5. Khi triển khai hoàn tất, mở URL `https://<ten-dich-vu>.onrender.com/#login?role=admin`, chọn **Quản trị viên**, đăng nhập bằng tài khoản `admin` và mật khẩu đã nhập ở bước 3.

Nếu tạo bằng **New → Web Service** thay vì Blueprint, đặt runtime **Python**, Start Command `python store_server.py`, và thêm biến Environment:

| Key | Value |
|---|---|
| `SWOOSH_HOST` | `0.0.0.0` |
| `SWOOSH_COOKIE_SECURE` | `1` |
| `TRUST_PROXY` | `1` |
| `SWOOSH_ADMIN_USERNAME` | `admin` |
| `SWOOSH_ADMIN_PASSWORD` | Mật khẩu riêng (ít nhất 12 ký tự; chỉ đặt trong Render Environment) |

**Tài khoản Admin chỉ được tạo mới khi chưa tồn tại.** Khởi động lại không ghi đè mật khẩu trên database đang có. Nếu đổi biến mật khẩu sau khi Admin đã được tạo, mật khẩu của tài khoản đã có sẽ không tự đổi.

> **Quan trọng với Render Free:** Đây là bản triển khai **demo**. Render Free dùng hệ thống file tạm: dữ liệu SQLite, đơn hàng, tài khoản khách và ảnh mới tải lên có thể bị mất khi dịch vụ ngủ, khởi động lại hoặc deploy lại. Tài khoản Admin vẫn được tạo lại từ biến môi trường, nhưng những dữ liệu phát sinh sẽ không được khôi phục. Để giữ dữ liệu thật, cần chuyển sang cơ sở dữ liệu lưu trữ bền vững hoặc dùng dịch vụ trả phí kèm Persistent Disk, và xử lý cả thư mục ảnh tải lên.

### Cách triển khai lên Railway:
1. Đăng nhập [Railway.app](https://railway.app) -> Chọn **New Project** -> **Deploy from GitHub repo**.
2. Railway tự động đọc `Dockerfile` và deploy trong vòng 60 giây.
3. Trong tab **Settings** -> **Networking**, nhấn **Generate Domain** để nhận tên miền HTTPS công khai.

> **Lưu ý:** Render Free không có Shell. Hãy thiết lập `SWOOSH_ADMIN_PASSWORD` trong Environment để tạo admin tự động (đã hỗ trợ trong mã nguồn), không cần chạy lệnh thủ công.

---

## 🐳 3. Triển Khai Bằng Docker & Docker Compose

Nếu bạn có máy chủ riêng hoặc dùng VPS:

### Khởi chạy nhanh bằng Docker Compose:
```bash
docker compose up -d --build
```
Dịch vụ sẽ tự động chạy ngầm tại cổng `8000`. Dữ liệu SQLite được lưu bền vững vào thư mục `./data` trên máy chủ.

### Tạo Admin bên trong Docker container:
```bash
docker compose exec swoosh-store python store_server.py create-admin
```

---

## 🛡️ 4. Triển Khai Lên VPS Linux (Nginx + Systemd + SSL)

Dự án đã cung cấp sẵn file mẫu `nginx.conf` với đầy đủ:
- Chuyển hướng tự động HTTP sang HTTPS.
- Cấu hình nén Gzip tăng tốc độ truyền tải.
- Bảo mật Rate-limiting chống DDoS nhẹ và Brute-force mật khẩu.
- Chặn tuyệt đối người lạ truy cập vào database hoặc mã nguồn.

### Các bước thiết lập trên VPS Ubuntu/Debian:
1. Cài đặt Python 3, Nginx và Certbot:
   ```bash
   sudo apt update && sudo apt install -y python3 python3-pip nginx certbot python3-certbot-nginx
   ```
2. Copy thư mục dự án vào `/var/www/swoosh-store`.
3. Tạo file service tự khởi động `/etc/systemd/system/swoosh-store.service`:
   ```ini
   [Unit]
   Description=Swoosh Store Python Web Service
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/var/www/swoosh-store
   Environment="PORT=8000"
   Environment="SWOOSH_HOST=127.0.0.1"
   Environment="SWOOSH_COOKIE_SECURE=1"
   Environment="TRUST_PROXY=1"
   ExecStart=/usr/bin/python3 store_server.py
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```
4. Kích hoạt service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now swoosh-store
   ```
5. Áp dụng cấu hình Nginx từ file `nginx.conf` của dự án và cấp chứng chỉ SSL miễn phí bằng Certbot:
   ```bash
   sudo certbot --nginx -d your-domain.com
   sudo systemctl restart nginx
   ```

---

## 📋 5. Quản Trị Hệ Thống & Bảo Mật Dữ Liệu

- **Phân quyền người dùng**:
  - **Admin**: Quản lý sản phẩm, tài khoản/vai trò nhân viên, voucher, nhật ký, hạng thành viên và media.
  - **Staff (Nhân viên)**: Được gán vai trò với quyền xem và/hoặc cập nhật trạng thái đơn hàng. Quyền mặc định là xem và cập nhật đơn.
- **Bảo vệ số Căn cước công dân (CCCD)**: Dữ liệu CCCD và ngày sinh nhân viên được lưu trong bảng `users` chỉ dành riêng cho Admin quản lý. Không bao giờ commit file `data/swoosh.sqlite3` lên GitHub hoặc kho lưu trữ công khai.
- **Sao lưu định kỳ**: Hãy thiết lập backup tự động file `data/swoosh.sqlite3` hàng ngày về lưu trữ đám mây an toàn.

## Danh mục 109 câu truy vấn (ULNL_cau_lenh_truy_van.xlsx)

- Nguồn: `java-backend/src/main/resources/queries/cau-lenh-truy-van.json` (stt, name, owner, sql, note).
- Service: `QueryCatalogService`; API quản trị (chỉ admin): `QueryController`
  - `GET /api/admin/queries?owner=Đạt` – danh sách + tham số cần truyền
  - `GET /api/admin/queries/{stt}` – chi tiết SQL và ghi chú
  - `POST /api/admin/queries/{stt}/run` – body `{"params":{"email":"a@b.c"},"commit":false}`.
    Mặc định `commit=false`: chạy rồi ROLLBACK. Tham số tùy chọn phải gửi `null` rõ ràng.
- Câu 48 (BACKUP/RESTORE) chỉ chạy thủ công trên SQL Server.
- Bảng bổ sung tự tạo khi khởi động: `user_view_history`, `shipping_zones`, `referrals`.
