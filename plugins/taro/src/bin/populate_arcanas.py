#!/usr/bin/env python3
"""
Populate the arcana table with all 78 Tarot cards.

This script creates:
- 22 Major Arcana (0-21): The Fool through The World
- 14 Cups cards (Ace-King)
- 14 Wands cards (Ace-King)
- 14 Swords cards (Ace-King)
- 14 Pentacles cards (Ace-King)

Usage:
    python src/plugins/taro/bin/populate_arcanas.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.extensions import db
from plugins.taro.src.models.arcana import Arcana
from plugins.taro.src.enums import ArcanaType


# 22 Major Arcana (0-21)
MAJOR_ARCANA = [
    (
        0,
        "The Fool",
        "New beginnings, taking risks, innocence, inexperience",
        "Recklessness, naivety, carelessness, poor judgment",
    ),
    (
        1,
        "The Magician",
        "Resourcefulness, power, inspired action, magnetism",
        "Manipulation, poor planning, untapped talents, illusion",
    ),
    (
        2,
        "The High Priestess",
        "Intuition, sacred knowledge, divine feminine, subconscious",
        "Secrets, disconnected from intuition, superficiality",
    ),
    (
        3,
        "The Empress",
        "Femininity, beauty, abundance, nature, fertility",
        "Creative block, dependence, neglect, insecurity",
    ),
    (
        4,
        "The Emperor",
        "Authority, establishment, structure, control, father figure",
        "Domination, rigid, stubborn, lack of discipline",
    ),
    (
        5,
        "The Hierophant",
        "Spirituality, tradition, conformity, morality, ethics",
        "Rebellion, subversion, divergence, new approaches",
    ),
    (
        6,
        "The Lovers",
        "Love, harmony, trust, alignment, relationships, values alignment",
        "Disharmony, misalignment of values, broken communication",
    ),
    (
        7,
        "The Chariot",
        "Control, willpower, determination, self-discipline, direction",
        "Lack of direction, lack of control, aggression, impatience",
    ),
    (
        8,
        "Strength",
        "Strength, courage, patience, control, influence, inner strength",
        "Weakness, self-doubt, insecurity, inadequacy",
    ),
    (
        9,
        "The Hermit",
        "Soul searching, introspection, inner guidance, isolation, reflection",
        "Loneliness, isolation, recluse, withdrawing from society",
    ),
    (
        10,
        "Wheel of Fortune",
        "Good luck, karma, life cycles, destiny, turning point",
        "Bad luck, bad karma, setbacks, out of control",
    ),
    (
        11,
        "Justice",
        "Justice, fairness, truth, accountability, cause and effect",
        "Injustice, unfairness, bias, dishonesty",
    ),
    (
        12,
        "The Hanged Man",
        "Pause, surrender, restriction, letting go, new perspective",
        "Avoiding sacrifice, stalling, stubbornness, unwilling to change",
    ),
    (
        13,
        "Death",
        "Transformation, endings, beginnings, change, transition",
        "Resistance to change, personal transformation, inner purging",
    ),
    (
        14,
        "Temperance",
        "Balance, moderation, patience, finding meaning, purpose",
        "Imbalance, excess, lack of patience, volatility",
    ),
    (
        15,
        "The Devil",
        "Bondage, materialism, playfulness, detachment, cynicism",
        "Detachment, rejection, confusion, disagreement",
    ),
    (
        16,
        "The Tower",
        "Sudden change, upheaval, chaos, revelation, awakening",
        "Avoidance of disaster, fear, resistance to change",
    ),
    (
        17,
        "The Star",
        "Hope, faith, purpose, renewal, spirituality, balance, harmony",
        "Despair, cynicism, hopelessness, lost sense of purpose",
    ),
    (
        18,
        "The Moon",
        "Illusion, fear, anxiety, subconscious, intuition, uncertainty",
        "Clarity, awareness, perspective, understanding",
    ),
    (
        19,
        "The Sun",
        "Success, vitality, joy, positivity, fun, warmth, triumph",
        "Excessive pride, arrogance, lack of success",
    ),
    (
        20,
        "Judgement",
        "Reckoning, awakening, renewal, reckoning, inner calling",
        "Self-doubt, denial, doubt, ignorance",
    ),
    (
        21,
        "The World",
        "Completion, accomplishment, fulfillment, wholeness, fulfillment",
        "Incompleteness, no closure, seeking, lack of closure",
    ),
]

# Minor Arcana - Suits: Cups, Wands, Swords, Pentacles
# Ranks: Ace, Two, Three, Four, Five, Six, Seven, Eight, Nine, Ten, Page, Knight, Queen, King

MINOR_ARCANA = {
    "CUPS": [
        (
            "ACE",
            "Ace of Cups",
            "New love, new opportunity, new relationship, fertility, abundance",
            "Heartbreak, emotional loss, creative block, feeling blocked",
        ),
        (
            "TWO",
            "Two of Cups",
            "Partnership, connection, union, relationship, harmony, respect",
            "Disharmony, separation, divorce, distrust, misalignment",
        ),
        (
            "THREE",
            "Three of Cups",
            "Celebration, community, friendship, gatherings, teamwork",
            "Loneliness, isolation, distance, feeling disconnected",
        ),
        (
            "FOUR",
            "Four of Cups",
            "Apathy, contemplation, reevaluation, meditation, pause",
            "Restlessness, dissatisfaction, impatience, seeking",
        ),
        (
            "FIVE",
            "Five of Cups",
            "Grief, loss, sadness, feeling isolated, regret",
            "Acceptance, moving on, finding peace, closure",
        ),
        (
            "SIX",
            "Six of Cups",
            "Innocence, nostalgia, good memories, harmony, cheerfulness",
            "Naivety, bitterness, dwelling in past, lack of progress",
        ),
        (
            "SEVEN",
            "Seven of Cups",
            "Illusion, wishful thinking, choices, dreams, illusions",
            "Clarity, disillusionment, awakening, reality check",
        ),
        (
            "EIGHT",
            "Eight of Cups",
            "Abandonment, disappointment, moving on, change, leaving",
            "Stagnation, avoidance, staying, not ready to move on",
        ),
        (
            "NINE",
            "Nine of Cups",
            "Satisfaction, contentment, joy, abundance, wellbeing",
            "Dissatisfaction, greed, lack of appreciation, discontent",
        ),
        (
            "TEN",
            "Ten of Cups",
            "Harmony, happiness, alignment, family, foundation",
            "Disharmony, conflict, misalignment, separation, breakup",
        ),
        (
            "PAGE",
            "Page of Cups",
            "Creativity, curiosity, innocence, exploration, youthfulness",
            "Naive, lack of direction, scattered energy, lack of focus",
        ),
        (
            "KNIGHT",
            "Knight of Cups",
            "Romance, charm, grace, elegance, adventure, idealism",
            "Moodiness, jealousy, insecurity, immature, unrealistic",
        ),
        (
            "QUEEN",
            "Queen of Cups",
            "Emotional balance, intuition, nurture, caring, empathy",
            "Self-care issues, insecurity, emotional dependency, fragile",
        ),
        (
            "KING",
            "King of Cups",
            "Emotional balance, balance, diplomacy, maturity, control",
            "Emotional manipulation, moodiness, insecurity, unpredictable",
        ),
    ],
    "WANDS": [
        (
            "ACE",
            "Ace of Wands",
            "Inspiration, new opportunities, growth, potential, energy",
            "Lack of direction, lack of passion, obstacles, delays",
        ),
        (
            "TWO",
            "Two of Wands",
            "Planning, making decisions, leaving home, exploration, discovery",
            "Lack of direction, procrastination, indecision, lack of progress",
        ),
        (
            "THREE",
            "Three of Wands",
            "Expansion, exploration, foresight, progress, enterprise",
            "Lack of foresight, lack of growth, stagnation, delays",
        ),
        (
            "FOUR",
            "Four of Wands",
            "Celebration, harmony, marriage, home, community",
            "Conflict, broken partnerships, lack of support, instability",
        ),
        (
            "FIVE",
            "Five of Wands",
            "Conflict, disagreement, tension, competition, struggle",
            "Agreement, harmony, cooperation, resolution, peace",
        ),
        (
            "SIX",
            "Six of Wands",
            "Success, recognition, praise, victory, good reputation",
            "Failure, lack of recognition, little progress, lack of success",
        ),
        (
            "SEVEN",
            "Seven of Wands",
            "Fearlessness, perseverance, determination, competition, valor",
            "Exhaustion, giving up, overwhelmed, cowardice, defensiveness",
        ),
        (
            "EIGHT",
            "Eight of Wands",
            "Swiftness, action, progress, momentum, haste",
            "Slowing down, obstacles, delays, frustration, stagnation",
        ),
        (
            "NINE",
            "Nine of Wands",
            "Resilience, persistence, courage, strong boundaries, stamina",
            "Exhaustion, fragility, boundaries issues, lack of stamina",
        ),
        (
            "TEN",
            "Ten of Wands",
            "Burden, struggle, responsibility, hard work, stress",
            "Letting go, unburdened, sharing responsibility, relief",
        ),
        (
            "PAGE",
            "Page of Wands",
            "Enthusiasm, passion, adventure, discovery, exploration",
            "Scattered energy, immaturity, lack of focus, procrastination",
        ),
        (
            "KNIGHT",
            "Knight of Wands",
            "Passion, adventure, energy, impulsiveness, bravery",
            "Recklessness, impatience, lack of direction, quick tempered",
        ),
        (
            "QUEEN",
            "Queen of Wands",
            "Confidence, determination, energy, boldness, independence",
            "Lack of confidence, impatience, insecurity, overbearing",
        ),
        (
            "KING",
            "King of Wands",
            "Leadership, vision, inspiration, big picture, entrepreneur",
            "Impulsiveness, recklessness, lack of foresight, no vision",
        ),
    ],
    "SWORDS": [
        (
            "ACE",
            "Ace of Swords",
            "Clarity, truth, new ideas, breakthrough, mental clarity",
            "Confusion, lack of clarity, clouded mind, unclear thinking",
        ),
        (
            "TWO",
            "Two of Swords",
            "Stalemate, indecision, difficult choices, blockage",
            "Clarity, decisive, breakthrough, moving forward, clarity",
        ),
        (
            "THREE",
            "Three of Swords",
            "Difficulty, separation, heartbreak, painful truth, sorrow",
            "Healing, forgiveness, recovery, moving forward, acceptance",
        ),
        (
            "FOUR",
            "Four of Swords",
            "Rest, respite, contemplation, pause, recuperation",
            "Restlessness, unrest, lack of rest, agitation, resistance",
        ),
        (
            "FIVE",
            "Five of Swords",
            "Conflict, disagreement, competition, tension, loss",
            "Agreement, harmony, cooperation, resolution, reconciliation",
        ),
        (
            "SIX",
            "Six of Swords",
            "Transition, change, movement, progress, journeys",
            "Stagnation, stuck, obstacles, blocked progress",
        ),
        (
            "SEVEN",
            "Seven of Swords",
            "Deception, trickery, cheating, illusion, betrayal",
            "Honesty, truth, coming clean, exposure, revelation",
        ),
        (
            "EIGHT",
            "Eight of Swords",
            "Restriction, confusion, powerlessness, self-imposed limitation",
            "Freedom, clarity, empowerment, escape, breakthrough",
        ),
        (
            "NINE",
            "Nine of Swords",
            "Anxiety, worry, fear, stress, nightmares, despair",
            "Hope, relief, freedom from anxiety, moving on",
        ),
        (
            "TEN",
            "Ten of Swords",
            "Painful endings, betrayal, ruin, crisis, lowest point",
            "Recovery, awakening, moving on, forgiveness, healing",
        ),
        (
            "PAGE",
            "Page of Swords",
            "Curiosity, intelligence, new ideas, impartiality, observation",
            "Deception, mischief, curiosity, manipulation, cynicism",
        ),
        (
            "KNIGHT",
            "Knight of Swords",
            "Action, impulsiveness, defending, intellectual, truth-seeking",
            "Recklessness, impulsiveness, no restraint, aggression",
        ),
        (
            "QUEEN",
            "Queen of Swords",
            "Perception, clarity, truth, intellectual power, independence",
            "Harshness, coldness, cruelty, bitterness, loneliness",
        ),
        (
            "KING",
            "King of Swords",
            "Authority, intellectual power, analytical ability, truth",
            "Abuse of power, manipulation, tyranny, coldness",
        ),
    ],
    "PENTACLES": [
        (
            "ACE",
            "Ace of Pentacles",
            "New opportunity, abundance, prosperity, security, wealth",
            "Lost opportunity, missed luck, lack of abundance, hardship",
        ),
        (
            "TWO",
            "Two of Pentacles",
            "Balance, adaptability, managing resources, flexibility",
            "Imbalance, disorganization, overwhelm, mismanagement",
        ),
        (
            "THREE",
            "Three of Pentacles",
            "Collaboration, teamwork, learning, growth, achievement",
            "Lack of teamwork, lack of communication, lack of progress",
        ),
        (
            "FOUR",
            "Four of Pentacles",
            "Possessiveness, control, conservatism, security, hoarding",
            "Generosity, sharing, open-handedness, wealth, giving",
        ),
        (
            "FIVE",
            "Five of Pentacles",
            "Hardship, poverty, unemployment, feeling left out, betrayal",
            "Recovery, fortune, finding help, new opportunity, healing",
        ),
        (
            "SIX",
            "Six of Pentacles",
            "Charity, generosity, sharing, fairness, giving, abundance",
            "Stinginess, selfishness, lack of generosity, unfairness",
        ),
        (
            "SEVEN",
            "Seven of Pentacles",
            "Perseverance, long-term planning, effort, hard work, reward",
            "Lack of progress, procrastination, no improvement, loss",
        ),
        (
            "EIGHT",
            "Eight of Pentacles",
            "Apprenticeship, mastery, skill, expertise, development",
            "Lack of focus, lack of skill, mediocrity, unfulfilled potential",
        ),
        (
            "NINE",
            "Nine of Pentacles",
            "Abundance, luxury, self-sufficiency, financial independence",
            "Lack of independence, financial struggle, dependence",
        ),
        (
            "TEN",
            "Ten of Pentacles",
            "Wealth, family, legacy, inheritance, stability, abundance",
            "Financial loss, struggle, lack of security, broken family",
        ),
        (
            "PAGE",
            "Page of Pentacles",
            "Student, ambition, eagerness, new opportunities, studious",
            "Lack of ambition, lack of motivation, procrastination, wasteful",
        ),
        (
            "KNIGHT",
            "Knight of Pentacles",
            "Reliability, loyalty, methodical, discipline, caution",
            "Laziness, irresponsibility, lack of progress, carelessness",
        ),
        (
            "QUEEN",
            "Queen of Pentacles",
            "Abundance, nurturing, security, practicality, creature comforts",
            "Insecurity, lack of abundance, fear of scarcity, neglect",
        ),
        (
            "KING",
            "King of Pentacles",
            "Wealth, success, abundance, prosperity, leadership",
            "Greed, lack of generosity, miserliness, waste",
        ),
    ],
}


def populate_arcanas():
    """Populate database with all 78 Tarot cards."""
    print("Populating Arcana table with 78 Tarot cards...")

    # Check if already populated
    existing_count = db.session.query(Arcana).count()
    if existing_count >= 78:
        print(f"✓ Database already has {existing_count} cards. Skipping population.")
        return

    cards_created = 0

    # Create Major Arcana
    print("\nCreating Major Arcana (22 cards)...")
    for number, name, upright, reversed in MAJOR_ARCANA:
        arcana = Arcana(
            number=number,
            name=name,
            suit=None,
            rank=None,
            arcana_type=ArcanaType.MAJOR_ARCANA.value,
            upright_meaning=upright,
            reversed_meaning=reversed,
            image_url=f"/api/v1/taro/assets/arcana/major/{number:02d}-{name.lower().replace(' ', '-')}.svg",
        )
        db.session.add(arcana)
        cards_created += 1

    db.session.commit()
    print(f"✓ Created {cards_created} Major Arcana cards")

    # Create Minor Arcana
    suit_colors = {
        "CUPS": "💧",
        "WANDS": "🔥",
        "SWORDS": "⚔️",
        "PENTACLES": "💰",
    }

    for suit, cards in MINOR_ARCANA.items():
        print(f"\nCreating {suit} ({len(cards)} cards)...")
        for rank, name, upright, reversed in cards:
            arcana = Arcana(
                number=None,
                name=name,
                suit=suit,
                rank=rank,
                arcana_type=suit,
                upright_meaning=upright,
                reversed_meaning=reversed,
                image_url=f"/api/v1/taro/assets/arcana/minor/{suit.lower()}/{rank.lower()}-of-{suit.lower()}.svg",
            )
            db.session.add(arcana)
            cards_created += 1

        db.session.commit()
        print(f"✓ Created {len(cards)} {suit} cards")

    # Final count
    total_count = db.session.query(Arcana).count()
    print(f"\n{'='*50}")
    print(f"✓ SUCCESS: Populated {total_count} Tarot cards")
    print(f"  - 22 Major Arcana (0-21)")
    print(f"  - 14 Cups cards")
    print(f"  - 14 Wands cards")
    print(f"  - 14 Swords cards")
    print(f"  - 14 Pentacles cards")
    print(f"{'='*50}")


if __name__ == "__main__":
    from src.app import create_app

    app = create_app()
    with app.app_context():
        populate_arcanas()
