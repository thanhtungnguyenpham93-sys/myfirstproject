# Pencil Video Studio 2.0

Ứng dụng tiếng Việt biến ảnh thành video vẽ chì, chạy trên máy với Python, Pillow, NumPy và FFmpeg. Có giao diện Tkinter và chế độ dòng lệnh cho máy chủ không có màn hình.

## Về bản nâng cấp này

Tệp được cung cấp chỉ là đoạn cuối 4.592 byte của một chương trình: bắt đầu bằng một khối `if` thụt lề, thiếu imports, lớp `App`, bảng preset, bộ xử lý ảnh và hàm `run_batch`. Bản này xây dựng lại ứng dụng có thể chạy độc lập từ các chức năng nhận diện được trong đoạn đó. Tệp đính kèm gốc được giữ nguyên.

Các tùy chọn cũ chỉ xuất hiện tên như nhận diện chủ thể/chữ, hatch, cinematic và camera không có phần triển khai trong tệp nguồn. Bản này không giả lập những chức năng đó bằng các nút không hoạt động và không nhập cấu hình cũ không rõ định dạng. Đây là hiệu ứng vẽ bằng xử lý ảnh, không phải mô hình AI dựng lại nét bút hoặc OCR. Video không kèm âm thanh.

## Các chức năng chính

- Chì đen trắng hoặc chì màu; hai giai đoạn phác nét và tô sắc độ.
- Vẽ ngang, dọc hoặc theo ô ngẫu nhiên; tùy chọn hiện bút chì và vân giấy.
- Khung ngang/dọc HD, Full HD, khung vuông; giữ toàn ảnh hoặc cắt để lấp đầy; viền an toàn.
- Chọn, xóa, đổi thứ tự ảnh; xuất riêng hoặc ghép thành một video.
- Xem trước ảnh hoàn thiện và khung hình trong lúc xuất; tiến độ và thời gian còn lại ước tính.
- Xử lý EXIF, ảnh trong suốt và đường dẫn tiếng Việt. GIF/ảnh động sử dụng khung đầu tiên.
- MP4 H.264/yuv420p, tối ưu phát trực tuyến với `faststart`.
- Giao diện chỉ cập nhật trên luồng chính. Xử lý ảnh và FFmpeg chạy nền; ảnh xem trước không tích tụ trong hàng đợi.
- Hủy tác vụ và đóng cửa sổ có dọn tiến trình/tệp tạm. Video đã hoàn tất được giữ lại.
- Mỗi lần xuất tạo thư mục mới; không ghi đè video sẵn có.
- Lưu cấu hình nguyên tử; báo rõ dữ liệu hỏng, giá trị không hợp lệ, ảnh lỗi và FFmpeg bị thiếu.

## Cài đặt

Yêu cầu **Python 3.10 trở lên**, **FFmpeg có encoder libx264** và Tkinter nếu dùng giao diện.

```bash
python -m venv .venv
```

Kích hoạt môi trường trên Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Trên macOS/Linux:

```bash
source .venv/bin/activate
```

Cài thư viện:

```bash
python -m pip install -r requirements.txt
```

Cài FFmpeg và bảo đảm `ffmpeg -version` chạy được trong terminal:

- Windows: cài FFmpeg từ nguồn được liên kết trên https://ffmpeg.org/download.html, thêm thư mục `bin` vào PATH rồi mở lại terminal.
- macOS có Homebrew: `brew install ffmpeg`. Python phải có hỗ trợ Tkinter; bản cài từ python.org có cung cấp Tk.
- Debian/Ubuntu dùng Python hệ thống: `sudo apt install ffmpeg python3-tk python3-venv`.

Kiểm tra Tkinter bằng `python -m tkinter`; cần môi trường desktop. Các bản Python tự biên dịch/độc lập có thể cần cài Tkinter phù hợp với chính interpreter đó.

## Chạy giao diện

```bash
python pencil_video_studio.py
```

1. Thêm ảnh và sắp xếp thứ tự bằng nút ↑/↓.
2. Chọn khung hình, hiệu ứng, thời gian vẽ và thời gian giữ cuối **cho mỗi ảnh**.
3. Chọn một ảnh, bấm **Xem trước ảnh đã chọn** để kiểm tra bố cục. Đây là bản xem trước giảm kích thước, có thể khác đôi chút về độ mềm so với video xuất.
4. Chọn thư mục, bật ghép nếu cần, rồi bấm **Xuất MP4**.
5. Bấm **Dừng** để hủy. Chờ ứng dụng dọn dẹp; không cần đóng cưỡng bức.

Mặc định mỗi ảnh vẽ 8 giây và giữ 2 giây, ở 24 FPS. Thời lượng thực làm tròn theo khung hình, tối thiểu 2 khung vẽ. Chỉ hỗ trợ tối đa 200 ảnh mỗi tác vụ và 40 triệu pixel mỗi ảnh nguồn để giới hạn bộ nhớ. File ảnh phải là định dạng được Pillow trên máy hỗ trợ; HEIC/RAW không được cài thêm trong gói này.

Cấu hình tự lưu khi xuất hoặc đóng giao diện:

- Windows: `%APPDATA%\pencil-video-studio\settings.json`
- macOS: `~/Library/Application Support/pencil-video-studio/settings.json`
- Linux: `$XDG_CONFIG_HOME/pencil-video-studio/settings.json` hoặc `~/.config/pencil-video-studio/settings.json`

Có thể đổi vị trí bằng `--config duong_dan/settings.json`. Cấu hình lưu đường dẫn ảnh và thông số, không sao chép ảnh nguồn. Nếu cấu hình hỏng, ứng dụng thông báo và dùng mặc định; lần lưu tiếp theo sẽ thay thế nó bằng cấu hình mới.

## Chạy không có giao diện

```bash
python pencil_video_studio.py --headless "anh_1.jpg" "anh_2.png" --output "videos" --merge --size 1280x720 --fps 24 --duration 8 --hold 2
```

Ví dụ video dọc, chì màu:

```bash
python pencil_video_studio.py --headless "anh.png" --output "videos" --size 720x1280 --effect color --order vertical --fit cover --safe-margin
```

Xem mọi tùy chọn bằng `python pencil_video_studio.py --help`. Các tùy chọn render trên dòng lệnh áp dụng với `--headless`; giao diện dùng cấu hình đã lưu. `--config` chỉ định tệp cấu hình giao diện, không ghi đè các đối số headless. Ctrl+C/SIGTERM yêu cầu hủy và dọn tệp tạm; mã thoát 130 khi hủy, 1 khi lỗi, 0 khi thành công.

Đầu ra nằm trong thư mục `pencil_YYYYMMDD_HHMMSS_<mã_ngẫu_nhiên>`. Chế độ ghép tạo `pencil_merged.mp4`; chế độ riêng đánh số từng ảnh. Nếu một ảnh sau bị lỗi, thông báo trả về vị trí các video trước đã xuất thành công. Nếu ghép bị lỗi hoặc bị hủy, video ghép chưa hoàn tất sẽ được xóa. Mất điện/kill cưỡng bức có thể để lại tệp `.render-*.mp4` và tệp đầu ra rỗng trong thư mục tác vụ.

## Hiệu năng và giới hạn

Khung hình được chuyển từng khung đến FFmpeg, không giữ toàn bộ video trong bộ nhớ. Bộ nhớ vẫn phụ thuộc độ phân giải và kích thước ảnh nguồn; Full HD cần nhiều RAM và thời gian hơn HD. Khi dừng, bước xử lý ảnh Pillow/NumPy đang chạy cần kết thúc trước khi kiểm tra tín hiệu hủy. Encoder có luồng giám sát riêng để ngắt pipe khi hủy.

Thời gian còn lại chỉ là ước tính theo tốc độ xử lý, không bao gồm chính xác thời gian hoàn tất MP4. Tiến độ khung hình 100% chưa đồng nghĩa tệp đã hoàn tất; chờ thông báo **Đã xuất**.

## Kiểm thử

```bash
python -m unittest -v
```

Bộ kiểm thử dùng thư mục tạm và ảnh tổng hợp: cấu hình, EXIF, transparency, hiệu ứng, hủy, lỗi encoder, bảo vệ tệp sẵn có, xuất/ghép MP4 thật, giải mã lại khung hình và kiểm tra codec, kích thước, thời lượng, số khung. Các bài tích hợp cần `ffmpeg`/`ffprobe`; các bài giao diện cần Tkinter và màn hình (hoặc Xvfb trên Linux). Bài không đáp ứng điều kiện được báo **skipped**, không tính là đã xác minh.

Đã kiểm thử trên Linux với Python 3.12, NumPy 2.3.5, Pillow 12.3.0 và FFmpeg 7.1.5. Chưa chạy trực tiếp trên Windows/macOS.
