# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend REPLAY, verdict lưu sẵn trong CSV). FAIL là lớp dương.

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Có** | dùng (chỉ cho tone, không cho tiền) |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không** (κ, R dưới sàn) | loại |

Ma trận nhầm lẫn:
- tone_ok: tp 24 · fp 4 · fn 6 · tn 66. Tỉ lệ FAIL quan sát 0.28, sau Rogan-Gladen là **0.30**.
- helpful: tp 9 · fp 0 · fn 21 · tn 70. Tỉ lệ FAIL quan sát 0.09, sau Rogan-Gladen là **0.30**. Judge thấy chưa tới 1/3 số lỗi thật.

## ≥5 case audit thủ công (tone_ok, 10 bất đồng)
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | H-008 "Em đã hoàn tiền cho anh rồi nha…" | PASS | FAIL | Người | Rubric thêm: xưng "em/anh" + "nha" là suồng sã với khách → FAIL |
| 2 | H-017 "Dạ, bạn ơi LogiX đã hoàn…" | PASS | FAIL | Người | Xưng hô chuẩn là "anh/chị"; "bạn" → FAIL |
| 3 | H-029 "…không cần nhắn thêm." | PASS | FAIL | Người | Judge bị đánh lừa bởi "Dạ, vui lòng". Rubric: câu mệnh lệnh/ngăn khách liên hệ → FAIL dù có kính ngữ |
| 4 | H-042 "Dạ, đơn O-808 đã hoàn 120.000đ…" | FAIL | PASS | Người | Rubric ghi rõ: **không** bắt buộc xin lỗi; ngắn mà đủ ý vẫn PASS |
| 5 | H-051 "LogiX đã refund 90.000đ…" | FAIL | PASS | Người | Thêm whitelist thuật ngữ CS cho phép ("refund") |
| 6 | H-063 "…và sẽ hoàn thêm cho anh/chị ạ" | PASS | FAIL | Người | Hứa ngoài kết quả hệ thống không phải lỗi tone mà là lỗi nội dung → chấm bằng code (FM-08 mở rộng), không giao cho judge tone |
| 7 | H-070 "…ạ 😂😂" | PASS | FAIL | Người | Rubric: emoji trong ngữ cảnh khiếu nại → FAIL |
| 8 | H-081 "đơn O-107 chưa đủ điều kiện…" | FAIL | PASS | **Judge** | Nhãn người sai (đọc nhầm ticket) → sửa nhãn, ghi vào changelog bộ nhãn |
| 9 | H-088 "Dạ, dạ, LogiX đã hoàn…" | FAIL | PASS | Người (chấp nhận được) | Lỗi gõ lặp từ: rubric coi là lỗi nhỏ, không FAIL |
| 10 | H-094 "Da, LogiX da hoan…" (mất dấu) | PASS | FAIL | Người | Rubric: tiếng Việt không dấu → FAIL |

## Audit helpful (vì sao loại)
21 bất đồng, **tất cả** đều là judge PASS còn người FAIL:
- **18/21 là "sai tiền"** (HL-015: reply 55.000đ, ledger 40.000đ; HL-020: 90.000đ vs 120.000đ; …). Nhiều reply là lời xin lỗi dài, trôi chảy, nên judge chấm "hữu ích".
- 3/21 sai xưng hô ("Ok bạn, … xử lý rồi nhé"): HL-047, HL-091, HL-097.

Judge không đọc ledger nên không thể biết reply nói sai tiền. Đây chính là FM-08, và nó đã được chấm bằng code qua `reply_matches_ledger`.

## Kết luận
- **helpful bị loại**: κ=0.375 < 0.6, R=0.30 < 0.7 (fn=21/30). P=1.0 không cứu được, vì một judge gần như luôn PASS thì có P cao nhưng bỏ sót 70% lỗi. Dùng nó làm gate thì regression về tiền sẽ lọt qua.
- **tone_ok được dùng** nhưng không blocking cho tiền/approval. Các bất đồng 1–3, 7, 10 cho thấy judge dễ dãi với giọng suồng sã/ra lệnh, nên rubric v2 thêm các luật ở bảng trên.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai. Cần nhãn người mới để có held-out thật, và cần chạy lại calibration mỗi khi đổi model hoặc prompt của judge.
