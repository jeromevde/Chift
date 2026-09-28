# hyperline · 2026-09-29T1309

**ACCEPTED**

deepseek/deepseek-v4-pro · 31 model calls · $0.61 · 19.0 min
Stopped: agent finished

| Suite | Result | Exit code | Evidence |
|---|---|---|---|
| Chift acceptance | 37 passed, 14 skipped in 11.88s | 0 | [Full output](logs/tests-20260929T132757262846.json) |

## Failures and limitations

- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact phone: Not supported by this provider: contact phone: Hyperline customers have no phone number
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact mobile: Not supported by this provider: contact mobile: Hyperline customers have no mobile number
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact comment: Not supported by this provider: contact comment: Hyperline customers have no comment field
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact birthdate: Not supported by this provider: contact birthdate: Hyperline customers have no birthdate field
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact gender: Not supported by this provider: contact gender: Hyperline customers have no gender field
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact customer_account_number: Not supported by this provider: contact customer_account_number: Hyperline has no customer account number
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact supplier_account_number: Not supported by this provider: contact supplier_account_number: Hyperline has no supplier account number
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact is_supplier: Not supported by this provider: contact is_supplier: Hyperline has no supplier concept
- SKIPPED [1] tests/conftest.py:102: declined by the connector: contact is_prospect: Not supported by this provider: contact is_prospect: Hyperline has no prospect concept
- SKIPPED [1] tests/conftest.py:102: declined by the connector: address number: Not supported by this provider: address number: Hyperline addresses have no number field (use street)
- SKIPPED [1] tests/conftest.py:102: declined by the connector: address box: Not supported by this provider: address box: Hyperline addresses have no box field
- SKIPPED [1] tests/conftest.py:102: declined by the connector: address phone: Not supported by this provider: address phone: Hyperline addresses have no phone field
- SKIPPED [1] tests/conftest.py:102: declined by the connector: address address_type: Not supported by this provider: address other: Hyperline supports only billing and shipping addresses
- SKIPPED [1] tests/conftest.py:102: declined by the connector: supplier invoices: Not supported by this provider: invoice type supplier_invoice: Hyperline has no supplier invoices

Acceptance is decided by Chift's suite; a skip leaves a capability unverified. Round trips cannot see a mistake made the same way on write and read: review the mapping decisions.

[Connector, mapping decisions and UNMAPPED](connector.py) · [Run trace and agent account (unverified)](logs/trace.html)
