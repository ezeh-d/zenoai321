"""ZENO sports intelligence: evidence-based prediction (Elo + Poisson + live).

Provider data ingestion (Sportradar/SportsDataIO/StatsBomb) is gated and mostly
AUTH_REQUIRED pending credentials; the PREDICTION math here is real and works
from any results -- it never repeats a provider probability as its own.
"""
