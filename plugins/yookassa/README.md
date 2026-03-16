# YooKassa Plugin (Backend)

YooKassa (formerly Yandex.Kassa) payment provider integration for RU/CIS markets.

## Purpose

Implements the `IPaymentSdkAdapter` interface for YooKassa. Provides payment creation, webhook handling, and refund processing for Russian-market customers.

## Configuration (`plugins/config.json`)

```json
{
  "yookassa": {
    "shop_id": "...",
    "secret_key": "...",
    "return_url": "https://yourdomain.com/payment/success"
  }
}
```

## API Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/yookassa/create-payment` | Bearer | Create YooKassa payment |
| POST | `/api/v1/yookassa/webhook` | YooKassa IP | Receive payment notifications |

## Events

Emits: `PaymentCapturedEvent` on successful payment notification.

## Database

No plugin-owned tables.

## Frontend Bundle

- Admin: none (uses core invoicing UI)
- User: `vbwd-fe-user/plugins/yookassa/` (if present)

## Testing

```bash
docker compose run --rm test python -m pytest plugins/yookassa/tests/ -v
```

---

## Related

| | Repository |
|-|------------|
| 👤 Frontend (user) | [vbwd-fe-user-plugin-yookassa-payment](https://github.com/VBWD-platform/vbwd-fe-user-plugin-yookassa-payment) |

**Core:** [vbwd-backend](https://github.com/VBWD-platform/vbwd-backend)
