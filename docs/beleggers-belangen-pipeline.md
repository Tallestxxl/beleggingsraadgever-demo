# Beleggers Belangen kennispijplijn

## Doel

Columns gebruiken als private kennisbron voor analyse en bewijsvoering.

## Pipeline

```text
scan/PDF/foto
-> OCR of tekstimport
-> documentregistratie
-> chunking
-> vectorrepresentatie
-> retrieval bij aandeelanalyse
-> bronvermelding in rapport
```

## Documentmetadata

Per document bewaren we:

- titel
- auteur
- publicatiedatum
- rubriek, bijvoorbeeld Beter Beleggen of Educatie
- bronpad
- checksum
- ruwe OCR-tekst

## Chunking

Documenten worden in overlappende tekstblokken verdeeld. Elk blok krijgt:

- document-id
- chunk-index
- tekst
- tags
- embedding/vector

## Principeslaag

Naast retrieval maken we een aparte bibliotheek van goedgekeurde principes.

Voorbeeld:

```text
Titel: Dividendvalkuil
Categorie: dividend
Principe: Extreem hoog dividendrendement moet worden beoordeeld op houdbaarheid
en vrije kasstroom, niet alleen op percentage.
Status: goedgekeurd door gebruiker
Bron: column X, datum Y
```

Deze laag is belangrijk omdat het systeem dan niet willekeurig een passage
interpreteert, maar werkt met expliciet vastgelegde beleggingsregels.

## V1 aanpak

V1 ondersteunt tekstimport. OCR voegen we daarna toe als aparte stap, zodat we
de kwaliteit van de kennisbank eerst kunnen beoordelen.

