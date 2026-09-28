# hyperline · 2026-09-29T1112

**ACCEPTED**

deepseek/deepseek-v4-pro · 17 model calls · $0.29 · 9.2 min
Stopped: agent finished

| Suite | Result | Exit code | Evidence |
|---|---|---|---|
| Chift acceptance | 29 passed, 1 skipped in 8.76s | 0 | [Full output](logs/tests-20260929T112155116343.json) |

## Failures and limitations

- SKIPPED [1] tests/conftest.py:102: declined by the connector: supplier invoices: Not supported by this provider: Hyperline does not support invoice type 'supplier_invoice'; only customer_invoice and customer_refund are supported

Acceptance is decided by Chift's suite; a skip leaves a capability unverified. Round trips cannot see a mistake made the same way on write and read: review the mapping decisions.

[Connector, mapping decisions and UNMAPPED](connector.py) · [Run trace and agent account (unverified)](logs/trace.html)
