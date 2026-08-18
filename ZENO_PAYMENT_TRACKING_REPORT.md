# ZENO Payment Tracking Report

Date: 2026-08-18

Payment records contain project, agreed amount, currency, milestone, method,
due date and invoice reference. Invalid or non-positive amounts are rejected.
Due and overdue states are refreshed from stored evidence without polling.

A client's statement that payment was sent produces `CLIENT REPORTS PAYMENT —
OWNER VERIFICATION REQUIRED`. Only the owner can verify an amount, and evidence
is mandatory. Client reports and owner verification are separate durable audit
events. The engine never moves money, opens financial accounts or executes a
transaction.

Tests cover report-versus-verification separation, missing evidence, overdue
state and exclusion of simulated payments from production revenue.

Limit: payment status is bookkeeping, not bank reconciliation. Currency totals
are not silently converted; the dashboard explicitly tells the owner to inspect
records by currency.
