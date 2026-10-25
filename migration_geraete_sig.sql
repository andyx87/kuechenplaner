-- Pro-Rezept-Markierung „auf welche Gerätekombination angepasst": Signatur der Geräte
-- zum Zeitpunkt der Anpassung. „abgestimmt" = geraete_sig == aktuelle Geräte-Signatur.
ALTER TABLE koch.rezepte ADD COLUMN IF NOT EXISTS geraete_sig text;
