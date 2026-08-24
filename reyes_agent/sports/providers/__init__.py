"""Sports data provider adapters (football-data.org, API-Sports).

Keys are read from the gitignored .env (loaded by reyes_agent.config); they are
never hard-coded or committed. Each provider caches aggressively to respect free
tier limits and reports honest health (AVAILABLE/AUTH_REQUIRED/RATE_LIMITED).
"""
