# Beleggingsraadgever

Local-first MVP voor een persoonlijke beleggingsraadgever met bewijsvoering.

Het doel van dit project is een systeem dat aandelen in NL/EU/VS on-demand kan
analyseren met end-of-day data, fundamentele data, macrocontext, jouw
portefeuille en een private kennisbank met Beleggers Belangen-columns en eigen
notities.

## V1 uitgangspunten

- Alleen voor eigen gebruik.
- NL/EU/VS als beleggingsuniversum.
- End-of-day data, maar analyse op ieder gewenst moment.
- Structured data voor cijfers, ratio's, macro en portefeuille.
- RAG/vectorlaag voor columns, notities, jaarverslagfragmenten en principes.
- Regels voor berekeningen en limieten; AI voor synthese en rapportage.
- Geen brokerkoppeling in v1.

## Quickstart

Deze eerste versie gebruikt alleen de Python standard library.

```bash
python3 -m unittest discover -s tests
python3 scripts/demo_analysis.py
```

Of handmatig:

```bash
PYTHONPATH=src python3 -m beleggingsraadgever init-db
PYTHONPATH=src python3 -m beleggingsraadgever demo-seed
PYTHONPATH=src python3 -m beleggingsraadgever analyze DEMO
```

De lokale database komt standaard in:

```text
data/local/beleggingsraadgever.sqlite
```

## Belangrijke mappen

```text
src/beleggingsraadgever/   Applicatiecode
docs/                      Architectuur en ontwerpkeuzes
scripts/                   Lokale hulpscripts
tests/                     Unit tests
data/raw/                  Lokale scans/PDFs/exports, niet committen
data/local/                Lokale SQLite database, niet committen
data/processed/            OCR-tekst en tussenbestanden, niet committen
data/indexes/              Vectorindexen of afgeleide indexbestanden
```

## Private GitHub repository

De repo is lokaal al bruikbaar. Voor publicatie naar GitHub: maak eerst een
private repository aan en voeg daarna de remote toe. Zie
`docs/github-private-repo.md`.
