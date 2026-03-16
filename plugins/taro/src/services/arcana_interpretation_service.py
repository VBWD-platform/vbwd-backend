"""ArcanaInterpretationService - LLM integration for card interpretations."""
from typing import Optional, Tuple, List
from plugins.taro.src.repositories.taro_card_draw_repository import (
    TaroCardDrawRepository,
)
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.models.taro_card_draw import TaroCardDraw
from plugins.taro.src.enums import CardPosition, CardOrientation


class ArcanaInterpretationService:
    """Service for generating Tarot card interpretations via LLM."""

    def __init__(
        self,
        llm_client,  # LLM client (e.g., OpenAI, Anthropic, etc.)
        card_draw_repo: TaroCardDrawRepository,
        model_name: str = "gpt-4",
        temperature: float = 0.8,
        max_tokens: int = 200,
    ):
        """Initialize interpretation service.

        Args:
            llm_client: LLM client for generating interpretations
            card_draw_repo: Repository for card draw data access
            model_name: Name of LLM model to use
            temperature: LLM temperature for creativity (0.0-1.0)
            max_tokens: Max tokens per interpretation
        """
        self.llm_client = llm_client
        self.card_draw_repo = card_draw_repo
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate_interpretation(
        self,
        arcana: Arcana,
        position: CardPosition,
        orientation: CardOrientation,
    ) -> Tuple[str, int]:
        """Generate unique interpretation for a card in context.

        Args:
            arcana: The Arcana card
            position: Position in spread (PAST, PRESENT, FUTURE)
            orientation: Card orientation (UPRIGHT, REVERSED)

        Returns:
            Tuple of (interpretation: str, tokens_used: int)
        """
        # Build prompt
        prompt = self._build_interpretation_prompt(
            arcana=arcana,
            position=position,
            orientation=orientation,
        )

        try:
            # Generate interpretation via LLM
            interpretation = self.llm_client.generate(
                prompt=prompt,
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            # Calculate token cost (approximate: 1 token per word)
            tokens_used = len(interpretation.split()) // 4  # ~4 chars per token

            return interpretation, tokens_used

        except Exception as e:
            # Fallback if LLM fails
            print(f"LLM error: {e}")
            fallback = self._build_fallback_interpretation(arcana, orientation)
            return fallback, 5

    def _build_interpretation_prompt(
        self,
        arcana: Arcana,
        position: CardPosition,
        orientation: CardOrientation,
    ) -> str:
        """Build LLM prompt for interpretation."""
        meaning = (
            arcana.upright_meaning
            if orientation == CardOrientation.UPRIGHT
            else arcana.reversed_meaning
        )

        position_context = {
            CardPosition.PAST: "This card represents influences from the past",
            CardPosition.PRESENT: "This card represents the current situation",
            CardPosition.FUTURE: "This card represents what may come ahead",
        }.get(position, "")

        prompt = f"""Generate a brief, insightful Tarot card interpretation:

Card: {arcana.name}
Orientation: {orientation.value}
Position: {position.value}
Base Meaning: {meaning}
Context: {position_context}

Provide a 1-2 sentence interpretation that:
- Integrates the position context
- Reflects whether the card is upright or reversed
- Is specific and meaningful
- Provides actionable insight

Keep it concise and mystical."""

        return prompt

    def _build_fallback_interpretation(
        self,
        arcana: Arcana,
        orientation: CardOrientation,
    ) -> str:
        """Build fallback interpretation if LLM fails."""
        meaning = (
            arcana.upright_meaning
            if orientation == CardOrientation.UPRIGHT
            else arcana.reversed_meaning
        )
        return f"{arcana.name}: {meaning}"

    def interpret_spread(
        self,
        cards: List[TaroCardDraw],
    ) -> Tuple[str, int]:
        """Generate cohesive interpretation for entire 3-card spread.

        Args:
            cards: List of TaroCardDraw cards (typically 3)

        Returns:
            Tuple of (spread_interpretation: str, tokens_used: int)
        """
        # Get Arcana data for each card
        arcana_list = []
        for card in cards:
            from src.extensions import db

            arcana = (
                db.session.query(Arcana).filter(Arcana.id == card.arcana_id).first()
            )
            if arcana:
                arcana_list.append((card, arcana))

        # Build spread prompt
        prompt = self._build_spread_prompt(arcana_list)

        try:
            interpretation = self.llm_client.generate(
                prompt=prompt,
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens * 2,  # More tokens for full spread
            )

            tokens_used = len(interpretation.split()) // 4
            return interpretation, tokens_used

        except Exception as e:
            print(f"LLM error for spread: {e}")
            fallback = "Your reading reveals a journey of growth and transformation."
            return fallback, 10

    def _build_spread_prompt(
        self, arcana_list: List[Tuple[TaroCardDraw, Arcana]]
    ) -> str:
        """Build LLM prompt for 3-card spread interpretation."""
        cards_text = ""
        for i, (card, arcana) in enumerate(arcana_list):
            meaning = (
                arcana.upright_meaning
                if card.orientation == CardOrientation.UPRIGHT.value
                else arcana.reversed_meaning
            )
            cards_text += (
                f"\n{card.position}: {arcana.name} ({card.orientation}) - {meaning}"
            )

        prompt = f"""Generate a mystical interpretation of this Tarot spread:
{cards_text}

Provide a 3-4 sentence interpretation that:
- Addresses the overall narrative of Past → Present → Future
- Connects the three cards thematically
- Offers insight and guidance
- Is empowering and positive while honest

Keep it evocative and meaningful."""

        return prompt

    def generate_follow_up_interpretation(
        self,
        original_cards: List[Arcana],
        follow_up_type: str,
        question: str,
    ) -> Tuple[str, int]:
        """Generate interpretation for follow-up question.

        Args:
            original_cards: Original 3-card spread
            follow_up_type: Type of follow-up (SAME_CARDS, ADDITIONAL, NEW_SPREAD)
            question: User's follow-up question

        Returns:
            Tuple of (interpretation: str, tokens_used: int)
        """
        prompt = self._build_follow_up_prompt(
            original_cards=original_cards,
            follow_up_type=follow_up_type,
            question=question,
        )

        try:
            interpretation = self.llm_client.generate(
                prompt=prompt,
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )

            tokens_used = len(interpretation.split()) // 4
            return interpretation, tokens_used

        except Exception as e:
            print(f"LLM error for follow-up: {e}")
            fallback = f"Regarding your question about {question[:20]}..., deeper insight reveals..."
            return fallback, 5

    def _build_follow_up_prompt(
        self,
        original_cards: List[Arcana],
        follow_up_type: str,
        question: str,
    ) -> str:
        """Build LLM prompt for follow-up question."""
        cards_text = "\n".join([f"- {c.name}" for c in original_cards])

        prompt = f"""The user asked a follow-up question about their Tarot reading:

Original cards: {cards_text}
Question: {question}
Follow-up type: {follow_up_type}

Generate a brief, insightful follow-up interpretation that:
- Addresses the specific question
- Builds on the original reading
- Provides additional clarity or perspective
- Is 1-2 sentences

Keep it concise and mystical."""

        return prompt
