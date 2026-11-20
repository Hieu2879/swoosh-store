# SWOOSH STORE - TẠO ADMIN THEO CÁCH GEMINI (DÙNG ĐƯỢC TRÊN RENDER)

## 1. Cách khuyên dùng: Thiết lập trực tiếp ở Render (Cách 2)

**Đây là cách dùng cho website mà mọi người có thể truy cập. Không cần upload file SQLite.**

1. Giải nén ZIP, đưa **toàn bộ các file bên trong** lên thư mục gốc của GitHub repository. Ở thư mục gốc phải thấy `store_server.py`, `index.html`, `render.yaml`.
2. **Nếu chưa có website ở Render:** vào https://dashboard.render.com/ > **New > Blueprint**, chọn repository vừa đẩy. Khi Render hỏi mật khẩu `SWOOSH_ADMIN_PASSWORD`, bạn tự nhập mật khẩu mạnh tối thiểu 12 ký tự.
3. **Nếu đã có service `swoosh-store` trên Render:** đảm bảo GitHub repository đang có bản code mới. Trên Render vào `swoosh-store` > **Environment** > **Add Environment Variable**, thêm các biến trong bảng dưới; chọn **Save, rebuild, and deploy**. Kiểm tra Start Command là `python store_server.py` (dịch vụ dùng runtime Python hoặc Dockerfile đi kèm).
4. Đợi trạng thái deploy thành **Live**, kiểm tra `https://<ten-service>.onrender.com/api/health`.
5. Mở `https://<ten-service>.onrender.com/#login?role=admin`, chọn **Quản trị viên**, nhập tên `admin` và mật khẩu của bạn.

| Environment key | Value |
|---|---|
| `SWOOSH_ADMIN_USERNAME` | `admin` |
| `SWOOSH_ADMIN_PASSWORD` | Mật khẩu mạnh do bạn tự chọn, **ít nhất 12 ký tự** |
| `SWOOSH_HOST` | `0.0.0.0` |
| `SWOOSH_COOKIE_SECURE` | `1` |
| `TRUST_PROXY` | `1` |

**Không đặt mật khẩu trong source code, `.env.example`, `render.yaml`, hình chụp màn hình hoặc GitHub.** Khi máy chủ khởi động, nó tạo Admin nếu tài khoản này chưa tồn tại. Đổi `SWOOSH_ADMIN_PASSWORD` trên một DB đã có Admin **không** tự đổi mật khẩu cũ; phải đổi mật khẩu qua cơ chế quản trị phù hợp hoặc tạo lại DB demo.

## 2. Tạo Admin trên máy Windows (tham khảo Cách 1 của Gemini)

File `create-admin.bat` **đã được sửa để gọi Python + SQLite**. File `create-admin-java.bat` giữ lại bản Java/SQL Server cũ.

1. Cài Python 3.10+ nếu chưa có.
2. Giải nén dự án, mở thư mục và nhấp đúp `create-admin.bat`.
3. Nhập mật khẩu ít nhất 12 ký tự trong cửa sổ lệnh. Admin cục bộ sẽ được lưu trong `data/swoosh.sqlite3`.
4. Chạy `python store_server.py` rồi đăng nhập ở `http://127.0.0.1:8000/#login?role=admin`.

**Không làm theo đoạn Gemini đề nghị xóa `data/*.sqlite3*`/`data/*.db*` khỏi `.gitignore` và `.dockerignore`.** Database có thể chứa thông tin khách, đơn hàng, mật khẩu băm và không nên đưa lên GitHub. Nếu bạn **đã lỡ commit** `data/swoosh.sqlite3` trước đó, cần xóa khỏi Git tracking và lịch sử công khai nếu cần, và thay các thông tin đăng nhập bị lộ. Tài khoản tạo trên máy chỉ dùng tại máy; để có Admin trên Render, hãy làm bước 1.

## 3. Trường hợp Gemini gợi ý mở SQLite để sửa `role` (Cách 3)

Không cần dùng cách này. Dự án đã có lệnh tạo Admin chính thống và bootstrap qua biến môi trường; việc tự sửa dữ liệu dễ gây lỗi và không giải quyết được vấn đề lưu trữ trên Render Free.

## 4. Ghi nhớ về Render Free

Theo tài liệu Render, **Free Web Service sử dụng hệ thống file tạm**: các thay đổi vào SQLite, ảnh tải lên, đơn hàng, tài khoản khách có thể mất sau spin-down, restart hay redeploy. Cấu hình biến môi trường sẽ khởi tạo lại Admin mỗi khi DB mới xuất hiện, nhưng **không giúp giữ lại đơn hàng**. Demo/học tập: dùng Free được. Bán hàng thực tế: cần lưu trữ bền vững và sao lưu thường xuyên (ví dụ dịch vụ trả phí có Persistent Disk và chuyển toàn bộ dữ liệu/ảnh sang đó).

Tài liệu chính thức:
- https://render.com/docs/configure-environment-variables
- https://render.com/docs/free
- https://render.com/docs/disks

## 5. Nếu đăng nhập không được

- Nếu deploy báo thiếu `SWOOSH_ADMIN_PASSWORD`: vào Environment, thêm biến rồi deploy lại.
- Nếu server báo mật khẩu ngắn: dùng mật khẩu từ 12 đến 256 ký tự.
- Nếu không thấy Admin: kiểm tra service đang chạy bản mới có `bootstrap_admin_from_environment()` và Start Command là `python store_server.py`.
- Nếu sai mật khẩu với database đã tồn tại: bootstrap không ghi đè mật khẩu cũ.
- Nếu website hiện chỉ chạy backend Java + SQL Server: cần chuyển Start Command/runtime sang Python hoặc cấu hình riêng cho Java; chỉ chỉnh Environment trên service Java không tự kích hoạt logic Python.
