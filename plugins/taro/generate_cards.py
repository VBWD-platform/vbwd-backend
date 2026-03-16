#!/usr/bin/env python3
"""Generate SVG images for all 78 tarot cards."""
import os
from pathlib import Path

# Card data
MAJOR_ARCANA = [
    (0, "The Fool"),
    (1, "The Magician"),
    (2, "The High Priestess"),
    (3, "The Empress"),
    (4, "The Emperor"),
    (5, "The Hierophant"),
    (6, "The Lovers"),
    (7, "The Chariot"),
    (8, "Strength"),
    (9, "The Hermit"),
    (10, "Wheel of Fortune"),
    (11, "Justice"),
    (12, "The Hanged Man"),
    (13, "Death"),
    (14, "Temperance"),
    (15, "The Devil"),
    (16, "The Tower"),
    (17, "The Star"),
    (18, "The Moon"),
    (19, "The Sun"),
    (20, "Judgement"),
    (21, "The World"),
]

MINOR_ARCANA_SUITS = {
    "cups": [
        "Ace",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Page",
        "Knight",
        "Queen",
        "King",
    ],
    "wands": [
        "Ace",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Page",
        "Knight",
        "Queen",
        "King",
    ],
    "swords": [
        "Ace",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Page",
        "Knight",
        "Queen",
        "King",
    ],
    "pentacles": [
        "Ace",
        "Two",
        "Three",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
        "Nine",
        "Ten",
        "Page",
        "Knight",
        "Queen",
        "King",
    ],
}

SUIT_COLORS = {
    "cups": "#3498db",  # Blue
    "wands": "#e74c3c",  # Red/Orange
    "swords": "#95a5a6",  # Gray
    "pentacles": "#f39c12",  # Gold
}

SUIT_SYMBOLS = {
    "cups": "♣",
    "wands": "♠",
    "swords": "♥",
    "pentacles": "♦",
}


def create_major_arcana_svg(number: int, name: str) -> str:
    """Create SVG for major arcana card."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="280" height="400" viewBox="0 0 280 400" xmlns="http://www.w3.org/2000/svg">
  <!-- Background -->
  <rect width="280" height="400" fill="#1a1a2e"/>

  <!-- Border -->
  <rect x="10" y="10" width="260" height="380" fill="none" stroke="#d4af37" stroke-width="2"/>
  <rect x="12" y="12" width="256" height="376" fill="none" stroke="#8b7500" stroke-width="1"/>

  <!-- Card number (top-left) -->
  <text x="30" y="50" font-family="Georgia, serif" font-size="32" font-weight="bold" fill="#d4af37" text-anchor="start">
    {number:02d}
  </text>

  <!-- Card symbol (center) -->
  <circle cx="140" cy="140" r="60" fill="none" stroke="#d4af37" stroke-width="2"/>
  <circle cx="140" cy="140" r="55" fill="none" stroke="#8b7500" stroke-width="1"/>
  <text x="140" y="160" font-family="Georgia, serif" font-size="80" fill="#d4af37" text-anchor="middle" opacity="0.3">
    ✦
  </text>

  <!-- Card title -->
  <text x="140" y="290" font-family="Georgia, serif" font-size="20" font-weight="bold" fill="#ffffff" text-anchor="middle">
    {name}
  </text>
  <text x="140" y="310" font-family="Georgia, serif" font-size="12" fill="#d4af37" text-anchor="middle">
    MAJOR ARCANA
  </text>

  <!-- Bottom ornament -->
  <line x1="50" y1="350" x2="230" y2="350" stroke="#d4af37" stroke-width="1"/>
  <circle cx="140" cy="350" r="3" fill="#d4af37"/>
</svg>"""


def create_minor_arcana_svg(suit: str, rank: str) -> str:
    """Create SVG for minor arcana card."""
    color = SUIT_COLORS[suit.lower()]
    suit_symbol = SUIT_SYMBOLS[suit.lower()]

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="280" height="400" viewBox="0 0 280 400" xmlns="http://www.w3.org/2000/svg">
  <!-- Background -->
  <rect width="280" height="400" fill="#1a1a2e"/>

  <!-- Border -->
  <rect x="10" y="10" width="260" height="380" fill="none" stroke="{color}" stroke-width="2"/>
  <rect x="12" y="12" width="256" height="376" fill="none" stroke="{color}" stroke-width="1" opacity="0.5"/>

  <!-- Suit symbol (top-left) -->
  <text x="30" y="50" font-family="Georgia, serif" font-size="28" fill="{color}" text-anchor="start">
    {suit_symbol}
  </text>

  <!-- Card symbol (center) -->
  <circle cx="140" cy="140" r="50" fill="none" stroke="{color}" stroke-width="2"/>
  <circle cx="140" cy="140" r="45" fill="none" stroke="{color}" stroke-width="1" opacity="0.5"/>
  <text x="140" y="155" font-family="Georgia, serif" font-size="60" fill="{color}" text-anchor="middle" opacity="0.4">
    {suit_symbol}
  </text>

  <!-- Card title -->
  <text x="140" y="290" font-family="Georgia, serif" font-size="18" font-weight="bold" fill="#ffffff" text-anchor="middle">
    {rank} of {suit.title()}
  </text>
  <text x="140" y="310" font-family="Georgia, serif" font-size="12" fill="{color}" text-anchor="middle">
    MINOR ARCANA
  </text>

  <!-- Bottom ornament -->
  <line x1="50" y1="350" x2="230" y2="350" stroke="{color}" stroke-width="1"/>
  <circle cx="140" cy="350" r="3" fill="{color}"/>
</svg>"""


def generate_all_cards():
    """Generate all 78 tarot card SVGs."""
    base_path = Path(__file__).parent / "assets" / "arcana"

    print("Generating Major Arcana cards...")
    major_path = base_path / "major"
    for number, name in MAJOR_ARCANA:
        svg_content = create_major_arcana_svg(number, name)
        filename = f"{number:02d}-{name.lower().replace(' ', '-')}.svg"
        filepath = major_path / filename
        filepath.write_text(svg_content)
        print(f"  ✓ Created {filename}")

    print("\nGenerating Minor Arcana cards...")
    for suit, ranks in MINOR_ARCANA_SUITS.items():
        print(f"  {suit.title()}:")
        suit_path = base_path / "minor" / suit
        for rank in ranks:
            svg_content = create_minor_arcana_svg(suit, rank)
            filename = f"{rank.lower()}-of-{suit}.svg"
            filepath = suit_path / filename
            filepath.write_text(svg_content)
            print(f"    ✓ Created {filename}")

    print(f"\n✓ Generated 78 tarot card SVGs in {base_path}")


if __name__ == "__main__":
    generate_all_cards()
