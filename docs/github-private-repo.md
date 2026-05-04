# Private GitHub repository

Deze workspace is al een lokale Git-repository. Er is nog geen remote ingesteld
en `gh` is in deze omgeving niet beschikbaar.

## Aanpak

1. Maak op GitHub een nieuwe private repository aan.
2. Voeg lokaal de remote toe:

```bash
git remote add origin git@github.com:<gebruikersnaam>/<repo>.git
```

3. Controleer de remote:

```bash
git remote -v
```

4. Commit lokaal:

```bash
git add README.md pyproject.toml .gitignore docs src scripts tests data
git commit -m "Initial beleggingsraadgever scaffold"
```

5. Push naar GitHub:

```bash
git push -u origin main
```

## Private data

De `.gitignore` sluit lokale scans, OCR-output, SQLite databases, indexen en
secrets uit. Controleer voor de eerste push altijd:

```bash
git status --short
```

Er mogen geen persoonlijke datafiles of scans gestaged zijn.

## Later

Als `gh` beschikbaar is, kan de flow worden uitgebreid met:

- repo aanmaken via CLI
- branch aanmaken
- pull request openen
- checks uitlezen

