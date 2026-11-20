# Tạo Admin và đưa Swoosh Store lên Render

## Tài khoản quản trị
- **Tên đăng nhập:** `admin`
- **Mật khẩu:** do chủ website đặt trong `SWOOSH_ADMIN_PASSWORD` trên Render, tối thiểu 12 ký tự.
- **URL:** `https://<ten-web>.onrender.com/#login?role=admin`
- Chọn **Quản trị viên** ở ô Vai trò trước khi đăng nhập.

## Các bước nhanh
1. Giải nén file ZIP. Đưa **nội dung thư mục** lên kho GitHub (file `render.yaml` phải nằm ở thư mục gốc repo).
2. Render → **New → Blueprint** → Connect GitHub repo.
3. Render yêu cầu biến `SWOOSH_ADMIN_PASSWORD`: nhập mật khẩu admin của bạn. **Không chia sẻ mật khẩu hoặc lưu vào GitHub.**
4. Deploy, mở URL Render cung cấp. Trang chủ dùng `/`; trang đăng nhập Admin dùng `/#login?role=admin`.
5. Để người khác xem và đặt hàng, chỉ cần gửi cho họ URL trang chủ. Không cung cấp tài khoản admin cho người lạ.

## Dùng New Web Service thủ công
- Runtime: `Python`
- Build command: `echo ready`
- Start command: `python store_server.py`
- Health check path: `/api/health`
- Environment: `SWOOSH_HOST=0.0.0.0`, `SWOOSH_COOKIE_SECURE=1`, `TRUST_PROXY=1`, `SWOOSH_ADMIN_USERNAME=admin`, `SWOOSH_ADMIN_PASSWORD=<mat-khau-tu-chon>`.

## Giữ dữ liệu sau khi deploy
Trên gói Free của Render, hệ thống file tạm mất dữ liệu SQLite và ảnh mới upload khi service spin down/restart/redeploy. Mỗi lần có DB mới, Admin có thể được khởi tạo lại bằng mật khẩu trong Environment, **nhưng các đơn hàng/tài khoản khách trước đó có thể mất**. Bản cấu hình này phù hợp để trình diễn và kiểm tra. Muốn vận hành thực tế lâu dài, cần lưu trữ bền vững (ví dụ Web Service trả phí với persistent disk), và sao lưu dữ liệu.

## Kiểm tra trên máy
Để thử khởi tạo Admin bằng biến môi trường (PowerShell):

```powershell
$env:SWOOSH_ADMIN_USERNAME = "admin"
$env:SWOOSH_ADMIN_PASSWORD = "MOT_MAT_KHAU_RIENG_TOI_THIEU_12_KY_TU"
python store_server.py
```

Nếu không đặt biến môi trường, có thể tạo admin thủ công:
`python store_server.py create-admin`
