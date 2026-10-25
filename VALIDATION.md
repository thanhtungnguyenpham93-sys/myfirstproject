# Kết quả xác minh

- 20/20 kiểm thử đạt, không bỏ qua bài nào trong lần chạy có màn hình ảo Xvfb.
- Đã kiểm tra giao diện: xem trước, xuất video, chặn khởi chạy trùng, hủy tác vụ, khôi phục các nút và hiển thị thanh xuất ở cửa sổ 900 × 700.
- Đã xuất MP4 thật theo chế độ riêng và ghép; ffprobe xác nhận H.264/yuv420p, độ phân giải, thời lượng và số khung hình. FFmpeg giải mã lại để kiểm tra ảnh đầu và các khung giữ cuối.
- Đã kiểm tra dữ liệu cấu hình hỏng, lỗi ghi cấu hình, ảnh lỗi, EXIF, alpha, giới hạn kích thước ảnh, thiếu FFmpeg, encoder lỗi và bảo vệ video sẵn có.
- Đã xuất riêng một video HD 1280 × 720, 24 FPS, 60 khung, dài 2,5 giây từ ảnh minh họa tổng hợp.
- Môi trường kiểm thử: Linux, Python 3.12.14, NumPy 2.3.5, Pillow 12.3.0, FFmpeg 7.1.5; giao diện chạy qua Tk/Xvfb với font DejaVu Sans.
- Chưa kiểm thử trực tiếp trên Windows/macOS hoặc với toàn bộ định dạng ảnh mà Pillow hỗ trợ. Chưa benchmark tải lớn 200 ảnh hoặc video dài.

Chạy lại bằng `python -m unittest -v`. Nếu máy không có màn hình hoặc FFmpeg/ffprobe, các kiểm thử phụ thuộc tương ứng sẽ báo skipped.
