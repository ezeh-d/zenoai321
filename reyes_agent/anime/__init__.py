"""ZENO's anime and manga companion.

Two honest halves, matching how the rest of ZENO is built:

  * catalog  -- facts about a series, from AniList's free public GraphQL API.
               No key, no scraping, no piracy. Titles, synopsis, score,
               status, episode/chapter counts, genres, recommendations.
  * reader   -- READS a manga or manhwa PAGE the owner shows it, using ZENO's
               existing vision model. It understands the art and the dialogue
               together -- Japanese, Korean or English -- which plain OCR
               cannot do. It reads pages the owner provides; it never fetches
               copyrighted chapters from anywhere.

`library` tracks what the owner is reading and watching, locally, so
"where was I in Solo Leveling?" has an answer.
"""

from reyes_agent.anime import catalog, library, reader  # noqa: F401

__all__ = ["catalog", "library", "reader"]
