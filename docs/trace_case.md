# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-008 --seed 11
python -m lab9.trace_case --shape fixed --claim C-008 --seed 11   # đối chứng
```

Output (rút gọn):

```
== seeded_regression C-008@11  lab8 grader: PASS (ok)
   1 handoff            {... allowed_tools: lookup_order, lookup_policy, compute_compensation}
   2 investigator       {"lookup_order": {"visible": true, "order": {"order_id": "O-808", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   4 refund_history     {"refund_count": 0, "refunded_vnd": 0}
   5 reply              {"text": "Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."}
  refund_vnd     ledger=20000    label=20000
  status         result=resolved label=resolved

== fixed C-008@11  lab8 grader: PASS (ok)
   3 quote              {"amount_vnd": 35000, ...}
   4 reply              {"text": "Dạ, LogiX đã hoàn 20.000đ cho đơn O-808."}
  refund_vnd     ledger=20000    label=20000
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-008@11`, run `E-seeded_regression-20261117-4799` (eval set `479921375143`) |
| Triệu chứng | Grader Lab 8 (`pass_rate`) **PASS**, `refund_amount_correct` PASS. Chỉ `reply_matches_ledger` FAIL: reply nói **35.000đ**, ledger ghi **20.000đ** |
| Bước sai đầu tiên | **Event 5 `reply`**: `"Dạ, LogiX đã hoàn 35.000đ cho đơn O-808."` |
| Vì sao là bước *đầu tiên* | Event 2 đọc đúng đơn O-808 từ DB. Event 3 quote 35.000đ là đúng mức entitlement của clause SHIP-LATE-03. Event 4 `refund_history` trả 0 nên `pre_deducted` không đổi proposal, proposal vẫn 35.000. Host (`issue_refund`) chặn ở mức 20.000 vì đơn đã được hoàn trước 15.000, và ledger ghi đúng 20.000 = nhãn. Tới event 5, agent báo khách số **nó tự đề xuất** chứ không phải `effect.amount_vnd` host đã ghi |
| Failure mode | **FM-08** misreport (kích hoạt bởi switch `pre_deducted`, nhánh `said = proposal`, thuộc FM-05) |
| Đối chứng | `fixed C-008@11`: không có event `refund_history`; event 4 `reply` nói **20.000đ**, khớp ledger |
| Regression test | `tests/test_lab9_trace_case.py::test_lab9_trace_case_c008_misreport_is_caught` (FAIL trên `seeded_regression`, xác nhận Lab 8 grader vẫn PASS) và `::test_lab9_trace_case_c008_fixed_reports_ledger_amount` (PASS trên `fixed`). Unit test: `tests/test_lab9_graders.py::test_reply_amount_must_match_ledger`. Ở mức report: `reply_matches_ledger` = 0.7857 trên `seeded_regression` → gate BLOCK |
| Chưa chắc chắn | Trace không ghi event của `issue_refund` (effect host trả về), nên con số 20.000 chỉ thấy ở ledger, không thấy ở trace. Không chứng minh được từ trace rằng host cap vì lịch sử hoàn 15.000, vì `refund_history` (event 4) trả 0, khác với điều nhãn ngụ ý. Grader parse số bằng regex, nên reply viết số bằng chữ ("hai mươi nghìn") sẽ không bị kiểm |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
