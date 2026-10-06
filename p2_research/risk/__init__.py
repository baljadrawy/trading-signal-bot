"""P2-RM0 portfolio & risk MEASUREMENT foundation (offline research only; stdlib only).

Flow: PIT market state -> hypothetical portfolio -> exposure engine -> metrics -> flags -> deterministic RiskSnapshot.
Nothing here acts: no order, no sizing, no limit, no halt, no notification, no write outside the caller's output
directory. It is distinct from the protective B3 Risk Engine (P2G-ADR-09), reads no Paper, account or DB data, and
never optimizes anything. Crypto / Binance spot only.
"""
