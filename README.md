# Daily Fuel Price Reports Downloader

Το `download_daily_reports.py` κατεβάζει τα ημερήσια PDF δελτία τιμών καυσίμων από το `fuelprices.gr` και τα αποθηκεύει τοπικά.

## Τι κάνει

- Κατεβάζει αρχεία με όνομα μορφής `IMERISIO_DELTIO_PANELLINIO_dd_mm_yyyy.pdf`.
- Από προεπιλογή ξεκινάει από το πιο πρόσφατο διαθέσιμο τοπικό PDF στον φάκελο `daily_reports/` και συνεχίζει έως και σήμερα.
- Αν δεν υπάρχει κανένα τοπικό PDF, ξεκινάει από `2017-03-14`.
- Παραλείπει αρχεία που υπάρχουν ήδη, εκτός αν δοθεί `--force`.
- Κάνει retry σε παροδικά σφάλματα δικτύου ή HTTP.
- Σταματάει αμέσως αν κάποιο αρχείο αποτύχει οριστικά μετά τα retries.
- Εμφανίζει αναλυτικό progress τόσο για κάθε αρχείο όσο και για όλο το run.

## Default συμπεριφορά

Αν τρέξεις:

```bash
python download_daily_reports.py
```

το script:

1. ψάχνει στο `daily_reports/` για αρχεία `IMERISIO_DELTIO_PANELLINIO_*.pdf`
2. εντοπίζει την πιο πρόσφατη ημερομηνία από το όνομα του αρχείου
3. χρησιμοποιεί αυτή την ημερομηνία ως `start-date`
4. κατεβάζει ή ελέγχει αρχεία μέχρι και τη σημερινή ημερομηνία

Παράδειγμα: αν το πιο πρόσφατο τοπικό PDF είναι το `IMERISIO_DELTIO_PANELLINIO_11_03_2026.pdf`, το run θα καλύψει το διάστημα `2026-03-11` έως `2026-03-12`.

## Απαιτήσεις

- Python 3.10+ για τα type hints που χρησιμοποιούνται στο script
- πρόσβαση στο Internet προς `https://www.fuelprices.gr/`

Δεν απαιτούνται external Python packages.

## Χρήση

### Βασικό run

```bash
python download_daily_reports.py
```

### Συγκεκριμένο date range

```bash
python download_daily_reports.py --start-date 2026-03-01 --end-date 2026-03-12
```

### Re-download αρχείων ακόμα κι αν υπάρχουν

```bash
python download_daily_reports.py --start-date 2026-03-10 --end-date 2026-03-12 --force
```

### Διαφορετικός φάκελος output

```bash
python download_daily_reports.py --output-dir reports_archive
```

### Προσαρμογή timeout και retries

```bash
python download_daily_reports.py --timeout 60 --retries 10
```

## CLI options

- `--start-date YYYY-MM-DD`
  Ορίζει την πρώτη ημερομηνία που θα ελεγχθεί. Αν δεν δοθεί, το script χρησιμοποιεί την πιο πρόσφατη τοπική ημερομηνία ή fallback στο `2017-03-14`.
- `--end-date YYYY-MM-DD`
  Ορίζει την τελευταία ημερομηνία που θα ελεγχθεί. Default: σήμερα.
- `--output-dir PATH`
  Ορίζει τον φάκελο αποθήκευσης. Default: `daily_reports`.
- `--force`
  Κατεβάζει ξανά αρχεία ακόμα κι αν υπάρχουν ήδη τοπικά.
- `--timeout SECONDS`
  Timeout ανά HTTP request. Default: `30`.
- `--retries N`
  Πόσες φορές θα ξαναδοκιμάσει ένα αρχείο σε transient failures. Default: `8`.

## Πώς βρίσκει το τελευταίο τοπικό PDF

Το script δεν βασίζεται στο filesystem modified time. Αντί γι' αυτό:

- διαβάζει τα filenames που ταιριάζουν στο pattern `IMERISIO_DELTIO_PANELLINIO_*.pdf`
- κάνει parse το τμήμα ημερομηνίας `dd_mm_yyyy`
- μετατρέπει το όνομα σε `date`
- κρατάει τη μέγιστη ημερομηνία

Αυτό είναι πιο αξιόπιστο όταν έχουν γίνει copy, restore ή manual αλλαγές στα timestamps των αρχείων.

## Συμπεριφορά ανά αρχείο

Για κάθε ημερομηνία στο range:

- αν το PDF υπάρχει ήδη και δεν έχει δοθεί `--force`, γίνεται `SKIP`
- αν κατέβει επιτυχώς, γίνεται `OK`
- αν το site επιστρέψει `404`, γίνεται `MISSING`
- αν υπάρξει οριστική αποτυχία μετά τα retries, γίνεται `ERROR` και το run σταματάει

Τα προσωρινά downloads γράφονται πρώτα σε `.tmp` αρχείο και μετά γίνονται rename στο τελικό PDF. Έτσι αποφεύγονται μισοκατεβασμένα αρχεία σε διακοπή ή αποτυχία.

## Logging και progress

Το script εμφανίζει:

- γενικές γραμμές `INFO`
- γραμμές `RETRY` όταν ξαναδοκιμάζει
- γραμμές `OK`, `SKIP`, `MISSING`, `ERROR`
- progress bar για το συνολικό run
- progress bar για το τρέχον αρχείο όταν υπάρχει `Content-Length`
- τελικό `SUMMARY` με counts για `downloaded`, `skipped`, `missing`, `failed`

## Retry strategy

- Retry delay: `5` δευτερόλεπτα
- Per-download delay: `2` δευτερόλεπτα μεταξύ διαδοχικών reports
- Default retries: `8`

Γίνεται retry σε transient HTTP/network προβλήματα. Σε `404` το αρχείο θεωρείται missing και δεν αντιμετωπίζεται ως fatal error.

## Έξοδος προγράμματος

- επιστρέφει `0` όταν ολοκληρωθεί χωρίς fatal failures
- επιστρέφει `1` όταν υπάρξει οριστική αποτυχία σε κάποιο report

## Παραδείγματα καθημερινής χρήσης

### Καθημερινό incremental update

```bash
python download_daily_reports.py
```

### Backfill για παλιότερο διάστημα

```bash
python download_daily_reports.py --start-date 2023-08-01 --end-date 2023-08-31
```

### Έλεγχος μόνο για τις τελευταίες ημέρες

```bash
python download_daily_reports.py --start-date 2026-03-10
```

## Σημειώσεις

- Το script χρησιμοποιεί browser-like request headers για καλύτερη συμβατότητα με το remote site.
- Αν αλλάξει το naming pattern ή το URL των PDFs στο `fuelprices.gr`, θα χρειαστεί ενημέρωση στο script.
