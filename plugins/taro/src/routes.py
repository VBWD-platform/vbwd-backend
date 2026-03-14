"""Routes for Taro plugin - API endpoints."""
from flask import Blueprint, request, jsonify, current_app, send_from_directory, g
from src.utils.datetime_utils import utcnow
from pathlib import Path
from uuid import UUID
from src.extensions import db
from src.middleware.auth import require_auth, require_admin

from plugins.taro.src.events import (
    TaroSessionRequestedEvent,
    TaroFollowUpRequestedEvent,
)
from plugins.taro.src.services.taro_session_service import TaroSessionService
from plugins.taro.src.repositories.taro_session_repository import TaroSessionRepository
from plugins.taro.src.repositories.arcana_repository import ArcanaRepository
from plugins.taro.src.repositories.taro_card_draw_repository import TaroCardDrawRepository
from plugins.taro.src.services.prompt_service import PromptService


taro_bp = Blueprint("taro", __name__, url_prefix="/api/v1/taro")


# Language code to full language name mapping for LLM prompts
LANGUAGE_NAMES = {
    'en': 'English',
    'de': 'Deutsch (German)',
    'es': 'Español (Spanish)',
    'fr': 'Français (French)',
    'ja': '日本語 (Japanese)',
    'ru': 'Русский (Russian)',
    'th': 'ไทย (Thai)',
    'zh': '中文 (Chinese)',
}


def get_language_name(language_code: str) -> str:
    """Convert language code to full language name for LLM prompts.

    Args:
        language_code: Language code (en, de, es, etc.)

    Returns:
        Full language name, defaults to English if code not found
    """
    return LANGUAGE_NAMES.get(language_code.lower(), 'English')


def _get_taro_services():
    """Get Taro service instances with LLM adapter from plugin config."""
    arcana_repo = ArcanaRepository(db.session)
    session_repo = TaroSessionRepository(db.session)
    card_draw_repo = TaroCardDrawRepository(db.session)

    # TaroSessionService initializes LLM adapter from plugin config
    session_service = TaroSessionService(
        arcana_repo=arcana_repo,
        session_repo=session_repo,
        card_draw_repo=card_draw_repo,
    )

    return session_service


def _get_prompt_service() -> PromptService:
    """Get PromptService instance for managing LLM prompts.

    Returns:
        PromptService instance initialized with plugin prompts file

    Raises:
        FileNotFoundError: If prompts file doesn't exist
    """
    import os

    # Get plugins directory (plugin-agnostic location)
    plugin_base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    prompts_file = os.path.join(plugin_base_dir, "taro-prompts.json")

    return PromptService(prompts_file)


def get_user_tarif_plan_limits(user_id: str) -> tuple:
    """Get user's daily Taro limits from their tarif plan.

    Reads the tarif plan features configuration to determine:
    - daily_taro_limit: Max taro sessions per day
    - max_follow_ups: Max follow-up questions per session

    Args:
        user_id: User ID to fetch limits for

    Returns:
        Tuple of (daily_limit: int, max_follow_ups: int)
        Returns defaults (3, 3) if user has no active subscription
    """
    from src.models.user import User
    from src.models.subscription import Subscription
    from src.models.enums import SubscriptionStatus

    # Default limits
    DEFAULT_DAILY_LIMIT = 3
    DEFAULT_MAX_FOLLOW_UPS = 3

    try:
        # Get user and their active subscription
        user = User.query.get(user_id)
        if not user:
            return DEFAULT_DAILY_LIMIT, DEFAULT_MAX_FOLLOW_UPS

        # Get user's active subscription (ACTIVE or TRIALING both grant plan features)
        subscription = Subscription.query.filter(
            Subscription.user_id == user_id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]),
        ).first()

        if not subscription or not subscription.tarif_plan:
            return DEFAULT_DAILY_LIMIT, DEFAULT_MAX_FOLLOW_UPS

        # Read limits from tarif plan features
        features = subscription.tarif_plan.features or {}
        daily_limit = features.get("daily_taro_limit", DEFAULT_DAILY_LIMIT)
        max_follow_ups = features.get("max_taro_follow_ups", DEFAULT_MAX_FOLLOW_UPS)

        return int(daily_limit), int(max_follow_ups)

    except Exception as e:
        print(f"Error fetching tarif plan limits: {e}")
        return DEFAULT_DAILY_LIMIT, DEFAULT_MAX_FOLLOW_UPS


def check_token_balance(user_id: str, tokens_required: int = 10) -> bool:
    """Check if user has sufficient tokens.

    Args:
        user_id: User ID to check
        tokens_required: Number of tokens needed

    Returns:
        True if user has sufficient tokens, False otherwise
    """
    from src.services.token_service import TokenService
    from src.repositories.token_repository import (
        TokenBalanceRepository,
        TokenTransactionRepository,
    )
    from src.repositories.token_bundle_purchase_repository import TokenBundlePurchaseRepository

    balance_repo = TokenBalanceRepository(db.session)
    transaction_repo = TokenTransactionRepository(db.session)
    purchase_repo = TokenBundlePurchaseRepository(db.session)

    token_service = TokenService(balance_repo, transaction_repo, purchase_repo)
    user_balance = token_service.get_balance(user_id)
    return user_balance >= tokens_required


@taro_bp.route("/session", methods=["POST"])
@require_auth
def create_session():
    """Create a new Taro reading session.

    Returns:
        JSON response with session_id and initial 3-card spread
    """
    try:
        user_id = g.user_id
        session_service = _get_taro_services()

        # Get daily limit and max follow-ups from user's tarif plan
        daily_limit, max_follow_ups = get_user_tarif_plan_limits(user_id)

        # Check daily limit
        allowed, remaining = session_service.check_daily_limit(user_id, daily_limit)
        if not allowed:
            return (
                jsonify({
                    "success": False,
                    "message": f"Daily limit reached. You can create {daily_limit} sessions per day.",
                    "remaining": remaining,
                }),
                402,
            )

        # Check token balance (10 tokens base cost)
        if not check_token_balance(user_id, tokens_required=10):
            return (
                jsonify({
                    "success": False,
                    "message": "Insufficient tokens. You need at least 10 tokens to create a reading.",
                }),
                402,
            )

        # Emit event for session creation
        event = TaroSessionRequestedEvent(
            user_id=user_id,
            requested_at=utcnow(),
            daily_limit=daily_limit,
            max_follow_ups=max_follow_ups,
        )
        current_app.container.event_dispatcher().emit(event)

        # Create session and get response (service handles event processing)
        session = session_service.create_session(
            user_id=user_id,
            daily_limit=daily_limit,
            max_follow_ups=max_follow_ups,
        )

        if not session:
            return (
                jsonify({
                    "success": False,
                    "message": "Failed to create session",
                }),
                500,
            )

        # Get spread cards
        cards = session_service.get_session_spread(session.id)

        return (
            jsonify({
                "success": True,
                "message": "Taro session created successfully",
                "session": {
                    "session_id": str(session.id),
                    "user_id": str(session.user_id),
                    "spread_id": str(session.spread_id),
                    "status": session.status,
                    "created_at": session.created_at.isoformat() if session.created_at else None,
                    "expires_at": session.expires_at.isoformat() if session.expires_at else None,
                    "follow_up_count": session.follow_up_count,
                    "max_follow_ups": max_follow_ups,
                    "cards": [
                        {
                            "card_id": str(card.id),
                            "position": card.position,
                            "orientation": card.orientation,
                            "arcana_id": str(card.arcana_id),
                            "interpretation": card.ai_interpretation,
                            # Include Arcana details for display
                            "arcana": {
                                "id": str(card.arcana.id),
                                "name": card.arcana.name,
                                "number": card.arcana.number,
                                "suit": card.arcana.suit,
                                "rank": card.arcana.rank,
                                "arcana_type": card.arcana.arcana_type,
                                "image_url": card.arcana.image_url,
                                "upright_meaning": card.arcana.upright_meaning,
                                "reversed_meaning": card.arcana.reversed_meaning,
                            } if card.arcana else None,
                        }
                        for card in cards
                    ],
                    "tokens_consumed": session.tokens_consumed,
                },
            }),
            201,
        )

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "message": f"Error creating session: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/session/<session_id>/follow-up", methods=["POST"])
@require_auth
def create_follow_up(session_id: str):
    """Create a follow-up question for an active session.

    Args:
        session_id: ID of the session to add follow-up to

    Returns:
        JSON response with follow-up interpretation
    """
    try:
        user_id = g.user_id
        data = request.get_json() or {}

        question = data.get("question", "")
        follow_up_type = data.get("follow_up_type", "SAME_CARDS")

        # Validate follow_up_type
        valid_types = {"SAME_CARDS", "ADDITIONAL", "NEW_SPREAD"}
        if follow_up_type not in valid_types:
            return (
                jsonify({
                    "success": False,
                    "message": f"Invalid follow_up_type. Must be one of {valid_types}",
                }),
                400,
            )

        # Validate question
        if not question or not question.strip():
            return (
                jsonify({
                    "success": False,
                    "message": "Question is required",
                }),
                400,
            )

        session_service = _get_taro_services()

        # Get session
        session = session_service.get_session(session_id)
        if not session:
            return (
                jsonify({
                    "success": False,
                    "message": "Session not found",
                }),
                404,
            )

        # Verify user owns session
        if str(session.user_id) != str(user_id):
            return (
                jsonify({
                    "success": False,
                    "message": "Unauthorized",
                }),
                403,
            )

        # Check if session is expired
        if session.status == "EXPIRED":
            return (
                jsonify({
                    "success": False,
                    "message": "Session has expired",
                }),
                410,
            )

        # Check if session is closed
        if session.status == "CLOSED":
            return (
                jsonify({
                    "success": False,
                    "message": "Session is closed",
                }),
                410,
            )

        # Get max follow-ups from user's plan
        _, max_follow_ups = get_user_tarif_plan_limits(user_id)

        # Check follow-up count limit
        if session.follow_up_count >= max_follow_ups:
            return (
                jsonify({
                    "success": False,
                    "message": f"Maximum follow-ups ({max_follow_ups}) reached for this session",
                }),
                402,
            )

        # Check token balance for follow-up (5 base + LLM tokens)
        if not check_token_balance(user_id, tokens_required=15):
            return (
                jsonify({
                    "success": False,
                    "message": "Insufficient tokens. You need at least 15 tokens for a follow-up",
                }),
                402,
            )

        # Emit follow-up event
        event = TaroFollowUpRequestedEvent(
            session_id=session_id,
            user_id=user_id,
            question=question,
            follow_up_type=follow_up_type,
            requested_at=utcnow(),
        )
        current_app.container.event_dispatcher().emit(event)

        # Return success response
        return (
            jsonify({
                "success": True,
                "message": "Follow-up question submitted successfully",
                "follow_up": {
                    "session_id": session_id,
                    "question": question,
                    "follow_up_type": follow_up_type,
                    "follow_up_count": session.follow_up_count + 1,
                    "requested_at": utcnow().isoformat(),
                },
            }),
            201,
        )

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "message": f"Error creating follow-up: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/session/<session_id>/follow-up-question", methods=["POST"])
@require_auth
def ask_follow_up_question(session_id: str):
    """Ask a follow-up question about the Tarot reading.

    Args:
        session_id: ID of the session

    Request body:
        {
            "question": "User's follow-up question",
            "language": "en" (optional, defaults to "en")
        }

    Returns:
        JSON response with Oracle's answer
    """
    try:
        user_id = g.user_id
        data = request.get_json() or {}

        question = data.get("question", "").strip()
        language = data.get("language", "en").lower()

        # Validate question
        if not question:
            return (
                jsonify({
                    "success": False,
                    "error": "Question is required",
                }),
                400,
            )

        session_service = _get_taro_services()

        # Get session
        session = session_service.get_session(session_id)
        if not session:
            return (
                jsonify({
                    "success": False,
                    "error": "Session not found",
                }),
                404,
            )

        # Verify user owns session
        if str(session.user_id) != str(user_id):
            return (
                jsonify({
                    "success": False,
                    "error": "Unauthorized",
                }),
                403,
            )

        # Check if session is expired or closed
        if session.status in ["EXPIRED", "CLOSED"]:
            return (
                jsonify({
                    "success": False,
                    "error": f"Session is {session.status.lower()}",
                }),
                410,
            )

        # Generate answer for follow-up question
        answer = session_service.answer_oracle_question(
            session_id=session_id,
            question=question,
            language=language,
        )

        return (
            jsonify({
                "success": True,
                "answer": answer,
            }),
            200,
        )

    except ValueError as e:
        return (
            jsonify({
                "success": False,
                "error": str(e),
            }),
            400,
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": f"Error processing question: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/session/<session_id>/card-explanation", methods=["POST"])
@require_auth
def get_card_explanation(session_id: str):
    """Get detailed explanation of the 3 cards in the spread.

    Args:
        session_id: ID of the session with the 3-card spread

    Request body:
        {
            "language": "en" (optional, defaults to "en")
        }

    Returns:
        JSON response with detailed card explanation
    """
    try:
        user_id = g.user_id
        data = request.get_json() or {}
        language = data.get("language", "en").lower()
        session_service = _get_taro_services()

        # Get session
        session = session_service.get_session(session_id)
        if not session:
            return (
                jsonify({
                    "success": False,
                    "error": "Session not found",
                }),
                404,
            )

        # Verify user owns session
        if str(session.user_id) != str(user_id):
            return (
                jsonify({
                    "success": False,
                    "error": "Unauthorized",
                }),
                403,
            )

        # Check if session is expired or closed
        if session.status == "EXPIRED":
            return (
                jsonify({
                    "success": False,
                    "error": "Session has expired",
                }),
                410,
            )

        if session.status == "CLOSED":
            return (
                jsonify({
                    "success": False,
                    "error": "Session is closed",
                }),
                410,
            )

        # Generate card explanation using prompt service
        cards = session_service.get_session_spread(session_id)
        if len(cards) != 3:
            return (
                jsonify({
                    "success": False,
                    "error": f"Session must have exactly 3 cards, found {len(cards)}",
                }),
                400,
            )

        # Build cards context
        cards_context = session_service._build_cards_context(cards)

        # Get explanation from LLM (required)
        if not session_service.llm_adapter or not session_service.prompt_service:
            return (
                jsonify({
                    "success": False,
                    "error": "LLM service unavailable. Please try again later.",
                }),
                503,
            )

        try:
            prompt = session_service.prompt_service.render('card_explanation', {
                'cards_context': cards_context,
                'language': get_language_name(language)
            })

            response = session_service.llm_adapter.chat(
                messages=[{"role": "user", "content": prompt}]
            )

            if not response:
                return (
                    jsonify({
                        "success": False,
                        "error": "Failed to generate explanation. Please try again.",
                    }),
                    500,
                )

            interpretation = response.strip()
            # Deduct tokens for LLM operation
            session_service.deduct_tokens(session_id, session_service.CARD_EXPLANATION_TOKENS)

            return (
                jsonify({
                    "success": True,
                    "interpretation": interpretation,
                }),
                200,
            )

        except Exception as e:
            logger.error(f"Error generating explanation: {e}")
            return (
                jsonify({
                    "success": False,
                    "error": "Failed to generate explanation. Please try again.",
                }),
                500,
            )

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": f"Error getting explanation: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/session/<session_id>/situation", methods=["POST"])
@require_auth
def submit_situation(session_id: str):
    """Submit user's situation and get contextual Oracle reading.

    Args:
        session_id: ID of the session with the 3-card spread

    Request body:
        {
            "situation_text": "User's situation description (max 100 words)",
            "language": "en" (optional, defaults to "en")
        }

    Returns:
        JSON response with Oracle interpretation
    """
    try:
        user_id = g.user_id
        data = request.get_json() or {}

        situation_text = data.get("situation_text", "").strip()
        language = data.get("language", "en").lower()

        # Validate situation_text
        if not situation_text:
            return (
                jsonify({
                    "success": False,
                    "error": "Situation text is required",
                }),
                400,
            )

        # Check word count (frontend does this too, but validate server-side)
        word_count = len(situation_text.split())
        if word_count > 100:
            return (
                jsonify({
                    "success": False,
                    "error": f"Situation text must be ≤ 100 words (got {word_count})",
                }),
                400,
            )

        session_service = _get_taro_services()

        # Get session
        session = session_service.get_session(session_id)
        if not session:
            return (
                jsonify({
                    "success": False,
                    "error": "Session not found",
                }),
                404,
            )

        # Verify user owns session
        if str(session.user_id) != str(user_id):
            return (
                jsonify({
                    "success": False,
                    "error": "Unauthorized",
                }),
                403,
            )

        # Check if session is expired or closed
        if session.status in ["EXPIRED", "CLOSED"]:
            return (
                jsonify({
                    "success": False,
                    "error": f"Session is {session.status.lower()}",
                }),
                410,
            )

        # Generate situation-based reading
        interpretation = session_service.generate_situation_reading(
            session_id=session_id,
            situation_text=situation_text,
            language=language,
        )

        return (
            jsonify({
                "success": True,
                "interpretation": interpretation,
            }),
            200,
        )

    except ValueError as e:
        return (
            jsonify({
                "success": False,
                "error": str(e),
            }),
            400,
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": f"Error processing situation: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/history", methods=["GET"])
@require_auth
def get_session_history():
    """Get user's Taro session history.

    Query parameters:
        limit: Number of sessions to return (default 10)
        offset: Offset for pagination (default 0)
        status: Filter by status (ACTIVE, EXPIRED, CLOSED)

    Returns:
        JSON response with list of sessions
    """
    try:
        user_id = g.user_id

        # Get pagination parameters
        limit = request.args.get("limit", 10, type=int)
        offset = request.args.get("offset", 0, type=int)
        status_filter = request.args.get("status", None)

        # Validate pagination
        limit = min(limit, 100)  # Max 100 items per request
        limit = max(limit, 1)

        session_service = _get_taro_services()

        # Get sessions
        sessions = session_service.get_user_sessions(
            user_id=user_id,
            limit=limit,
            offset=offset,
        )

        # Filter by status if provided
        if status_filter:
            sessions = [s for s in sessions if s.status == status_filter]

        # Format response
        sessions_data = []
        for session in sessions:
            cards = session_service.get_session_spread(session.id)

            sessions_data.append({
                "session_id": str(session.id),
                "user_id": str(session.user_id),
                "status": session.status,
                "created_at": session.created_at.isoformat() if session.created_at else None,
                "expires_at": session.expires_at.isoformat() if session.expires_at else None,
                "tokens_consumed": session.tokens_consumed,
                "follow_up_count": session.follow_up_count,
                "cards": [
                    {
                        "card_id": str(card.id),
                        "position": card.position,
                        "orientation": card.orientation,
                        "arcana_id": str(card.arcana_id),
                        "interpretation": card.ai_interpretation,
                    }
                    for card in cards
                ],
            })

        return (
            jsonify({
                "success": True,
                "message": "Session history retrieved successfully",
                "sessions": sessions_data,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": session_service.count_user_sessions(user_id),
                },
            }),
            200,
        )

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "message": f"Error retrieving history: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/limits", methods=["GET"])
@require_auth
def get_daily_limits():
    """Get user's daily Taro limits and current usage.

    Returns:
        JSON response with daily limits and remaining sessions
    """
    try:
        user_id = g.user_id

        # Get daily limit from user's tarif plan
        daily_limit, _ = get_user_tarif_plan_limits(user_id)

        # Get plan name from subscription
        from src.models.subscription import Subscription
        from src.models.enums import SubscriptionStatus

        plan_name = "Unknown"
        subscription = Subscription.query.filter(
            Subscription.user_id == user_id,
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING]),
        ).first()
        if subscription and subscription.tarif_plan:
            plan_name = subscription.tarif_plan.name

        session_service = _get_taro_services()

        # Check daily limit
        allowed, remaining = session_service.check_daily_limit(user_id, daily_limit)

        # Get active session if exists
        active_session = session_service.get_active_session(user_id)
        session_expiry_warning = None

        if active_session:
            has_warning = session_service.has_expiry_warning(active_session)
            if has_warning:
                time_remaining = (active_session.expires_at - utcnow()).total_seconds()
                session_expiry_warning = {
                    "has_warning": True,
                    "session_id": str(active_session.id),
                    "expires_at": active_session.expires_at.isoformat() if active_session.expires_at else None,
                    "seconds_remaining": int(time_remaining),
                }

        response_data = {
            "success": True,
            "message": "Limits retrieved successfully",
            "limits": {
                "daily_total": daily_limit,
                "daily_remaining": remaining,
                "daily_used": daily_limit - remaining,
                "plan_name": plan_name,
                "can_create": allowed,
            },
        }

        if session_expiry_warning:
            response_data["session_expiry_warning"] = session_expiry_warning

        return jsonify(response_data), 200

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "message": f"Error retrieving limits: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/assets/arcana/<path:filename>", methods=["GET"])
def serve_arcana_assets(filename):
    """Serve tarot card SVG assets from the plugin directory."""
    try:
        # Security: only allow safe file paths (alphanumeric, hyphens, slashes, dots)
        if not all(c.isalnum() or c in '-_/.svg' for c in filename):
            return jsonify({"error": "Invalid file path"}), 400

        # Get plugin directory path
        plugin_dir = Path(__file__).parent.parent
        assets_dir = plugin_dir / "assets" / "arcana"

        # Resolve the full path safely (prevent directory traversal)
        file_path = (assets_dir / filename).resolve()
        if not str(file_path).startswith(str(assets_dir.resolve())):
            return jsonify({"error": "Access denied"}), 403

        if not file_path.exists():
            return jsonify({"error": "File not found"}), 404

        # Serve the file
        return send_from_directory(str(assets_dir), filename, mimetype="image/svg+xml")

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# ADMIN ENDPOINTS - Taro Admin Utilities
# ============================================================================


@taro_bp.route("/admin/users/<user_id>/sessions", methods=["GET"])
@require_auth
@require_admin
def admin_get_user_sessions(user_id):
    """Get user's Taro session info (admin utility).

    Returns current session count and limits for the specified user.
    Used by admins to view user's taro session status.

    Args:
        user_id: UUID of the user

    Returns:
        JSON response with session info
        403: Unauthorized (requires admin)
        404: User not found
    """
    try:
        # Validate user_id format
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            return jsonify({"error": "Invalid user ID format"}), 400

        # Verify user exists
        from src.models.user import User
        user = User.query.get(user_uuid)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Get taro service
        session_service = _get_taro_services()

        # Get session info from user's tarif plan
        daily_limit, _ = get_user_tarif_plan_limits(str(user_id))
        allowed, remaining = session_service.check_daily_limit(str(user_id), daily_limit)

        return (
            jsonify({
                "success": True,
                "user_id": str(user.id),
                "email": user.email,
                "daily_limit": daily_limit,
                "daily_remaining": remaining,
                "daily_used": daily_limit - remaining,
                "can_create": allowed,
            }),
            200,
        )

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "message": f"Error fetching session info: {str(e)}",
            }),
            500,
        )


@taro_bp.route("/admin/users/<user_id>/reset-sessions", methods=["POST"])
@require_auth
@require_admin
def admin_reset_user_sessions(user_id):
    """Reset user's daily Taro sessions (admin utility).

    Closes all active sessions created today for the specified user.
    Used by admins to allow users to create new sessions after reaching their limit.

    Args:
        user_id: UUID of the user to reset sessions for

    Returns:
        JSON response with reset count and updated session info
        403: Unauthorized (requires admin)
        404: User not found
    """
    try:
        # Validate user_id format
        try:
            user_uuid = UUID(user_id)
        except ValueError:
            return jsonify({"error": "Invalid user ID format"}), 400

        # Verify user exists
        from src.models.user import User
        user = User.query.get(user_uuid)
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Get taro service
        session_service = _get_taro_services()

        # Reset sessions
        reset_count = session_service.reset_today_sessions(str(user_id))

        # Get remaining sessions info after reset (from user's tarif plan)
        daily_limit, _ = get_user_tarif_plan_limits(str(user_id))
        allowed, remaining = session_service.check_daily_limit(str(user_id), daily_limit)

        return (
            jsonify({
                "success": True,
                "message": f"Reset {reset_count} Taro sessions for {user.email}",
                "user_id": str(user.id),
                "email": user.email,
                "reset_count": reset_count,
                "daily_limit": daily_limit,
                "daily_remaining": remaining,
                "daily_used": daily_limit - remaining,
                "can_create": allowed,
            }),
            200,
        )

    except Exception as e:
        return (
            jsonify({
                "success": False,
                "message": f"Error resetting sessions: {str(e)}",
            }),
            500,
        )


# ============================================================================
# Admin Prompt Management Endpoints
# ============================================================================


@taro_bp.route("/admin/prompts", methods=["GET"])
@require_auth
@require_admin
def get_all_prompts():
    """Get all prompts with resolved metadata.

    Returns:
        JSON response with all prompts and defaults
        403: Unauthorized (requires admin)
    """
    try:
        prompt_service = _get_prompt_service()
        prompts = {}

        # Get all non-internal prompts with resolved metadata
        for slug in prompt_service.prompts:
            if not slug.startswith('_'):
                prompts[slug] = prompt_service.get_prompt(slug)

        return (
            jsonify({
                "success": True,
                "prompts": prompts,
                "defaults": prompt_service.defaults
            }),
            200
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            500
        )


@taro_bp.route("/admin/prompts/defaults", methods=["GET"])
@require_auth
@require_admin
def get_prompt_defaults():
    """Get default metadata.

    Returns:
        JSON response with current defaults
        403: Unauthorized (requires admin)
    """
    try:
        prompt_service = _get_prompt_service()
        return (
            jsonify({
                "success": True,
                "defaults": prompt_service.defaults
            }),
            200
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            500
        )


@taro_bp.route("/admin/prompts/defaults", methods=["PUT"])
@require_auth
@require_admin
def update_prompt_defaults():
    """Update default metadata.

    Returns:
        JSON response with updated defaults
        400: Invalid metadata
        403: Unauthorized (requires admin)
    """
    try:
        data = request.get_json() or {}
        prompt_service = _get_prompt_service()

        # Validate metadata fields - only allow specific fields
        allowed_keys = {'temperature', 'max_tokens', 'timeout'}
        data = {k: v for k, v in data.items() if k in allowed_keys}

        defaults = prompt_service.update_defaults(data)
        return (
            jsonify({
                "success": True,
                "defaults": defaults
            }),
            200
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            400
        )


@taro_bp.route("/admin/prompts/<slug>", methods=["GET"])
@require_auth
@require_admin
def get_prompt(slug):
    """Get single prompt with resolved metadata.

    Args:
        slug: Prompt identifier

    Returns:
        JSON response with prompt
        404: Prompt not found
        403: Unauthorized (requires admin)
    """
    try:
        prompt_service = _get_prompt_service()
        prompt = prompt_service.get_prompt(slug)
        return (
            jsonify({
                "success": True,
                "prompt": prompt
            }),
            200
        )
    except ValueError as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            404
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            500
        )


@taro_bp.route("/admin/prompts/<slug>", methods=["PUT"])
@require_auth
@require_admin
def update_prompt(slug):
    """Update a prompt (template + optional metadata overrides).

    Args:
        slug: Prompt identifier

    Request body:
        {
          "template": "...",
          "variables": [...],
          "temperature": 0.9,  (optional)
          "max_tokens": 3000   (optional)
        }

    Returns:
        JSON response with updated prompt
        400: Invalid template or metadata
        404: Prompt not found
        403: Unauthorized (requires admin)
    """
    try:
        data = request.get_json() or {}
        prompt_service = _get_prompt_service()

        # Validate template if provided
        if 'template' in data:
            variables = data.get('variables', [])
            prompt_service.validate_template(data['template'], variables)

        # Only allow specific fields
        allowed_keys = {'template', 'variables', 'temperature', 'max_tokens', 'timeout'}
        data = {k: v for k, v in data.items() if k in allowed_keys}

        updated = prompt_service.update_prompt(slug, data)
        return (
            jsonify({
                "success": True,
                "prompt": updated
            }),
            200
        )
    except ValueError as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            400
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            500
        )


@taro_bp.route("/admin/prompts/reset", methods=["POST"])
@require_auth
@require_admin
def reset_prompts():
    """Reset all prompts to distribution defaults.

    Returns:
        JSON response confirming reset
        400: Reset failed
        403: Unauthorized (requires admin)
    """
    try:
        prompt_service = _get_prompt_service()
        prompt_service.reset_to_defaults()
        return (
            jsonify({
                "success": True,
                "message": "Prompts reset to defaults"
            }),
            200
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            400
        )


@taro_bp.route("/admin/prompts/validate", methods=["POST"])
@require_auth
@require_admin
def validate_prompt():
    """Validate prompt template syntax.

    Request body:
        {
          "template": "...",
          "variables": [...]
        }

    Returns:
        JSON response with validation result
        400: Invalid template
        403: Unauthorized (requires admin)
    """
    try:
        data = request.get_json() or {}
        template = data.get('template', '')
        variables = data.get('variables', [])

        prompt_service = _get_prompt_service()
        prompt_service.validate_template(template, variables)

        return (
            jsonify({
                "success": True,
                "message": "Template is valid"
            }),
            200
        )
    except ValueError as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            400
        )
    except Exception as e:
        return (
            jsonify({
                "success": False,
                "error": str(e)
            }),
            400
        )
