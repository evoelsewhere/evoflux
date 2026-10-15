# Animate: strategy cho agent sản xuất motion trong EvoFlux

Ngày kiểm tra: 2026-10-15. Repo: [cth9191/animate][repo], snapshot
`7e5eb56feb2dd573f890e1b7b34748af43d58263`, commit ngày 2026-10-05, plugin
0.4.0. Đã đọc source và license MIT; không chạy installer, scripts, hoặc render
upstream. Node có trên PATH của máy nghiên cứu; FFmpeg/ffprobe không được tìm
thấy bằng `Get-Command`. Đây là nghiên cứu source, không phải benchmark video.

## 1. Điều đáng học nhất

Animate đóng gói kiến thức thành một quy trình sản xuất: brief → chọn cách kể →
thử look → storyboard → dựng → đo và xem → sửa. Nó tách story grammar, drawing
kit của từng style, scene code, timing, sound và công cụ kiểm tra. Kết quả là
agent có các bước cụ thể để làm và bằng chứng để quay lại sửa, thay vì chỉ được
nhắc “hãy làm video đẹp”. Repo còn dùng lại drawing functions của storyboard
cho video hoàn chỉnh. [README][repo], [Skill][skill]

README vẫn đánh dấu WebGL motion-design style là phần sắp có. GPU export
tooling không chứng minh repo đã cung cấp một bộ authoring 3D hoàn chỉnh;
không coi roadmap đó là tính năng đã chạy trong EvoFlux. [README][repo]

EvoFlux nên học cấu trúc này dưới dạng knowledge nạp theo nhu cầu. Những lựa
chọn đã có trong brief hoặc conversation được kế thừa; các bước kiểm tra story,
look và storyboard có thể thực hiện nội bộ. Không chuyển nguyên các checkpoint
xin duyệt của upstream thành các lần dừng mới trong một task đã được giao.

## 2. Tự nhận định task qua bốn quyết định

`grammar/FORMATS.md` tách cách dựng thành story engine, stage, clock và medium.
Ví dụ chronology có thể dùng shape morph; một vật đi qua trạm có thể dùng
camera theo đường đi; video có narration lấy nhịp từ câu nói. Tác giả ghi rằng
taxonomy dựa trên shot log của 16 animation và đánh dấu một số format chưa
được dựng bằng kit. Đây là các mẫu tham khảo, không phải quy luật phổ quát.
[Formats][formats]

Áp dụng vào EvoFlux:

| Task | Story/stage hợp lý | Clock | Điều cần nhìn thấy |
| --- | --- | --- | --- |
| Hành trình vận đơn | Một kiện hàng và route qua các trạm; camera theo đối tượng | Hành động hoặc narration | Scan, đổi người giữ, di chuyển, giao thành công |
| Xử lý nước mưa | Nước đi qua thiết bị, giữ màu/độ trong nhất quán | Thời gian cần để thấy cơ chế | Cặn bị giữ lại; trạng thái thay đổi vì tác động cụ thể |
| Product walkthrough | Màn hình thật, crop/zoom và cursor có mục đích | Hành động người dùng hoặc lời nói | Trigger → thay đổi UI → kết quả |
| Launch reel theo nhạc | Vài hình ảnh có chủ thể xuyên suốt, cuts theo nhạc | Track được phân tích và kiểm tra | Hook, điểm nhấn, payoff rõ |
| Dashboard để phân tích | Dashboard tương tác vẫn có thể phù hợp hơn video | Người xem tự điều khiển | Giá trị thao tác, nguồn dữ liệu và trạng thái |

Không dùng từ khóa để chọn template cứng. Agent phải giải thích được vì sao
story, stage và clock giúp mục tiêu của người xem.

## 3. Pipeline thực tế trong source

`tools/export.mjs` mở HTML bằng Playwright, đọc metadata, chờ hàm render sẵn
sàng, rồi gọi `window.renderFrame(i/fps)` và lấy PNG từ canvas. Nó có thể phân
phối frame cho nhiều browser page. Audio score được lấy riêng thành WAV/stems;
FFmpeg encode video và mux audio. Có nhánh chỉ render lại âm thanh rồi copy
video stream vào bản mux mới, tránh dựng lại hình không thay đổi. [Exporter][export]

`kit/score-head.js` tạo score bằng JavaScript `OfflineAudioContext`; live preview
dùng Web Audio sau thao tác click. `score-tail.js` render PCM, xử lý tail và
gain/limiter, xuất WAV và stems. Vì vậy nhận định “JavaScript làm hình, Python
bắt buộc thêm nhạc” không đúng với repo này. [Score head][score], [Score tail][tail]

Python `voice_words.py` dùng faster-whisper để lấy timestamp từ audio voice.
Snapshot mặc định `small.en` và `language='en'`; nếu áp dụng cho tiếng Việt phải
chọn model/language phù hợp, kiểm tra từ bị nhận nhầm và phân biệt estimated
timing với measured timing. ASR timestamp không bảo đảm alignment chính xác
với mọi script. [Word timing][words]

Python vẫn là một lựa chọn cho phân tích, synthesis hoặc orchestration.
MoviePy có `CompositeAudioClip` để đặt/mix các clip theo thời gian; FFmpeg có
`amix`, `sidechaincompress`, `loudnorm` cho mix, ducking và kiểm soát loudness.
Không cần thêm MoviePy chỉ để gọi FFmpeg nếu Node hoặc Python subprocess đã
phù hợp với runtime. [MoviePy][moviepy], [FFmpeg filters][filters]

## 4. “Loop từng frame” nên có nghĩa gì?

Một video 15 giây ở 30 fps có 450 frame đầu ra. Agent viết scene functions,
timeline và các key state; renderer chạy vòng lặp lấy mẫu chúng. Không cần 450
lượt gọi model hay 450 hình vẽ tay độc lập. Model nên lặp ở cấp thiết kế và sửa
lỗi quan sát được.

Phân biệt bốn thứ:

| Khái niệm | Tác dụng | Đánh đổi |
| --- | --- | --- |
| Style frame/keyframe | Chốt bố cục, pose, typography, before/after | Chọn ít nhưng đại diện các tình huống khác nhau |
| Beat/action | Tổ chức hành động, nguyên nhân, hit và settle | Quá nhiều beat có thể làm người xem không theo kịp |
| Encoded frame/fps | Lấy mẫu chuyển động theo thời gian | Tăng fps tăng chi phí, không tự tăng ý tưởng hoặc độ phức tạp |
| Sub-frame sample | Lấy nhiều thời điểm cho một output frame để tạo blur | Tăng chi phí và có thể làm mờ UI/text |

Exporter upstream hỗ trợ averaging nhiều sub-frame cho style mượt; các style
stepped giữ hình có chủ ý. Đây là lựa chọn chất liệu, không có quy tắc “càng
nhiều frame càng đẹp”. EvoFlux hiện encode cố định 30 fps; không copy clock
24 fps của template upstream vào bridge hiện tại. [Exporter][export]

## 5. Style và soundtrack theo vibe

Tách một visual system nhỏ: palette, type scale, chất liệu, line weight,
camera và motion cadence. Chọn vài style frame khác nhau rồi so với reference;
đừng rải cùng hiệu ứng lên mọi subject. Ý tưởng phải được diễn ra trong hình,
không chỉ xuất hiện như nhãn. [Frame checklist][frame], [Style matching][style]

Đối với sound, lưu riêng mood, energy arc, timbre, mật độ, hit và khoảng nghỉ.
Nhạc đã có dẫn clock nếu video music-led; lời nói dẫn clock nếu voice-led.
Một reveal có thể hưởng lợi từ dip/hit; bài giảng bình tĩnh có thể không cần.
Các ngưỡng LUFS, thời lượng silence và BPM trong kit là quyết định của mẫu
video tác giả, không phải chuẩn thẩm mỹ cho mọi video. [Craft][craft]

`beats.mjs` giải mã audio qua FFmpeg, tự tính onset strength/tempo/phase, hits và
quiet windows. Nó giả định tempo tương đối đều, chọn bar theo bốn phách và có
tempo prior quanh 120 BPM; chính source yêu cầu kiểm tra grid. Không coi kết
quả detection là ground truth cho ambient, changing tempo, nhịp khác hoặc
half/double-time. Không đổi tốc độ nhạc chỉ để khớp frame grid. [Beat mapping][beats]

Giữ music/SFX/voice thành stems để sửa mix độc lập. Mọi cue dùng một timeline
giây, rồi suy ra frame index. Kiểm tra onset/rounding, fades, decay, ducking,
clipping, loudness và file sau encode; metrics không thay thế nghe thử.

## 6. Review loop: phần nên mang về, phần cần sửa

`review.mjs` tạo contact sheets, kiểm tra cut grid, story arc, vị trí anchor,
text, loudness và các đoạn hình ít thay đổi. Đây là ý tưởng tốt để cho agent
bằng chứng theo timestamp rồi patch đúng scene. Tuy nhiên nhiều kết quả FAIL
trong snapshot chỉ được in ra; không có nhánh tổng hợp chúng thành exit code
khác zero. EvoFlux cần structured findings và gate rõ nếu dùng để automation.
Dead-time heuristic cũng không phân biệt hoàn toàn hold có ý nghĩa với lỗi;
không thêm hạt/chuyển động vô nghĩa để làm đẹp số đo. [Review implementation][review]

Một khác biệt quan trọng khác: preview của upstream vẫn phát score procedural
khi export có supplied music thay thế. Cần kiểm tra bản soundtrack đã mux,
không dùng preview với nhạc khác để xác nhận audio/visual parity. [Skill][skill]

Vòng lặp đề xuất cho agent EvoFlux:

1. Đọc brief/capability/ledger; chọn story, stage, clock, medium.
2. Dựng style samples và key states từ drawing code cuối.
3. Dựng draft/sampled frames; xem toàn beat map và frame trước/sau transition.
4. Ghi findings: timestamp, expected/observed, severity, scene/beat liên quan.
5. Sửa phần nhỏ nhất; re-render vùng ảnh hưởng và hai đoạn nối; ghi revision.
6. Dừng vòng lặp không tạo cải thiện; báo rõ defect chưa giải quyết. Với defect
   correctness còn sửa được thì tiếp tục khắc phục, không dùng ngân sách mặc
   định làm lý do tuyên bố xong.
7. Encode cuối; decode/check hình và tiếng của cùng revision; mở kết quả bằng
   capability thật đang có trong EvoFlux.

## 7. Khoảng cách với EvoFlux và plan triển khai tiếp

| Lát cắt | Trạng thái ở thay đổi nghiên cứu này | Acceptance cho implementation tiếp |
| --- | --- | --- |
| Knowledge/task judgment | Bổ sung reference nạp theo nhu cầu và liên kết từ Skill | Agent nhận định workflow từ mục tiêu, lưu ledger, không model-call từng frame |
| Runtime sample/review | Hiện có frame bridge; chưa có tool trả review/contact sheet cho agent | Agent nhận frame artifacts + findings; seek lại cùng thời điểm cho cùng hình |
| Audio | Export trong app vẫn silent; chưa có audio protocol | Audio renderer/asset → bounded PCM/WAV → encode/mux; preview/export cùng mix và revision |
| External render worker | Chưa tích hợp Playwright/FFmpeg runner | Chỉ runner được cấp quyền thực thi; timeout/cancel, codec probe, bounded storage, mở output trong Workbench |
| Quality eval | Mới có skill lint/unit checks; chưa có video/live-model benchmark mới | Paired prompts/model/settings; review causal clarity, pacing, style fidelity, sync, token/time cost |

Ưu tiên thêm đường agent lấy sample frame và nhận findings trước, sau đó audio
source/mux. Mediabunny đang có sẵn trong app có audio sources nên cần so sánh
đường đó với FFmpeg trước khi thêm binary. Playwright không phải lựa chọn bắt
buộc khi bridge canvas đã cung cấp đúng frame. HyperFrames là ví dụ khác của
seek/capture/encode có kiểm tra, không phải dependency được chọn trong thay
đổi này. [Mediabunny][bunny], [HyperFrames engine][hyper]

Giữ HTML trong sandbox hiện tại; nó không được tự gọi Python/FFmpeg hoặc tải
binary. Code sinh, frames, stems và video mặc định thuộc session ngoài Git;
save-to-project vẫn là lựa chọn có chủ đích. Nếu vendor kit MIT sau này, phải
giữ notice/license. Lượt này chỉ viết kiến thức và phân tích, không vendor kit.

Đánh giá kết quả cần cả metadata lẫn hình/tiếng thực tế. Lint tài liệu hoặc một
fixture deterministic không chứng minh MiMo tự dùng đúng workflow hay video
đã đẹp hơn. Kiểm chứng các trường hợp parcel, water process, UI walkthrough,
voice tiếng Việt và music-led reel với baseline cùng điều kiện; ghi cả trường
hợp không có cải thiện.

[repo]: https://github.com/cth9191/animate/tree/7e5eb56feb2dd573f890e1b7b34748af43d58263
[skill]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/SKILL.md
[formats]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/grammar/FORMATS.md
[frame]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/grammar/FRAME.md
[style]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/new-style.md
[craft]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/craft.md
[export]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/tools/export.mjs
[review]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/tools/review.mjs
[beats]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/tools/beats.mjs
[score]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/kit/score-head.js
[tail]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/kit/score-tail.js
[words]: https://github.com/cth9191/animate/blob/7e5eb56feb2dd573f890e1b7b34748af43d58263/plugins/animate/skills/animate/tools/voice_words.py
[moviepy]: https://zulko.github.io/moviepy/user_guide/compositing.html
[filters]: https://www.ffmpeg.org/ffmpeg-filters.html
[bunny]: https://mediabunny.dev/guide/media-sources
[hyper]: https://hyperframes.heygen.com/packages/engine
