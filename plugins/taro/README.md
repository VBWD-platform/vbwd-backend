# Taro Plugin

An AI-powered Tarot reading plugin for the VBWD SaaS platform. Users can create Tarot reading sessions with 3-card spreads (Past/Present/Future), receive AI-generated interpretations, and ask follow-up questions.

**Key Features:**
- 🔮 3-card Tarot spreads with randomized card orientations
- 🤖 AI-powered card interpretations
- 💬 Follow-up question support
- 📊 Daily session limits per subscription plan
- 🔐 Token-based consumption tracking
- 🎯 Admin utilities to manage user sessions

---

## Architecture

### Layered Architecture
```
Routes (/src/routes.py)
   ↓
Services (/src/services/)
   ↓
Repositories (/src/repositories/)
   ↓
Models (/src/models/)
   ↓
Database (PostgreSQL)
```

### Core Components

**Models** (`/src/models/`)
- `Arcana` - Tarot card definition (22 major arcana, 56 minor arcana)
- `TaroSession` - User's reading session with status tracking
- `TaroCardDraw` - Individual card within a session with AI interpretation

**Services** (`/src/services/`)
- `TaroSessionService` - Business logic for creating/managing sessions
- `ArcanaInterpretationService` - LLM integration for AI interpretations

**Repositories** (`/src/repositories/`)
- Data access layer with dependency injection
- Query filtering, pagination, status management

**Routes** (`/src/routes.py`)
- User endpoints for creating sessions and follow-ups
- Admin endpoints for user session management
- Public asset serving (card SVG files)

---

## How the Plugin Works

### User Workflow

#### 1. Create a Reading Session
```
POST /api/v1/taro/session
```

**Flow:**
1. Validate JWT token (authenticated user)
2. Get user's subscription → fetch tarif plan → read `daily_taro_limit` from features
3. Check daily limit: `count_today_sessions() < daily_limit`
4. Check token balance: user has ≥ 10 tokens
5. Emit `TaroSessionRequestedEvent`
6. Create ACTIVE session with 30-minute expiry
7. Generate 3-card spread (PAST, PRESENT, FUTURE)
8. Return session with cards and interpretations

**Response:**
```json
{
  "success": true,
  "session": {
    "session_id": "uuid",
    "status": "ACTIVE",
    "expires_at": "2026-02-16T13:30:00",
    "cards": [
      {
        "position": "PAST",
        "orientation": "UPRIGHT",
        "arcana": { "name": "The Magician", "meaning": "..." }
      },
      { "position": "PRESENT", ... },
      { "position": "FUTURE", ... }
    ]
  }
}
```

#### 2. Ask Follow-Up Questions
```
POST /api/v1/taro/session/<session_id>/follow-up
```

**Flow:**
1. Validate session ownership
2. Check session not EXPIRED or CLOSED
3. Check follow-up count < `max_taro_follow_ups` (from tarif plan)
4. Check token balance: ≥ 15 tokens
5. Increment follow-up count
6. Emit `TaroFollowUpRequestedEvent`
7. Return follow-up response with AI interpretation

#### 3. Check Daily Limits
```
GET /api/v1/taro/limits
```

Returns user's daily session limits and remaining quota:
```json
{
  "success": true,
  "limits": {
    "daily_total": 3,
    "daily_remaining": 2,
    "daily_used": 1,
    "plan_name": "Star Plan",
    "can_create": true
  }
}
```

### Admin Workflow

#### View User's Sessions
```
GET /api/v1/taro/admin/users/<user_id>/sessions
```

Admin can see a specific user's Taro session info, including:
- Total daily limit (from their tarif plan)
- Currently used sessions (only counting ACTIVE sessions)
- Remaining quota available

#### Reset User's Sessions
```
POST /api/v1/taro/admin/users/<user_id>/reset-sessions
```

**Flow:**
1. Verify admin authentication
2. Find all ACTIVE sessions created today for user
3. Close them (status = CLOSED)
4. CLOSED sessions no longer count towards daily limit
5. User can now create new sessions
6. Return updated session info with new remaining quota

**Key Fix:** Only ACTIVE sessions count towards the daily limit. When reset, sessions become CLOSED and are excluded from the count.

---

## Configuring Tarif Plans

### Overview
Daily limits are **not hardcoded** in the plugin. Instead, they're configured in the **tarif plan features** JSON field.

This allows different subscription tiers to have different Taro session limits:
- **Free Plan**: 1 reading per day
- **Basic Plan**: 3 readings per day
- **Pro Plan**: 10 readings per day

### How to Configure

#### 1. Via Admin API (Coming Soon)
```
PUT /api/v1/admin/tarif-plans/<plan_id>
```

Set the features JSON:
```json
{
  "features": {
    "daily_taro_limit": 3,
    "max_taro_follow_ups": 3
  }
}
```

#### 2. Via Database
```sql
UPDATE tarif_plan
SET features = jsonb_set(features, '{daily_taro_limit}', '3')
WHERE id = 'plan-uuid';
```

#### 3. Default Values
If a tarif plan doesn't have these features configured, defaults are used:
- `daily_taro_limit` = 3
- `max_taro_follow_ups` = 3

### Configuration Flow

```
User requests /api/v1/taro/session
  ↓
get_user_tarif_plan_limits(user_id)
  ↓
Fetch Subscription where user_id and status = ACTIVE
  ↓
Get subscription.tarif_plan
  ↓
Read features["daily_taro_limit"] and features["max_taro_follow_ups"]
  ↓
Use values (or defaults if not configured)
  ↓
Enforce limits
```

### Example Tarif Plans Configuration

**Free Plan (features column):**
```json
{
  "daily_taro_limit": 1,
  "max_taro_follow_ups": 1
}
```

**Pro Plan (features column):**
```json
{
  "daily_taro_limit": 10,
  "max_taro_follow_ups": 5,
  "advanced_interpretations": true
}
```

---

## Database Models

### Arcana
Represents a Tarot card definition (immutable lookup table).

```
Column          | Type    | Description
----------------|---------|-------------------------------------------
id              | UUID    | Primary key
number          | INT     | Card number (0-21 for major, 0-55 for minor)
name            | STRING  | Card name (e.g., "The Magician")
arcana_type     | ENUM    | MAJOR_ARCANA or MINOR_ARCANA
suit            | STRING  | For minor arcana (CUPS, WANDS, SWORDS, PENTACLES)
rank            | STRING  | For minor arcana (ACE, TWO, ... KING)
upright_meaning | TEXT    | Interpretation when upright
reversed_meaning| TEXT    | Interpretation when reversed
image_url       | STRING  | Path to SVG asset
```

### TaroSession
Represents a user's reading session.

```
Column          | Type    | Description
----------------|---------|-------------------------------------------
id              | UUID    | Primary key
user_id         | UUID    | FK to User
status          | ENUM    | ACTIVE, EXPIRED, CLOSED
started_at      | DATETIME| Session creation time
expires_at      | DATETIME| Session 30-min expiry
ended_at        | DATETIME| When manually closed
spread_id       | STRING  | Spread identifier
tokens_consumed | INT     | Base 10 + LLM tokens
follow_up_count | INT     | Number of follow-ups asked
max_follow_ups  | INT     | Limit for this session
```

### TaroCardDraw
Represents a single card within a session.

```
Column          | Type    | Description
----------------|---------|-------------------------------------------
id              | UUID    | Primary key
session_id      | UUID    | FK to TaroSession
arcana_id       | UUID    | FK to Arcana
position        | STRING  | PAST, PRESENT, FUTURE
orientation     | STRING  | UPRIGHT or REVERSED
ai_interpretation|TEXT    | LLM-generated interpretation
```

---

## Subscription Plan Integration

### How Limits Are Enforced

1. **User has subscription** (status = ACTIVE):
   - Get subscription.tarif_plan
   - Read daily_taro_limit from plan.features
   - Compare: `active_sessions_today < daily_taro_limit`

2. **User has no subscription**:
   - Use default: 3 readings per day
   - Allows free trial

3. **Subscription expires**:
   - Query returns no active subscription
   - Falls back to default limits
   - User can still read, but with default limits

### Session Counting Logic

```python
def count_today_sessions(user_id: str) -> int:
    """Count ACTIVE sessions created today for user.

    Only ACTIVE sessions count towards the daily limit.
    CLOSED and EXPIRED sessions do not consume the user's quota.
    """
    sessions = get_user_sessions(user_id)
    today = date.today()

    return sum(
        1 for session in sessions
        if session.started_at.date() == today
        and session.status == "ACTIVE"
    )
```

**Key Points:**
- ✅ ACTIVE sessions → **count** towards limit
- ❌ CLOSED sessions → **don't count** (reset frees quota)
- ❌ EXPIRED sessions → **don't count** (auto-cleanup)

---

## API Endpoints

### User Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/taro/session` | Create new reading session |
| POST | `/api/v1/taro/session/<id>/follow-up` | Ask follow-up question |
| GET | `/api/v1/taro/history` | Get session history |
| GET | `/api/v1/taro/limits` | Get daily limits and usage |
| GET | `/api/v1/taro/assets/arcana/<file>` | Serve card SVG assets |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/taro/admin/users/<user_id>/sessions` | View user's session info |
| POST | `/api/v1/taro/admin/users/<user_id>/reset-sessions` | Reset user's daily quota |

### Error Responses

**402 - Daily Limit Reached:**
```json
{
  "success": false,
  "message": "Daily limit reached. You can create 3 sessions per day.",
  "remaining": 0
}
```

**402 - Insufficient Tokens:**
```json
{
  "success": false,
  "message": "Insufficient tokens. You need at least 10 tokens to create a reading."
}
```

**410 - Session Expired:**
```json
{
  "success": false,
  "message": "Session has expired"
}
```

---

## Development

### Running Tests

```bash
# Unit tests only
docker compose exec api pytest plugins/taro/tests/unit/ -v

# Test specific service
docker compose exec api pytest plugins/taro/tests/unit/services/test_taro_session_service.py -v

# Test with coverage
docker compose exec api pytest plugins/taro/tests/unit/ --cov=plugins/taro/src
```

### Key Test Cases

- ✅ Daily limit enforcement (basic and star plans)
- ✅ Session creation with 3-card spread
- ✅ Card randomization and orientation
- ✅ Session expiry detection
- ✅ Follow-up question limits
- ✅ **Reset sessions freeing quota** (critical fix)
- ✅ Token consumption tracking

### Adding New Tests

Follow TDD approach:
```python
def test_feature_name(self, taro_service, sample_arcanas, db):
    """Test description."""
    # Arrange
    user_id = str(uuid4())

    # Act
    result = taro_service.some_method(user_id)

    # Assert
    assert result.expected_field == expected_value
```

---

## Troubleshooting

### User Can't Create Sessions After Reset
**Issue:** Admin resets sessions, but user still sees "daily limit reached"

**Root Cause:** (Fixed) Counting logic was including CLOSED sessions

**Solution:** Update counting to only include ACTIVE sessions
```python
# Only count ACTIVE sessions
if session.status == TaroSessionStatus.ACTIVE.value
```

### Sessions Showing Wrong Limits
**Issue:** User sees incorrect daily_total or daily_remaining

**Root Cause:** Tarif plan features not configured

**Solution:** Configure tarif plan features JSON:
```json
{
  "daily_taro_limit": 3,
  "max_taro_follow_ups": 3
}
```

### Cards Not Loading
**Issue:** Cards show no image or "failed to load"

**Root Cause:** SVG assets path or permissions

**Solution:** Check assets exist:
```bash
ls plugins/taro/assets/arcana/
```

---

## Architecture Decisions

### SOLID Principles
- **Single Responsibility:** Services handle business logic, repositories handle data access
- **Open/Closed:** Plugin is closed for modification, open for extension via events
- **Dependency Injection:** Services receive repositories as dependencies
- **Interface Segregation:** Small, focused interfaces (get_user_sessions, check_daily_limit, etc.)

### DRY (Don't Repeat Yourself)
- `get_user_tarif_plan_limits()` is single source of truth for all limit resolution
- All 5 endpoints use the same function → consistent behavior

### Key Design Patterns
- **Repository Pattern:** Data access abstraction
- **Service Layer:** Business logic isolation
- **Event-Driven:** Emit events for session creation/follow-ups (extensible)
- **Strategy Pattern:** Different subscription plans have different limits

---

## Future Enhancements

- [ ] Custom card interpretations per plan tier
- [ ] Spread variations (Celtic Cross, 5-card, etc.)
- [ ] Card combination analysis ("card pairs" meanings)
- [ ] Reading history export (PDF, JSON)
- [ ] Admin reading statistics dashboard
- [ ] Bulk user quota reset API
- [ ] GraphQL API for readings
- [ ] Webhook support for reading events

---

## License

This plugin is part of VBWD SDK. See main LICENSE for details.

---

## Related

| | Repository |
|-|------------|
| 👤 Frontend (user) | [vbwd-fe-user-plugin-taro](https://github.com/VBWD-platform/vbwd-fe-user-plugin-taro) |
| 🛠 Frontend (admin) | [vbwd-fe-admin-plugin-taro](https://github.com/VBWD-platform/vbwd-fe-admin-plugin-taro) |

**Core:** [vbwd-backend](https://github.com/VBWD-platform/vbwd-backend)
