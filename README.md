# Pencil Video Studio 3.1.1 — vẽ ảnh thành video

Ứng dụng cho Windows 10/11 x64: đưa nhiều ảnh vào, tự nhận diện vùng nổi bật và chữ, lập các đường nét rồi tạo video bút chì vẽ lần lượt. AI chạy trên máy, ảnh không được gửi lên dịch vụ bên ngoài.

## Tải và mở trên Windows

**Bản portable, không cần Python:** mở mục **Releases**, tải `PencilVideoStudio-Windows-x64.zip` của bản dựng đã hoàn tất. Giải nén **toàn bộ** rồi mở `PencilVideoStudio/PencilVideoStudio.exe`. Giữ thư mục `_internal` đi kèm; không chỉ chép riêng tệp `.exe`. Bản portable gồm Python runtime, OpenCV, mô hình chủ thể, mô hình vùng chữ và FFmpeg. Sau khi tải và giải nén, xử lý được khi không có mạng.

[Trang tải các bản phát hành](https://github.com/thanhtungnguyenpham93-sys/myfirstproject/releases)

**Bản mã nguồn:** tải ZIP của nhánh `pencil-video-studio-v3`, giải nén, cài **Python 3.12 x64** từ python.org (có Python Launcher và Tcl/Tk). Chạy `Setup-Windows.bat` một lần với Internet, rồi mở `Start-Windows.bat`. Lần thiết lập đầu tải thư viện và mô hình U²-Net khoảng 4,6 MB, có kiểm tra checksum. Không cần tự cài FFmpeg riêng.

**Tự tạo portable:** sau bước thiết lập, mở `Build-Windows.bat`. Kết quả ở `dist/PencilVideoStudio/`. Cách này cần Windows; tệp exe Windows không được tạo bằng cách đổi đuôi một tệp Python trên Linux.

## Quy trình sử dụng

1. Trong **Ảnh đầu vào**, thêm JPG/JPEG, PNG, WEBP, BMP, TIFF hoặc GIF; đổi thứ tự bằng ↑/↓. Ảnh động dùng khung đầu. Ảnh trong suốt được ghép trên giấy trắng; hướng EXIF được áp dụng.
2. Trong **Thiết lập vẽ → Video**, chọn YouTube, TikTok/Reels/Shorts, Facebook Feed hoặc kích thước khác.
3. Trong **Bút & nét**, chọn loại bút, độ dày, tốc độ và độ mềm. Trong **Bàn tay**, chọn chỉ hiện bút, tay phải cầm bút hoặc tay trái cầm bút, màu da và kích thước tay **50–200%** bằng thanh kéo hoặc nhập số. Chọn trực tiếp **Tay phải cầm bút** hoặc **Tay trái cầm bút**: hình minh họa bên dưới đổi ngay và lựa chọn này được áp dụng khi xuất MP4. Chọn **Ẩn bút và bàn tay** nếu không muốn hiển thị. Cỡ tay, cỡ bút hiển thị và độ dày nét được chỉnh riêng.
4. Trong **Chủ thể & chữ**, chọn tách chủ thể bằng AI, theo vùng trung tâm hoặc tắt; chọn thứ tự vẽ. Có thể bật/tắt nhận diện chữ và ưu tiên khuôn mặt.
5. Bấm **Xem vùng** để kiểm tra: xanh lá = chủ thể, vàng = chữ, xanh dương = khuôn mặt. Bấm **Xem tranh** để xem kết quả hoặc **Vẽ thử 6s** để xem thứ tự nét trên bản xem trước giảm kích thước.
6. Chọn thư mục, bật ghép nếu cần và bấm **Xuất MP4**. Chờ thông báo **Đã xuất**; 100% khung hình vẫn cần bước hoàn tất MP4.

## Những gì bản 3 thực hiện

| Yêu cầu | Cách thực hiện |
|---|---|
| Vẽ từng chi tiết | Lấy đường viền bằng OpenCV, làm mềm đường cong, vẽ tăng dần dọc theo chiều dài từng nét; bút nhấc khi đi sang nét khác |
| Tô sắc độ | Các nét đánh bóng cong và đan chéo trong vùng tối, kết hợp lớp sắc độ graphite và vân giấy |
| Ưu tiên chủ thể | U²-Net tách vùng nổi bật; bộ phát hiện khuôn mặt chính diện ưu tiên chi tiết mặt trong vùng chủ thể |
| Ưu tiên chữ | Mô hình PP-OCR phát hiện vùng chữ; đường nét bám ảnh chữ gốc, không thay nội dung bằng font khác |
| Chọn thứ tự | Chủ thể → nền → chữ; chủ thể → chữ → nền; chữ → chủ thể → nền; nền → chủ thể → chữ; hoặc không chia vùng |
| Loại bút | 2H, HB, 2B, 6B, than chì; mỗi loại thay đổi độ đậm, độ rộng và hạt giấy |
| Tay cầm bút | Tay phải/tay trái dạng minh họa vector tích hợp, ba màu da; phóng to 50–200% quanh điểm cầm, đầu bút bám theo nét |
| Kích thước và tốc độ | Cỡ hình bút 20–200; nét 0,4–6; tốc độ bút 0,25–4×; tốc độ đánh bóng 0,5–6× |
| Điện ảnh | Zoom chậm liên tục hướng về chủ thể, tối viền nhẹ, giấy có hạt, chuyển cảnh mềm giữa các ảnh được ghép |
| Hàng loạt | Xuất riêng từng ảnh hoặc ghép thành một MP4; giữ video đã hoàn tất nếu ảnh sau bị lỗi |
| Chạy độc lập | Bản Windows portable đóng gói thư viện, mô hình và encoder, không cần Python trên máy nhận |

Các nét được tái dựng từ ảnh bằng thị giác máy tính, không phải ghi lại nét vẽ của một họa sĩ. Chữ được dò vị trí và vẽ lại theo hình dạng pixel; chương trình không đọc hiểu nội dung chữ hay mô phỏng chính xác thứ tự viết tay của từng ký tự.

Bàn tay là hình minh họa có ngón tay đặt trước/sau thân bút, không phải video bàn tay thật. Tay/bút chỉ xuất hiện trong lúc vẽ và ẩn khi tranh hoàn tất. Dùng **Vẽ thử 6s** để xem bàn tay chuyển động; **Xem tranh** chỉ hiển thị kết quả cuối. Tay lớn có thể che nhiều chi tiết đang vẽ hoặc nằm một phần ngoài khung; giảm cỡ tay nếu cần. Cấu hình cũ mặc định vẫn chỉ hiện bút.

## Preset mạng xã hội

| Preset | Độ phân giải | FPS mặc định |
|---|---|---|
| YouTube ngang | 1920 × 1080 | 30 |
| TikTok / Facebook Reels / YouTube Shorts | 1080 × 1920 | 30 |
| Facebook Feed | 1080 × 1350 | 30 |
| Facebook vuông | 1080 × 1080 | 30 |

Chọn preset tự đặt FPS, chế độ giữ toàn ảnh và vùng an toàn. Video dùng MP4/H.264/yuv420p và faststart. Vùng an toàn dọc chừa thêm phía dưới và bên phải để giảm bị các nút giao diện che; đây là bố cục gợi ý, không phải cam kết mọi phiên bản ứng dụng đều dùng cùng vùng che. Bạn có thể tắt vùng an toàn, đổi FPS hoặc cắt để lấp đầy khung.

Ứng dụng xuất tệp để bạn đăng, không tự đăng video, không tự chọn nhạc và không bảo đảm đạt yêu cầu kiếm tiền hay phân phối của từng nền tảng.

## Chọn thông số để nét mềm hơn

- Bắt đầu với **HB**, độ dày **1–1,3**, mức chi tiết **0,65–0,8**, độ uốn mềm **0,8**.
- Chọn **2H** nếu nét đang quá đậm; chọn **2B/6B** nếu muốn nhiều độ đậm và sắc độ hơn.
- Đặt thời gian vẽ **0** để tự tính theo lượng nét, giới hạn 6–180 giây trước hệ số tốc độ. Đặt một số dương để chủ động thời gian. Tốc độ bút 2× làm thời gian vẽ còn khoảng một nửa, thời gian giữ tranh cuối không đổi.
- Thời gian quá ngắn trên một ảnh nhiều chi tiết sẽ khiến nhiều nét hoàn thành trong mỗi khung; hãy tăng thời gian hoặc giảm tốc độ nếu muốn thấy đầu bút đi chậm.
- Để giữ nguyên chân dung và chữ, nên dùng **Vừa khung**. Zoom khoảng **0,02–0,03**, tối viền **0,04–0,08** tạo chuyển động nhẹ mà ít cắt nội dung.
- Nhận diện sai chủ thể: kiểm tra **Xem vùng**, thử **Vùng trung tâm**, đổi thứ tự hoặc tắt phân vùng. Bản này chưa có công cụ tô sửa mask bằng tay.

## Dòng lệnh

```bash
python -m pip install -r requirements.txt
python model_assets.py
python pencil_video_studio.py
```

Xuất dọc cho mạng xã hội:

```bash
python pencil_video_studio.py --headless "anh1.jpg" "anh2.png" --platform vertical --merge --output videos --pencil-type 2b --line-width 1.2 --pen-speed 1 --priority subject_background_text
```

Chạy không phân vùng AI/chữ:

```bash
python pencil_video_studio.py --headless "anh.png" --subject-detection center --no-text --duration 20 --camera 0 --output videos
```

Thêm tay phải cầm bút, cỡ 125%, màu da trung bình:

```bash
python pencil_video_studio.py --headless "anh.png" --tool-style right_hand --hand-size 125 --skin-tone medium --output videos
```

`--tool-style left_hand` chọn tay trái; `--no-pencil` ẩn cả tay và bút. Tất cả chế độ tay đã nằm sẵn trong ứng dụng, không cần tải thêm tài nguyên.

`--size` ghi đè độ phân giải preset; `--duration 0` dùng thời gian tự động. Xem toàn bộ tùy chọn bằng `--help`. `--config` chỉ định tệp cấu hình giao diện; chế độ headless dùng các đối số dòng lệnh. Mã thoát: 0 thành công, 1 lỗi, 130 hủy. Ctrl+C yêu cầu dừng và dọn encoder.

## Dữ liệu và giới hạn thực tế

- AI U²-Net nhận diện vùng nổi bật, không bảo đảm tách đúng mọi người/vật trong ảnh có nền phức tạp. Bộ nhận diện mặt phù hợp mặt chính diện; có thể bỏ sót góc nghiêng.
- Detector chữ có thể bỏ sót chữ nhỏ, chữ trang trí hoặc chữ sát nền. Chữ tiếng Việt giữ nguyên hình dạng từ ảnh nếu vùng chữ được phát hiện; chương trình không sửa chính tả hay dựng lại dấu bị mờ.
- Có tối đa 200 ảnh/tác vụ, 40 triệu pixel/ảnh nguồn. Video tối đa 1920 pixel mỗi chiều, 60 FPS. Ảnh HEIC/RAW chưa có bộ đọc riêng.
- Bản đồ nét được lập ở cạnh dài tối đa 900 pixel để cân bằng tốc độ và chi tiết; nét được vẽ tại độ phân giải xuất. Chữ rất nhỏ nên dùng ảnh rõ và crop nội dung hợp lý trước khi đưa vào.
- Cần RAM cho ảnh, bản đồ vùng và mô hình. Full HD chậm hơn HD. Không bảo đảm thời gian dựng nhanh hơn thời lượng video trên mọi CPU.
- Hoạt ảnh không làm nhân vật cử động như phim: chuyển động là đầu bút, tiến trình vẽ và camera nhẹ trên bức tranh.
- Cấu hình lưu trong `%APPDATA%/pencil-video-studio/settings.json` trên Windows. Phiên bản 3 đọc được cấu hình phiên bản 2; những thông số mới nhận giá trị mặc định.
- Mỗi lần xuất tạo thư mục mới và không ghi đè video sẵn có. Hủy bình thường dọn tệp dở; tắt máy/kill cưỡng bức có thể để lại tệp tạm hoặc tệp rỗng.

## Kiểm thử và bản dựng

```bash
python -m unittest -v
python pencil_video_studio.py --self-test --output smoke-output
```

Self-test chạy cả hai mô hình, lập nét, xuất MP4 và giải mã lại đủ số khung. Báo cáo nằm ở `smoke-output/self-test.json`; lỗi ở `self-test-error.txt`. Bộ unittest kiểm tra thêm thứ tự vùng, vùng chưa đến lượt vẫn trắng, điều khiển bút, hủy, cấu hình, giao diện và encoder.

Workflow **Build Windows portable** chạy trên Windows, kiểm tra mã nguồn, đóng gói bằng PyInstaller, kiểm tra chính exe rồi mới đăng bản phát hành. Chỉ tải bản dựng đã hoàn tất thành công. Xem `VALIDATION.md` để biết những gì đã được xác minh; xem `THIRD_PARTY.md` về các thành phần bên ngoài.
