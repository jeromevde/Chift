# Chift invoicing acceptance suite

The same scenarios for every provider. The suite speaks only Chift's HTTP API, validates every
response against [`chift/openapi.yaml`](../chift/openapi.yaml), and knows nothing about any
provider: it creates its own contacts and invoices through Chift, then checks that Chift reads
back what it was sent.

```bash
CHIFT_PROVIDER=hyperline pytest tests
```

| File | Checks |
|---|---|
| `test_contacts.py` | Company and person round trips (a person is never a company name); every optional field, alone and then all accepted ones together, reads back or is declined; created contact is listed, identically; Chift's 404 and 422 |
| `test_invoices.py` | Two-line EUR round trip to the cent; every optional field, alone and then together; line discount, JPY, posted and supplier invoices round-trip or are declined with Chift's 400; existing invoices are valid and add up; unknown partner is refused, not crashed; 404 and 422 |
| `test_code_rules.py` | The connector never fills a missing value with a default (`.get(key, default)`, `x or ""`), read from its source |
| `test_fields.py` | Every Chift field is returned or declared in the connector's `UNMAPPED` with a reason |
| `test_pagination.py` | Pages are disjoint and agree on the total; a page past the end is empty |

- **Needs** a sandbox key that allows writes. Records stay in the sandbox: Chift has no DELETE.
- **Declined capabilities show as skips**, so a coverage gap is visible, never a silent pass.
- **Cannot prove** a mistake made the same way on write and read, or the mapping of states Chift
  cannot create (paid, cancelled, credit notes). Review of the mapping decisions covers those;
  an adversarial, provider-tailored suite would be the next step.

Do not edit these tests to make a connector pass. If a test is wrong, say why.
