-- Abo-Modell Stufe 3: Stripe-Abo + Foto-Credit-Pack.
-- Idempotenz-Tabelle für den Webhook: jedes Stripe-Event wird höchstens einmal verarbeitet
-- (Stripe stellt Events mehrfach zu / mit Retries). Idempotent ausführbar; Owner nötig.

SET search_path TO koch, public;

CREATE TABLE IF NOT EXISTS koch.stripe_event (
  event_id      text PRIMARY KEY,
  typ           text,
  verarbeitet_am timestamptz NOT NULL DEFAULT now()
);

-- Schneller Lookup eines Kontos zur Stripe-Subscription (invoice.paid / subscription.deleted).
CREATE INDEX IF NOT EXISTS account_stripe_sub_idx
  ON koch.account (stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;
