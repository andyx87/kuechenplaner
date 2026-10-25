SET search_path TO koch, public;

-- Beta-Bugreports: In-App-Meldungen der Tester. Pro Konto isoliert (RLS),
-- Super-Admin/Support liest alle per bypass.
CREATE TABLE IF NOT EXISTS bugreport (
  id          serial PRIMARY KEY,
  account_id  int REFERENCES account(id) ON DELETE CASCADE
                DEFAULT nullif(current_setting('app.account_id', true), '')::int,
  user_id     int REFERENCES app_user(id) ON DELETE SET NULL,
  seite       text,
  text        text NOT NULL,
  status      text NOT NULL DEFAULT 'offen',   -- offen | erledigt
  user_agent  text,
  erstellt_am timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE bugreport ENABLE ROW LEVEL SECURITY;
ALTER TABLE bugreport FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS acc_isolation ON bugreport;
CREATE POLICY acc_isolation ON bugreport
  USING (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int)
  WITH CHECK (current_setting('app.bypass', true) = 'on'
         OR account_id = nullif(current_setting('app.account_id', true), '')::int);
