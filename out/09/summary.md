# Issue 09 manual verification (4 real scan PDFs)

```text
source pdfs      : 4
pages rendered   : 154
blank pages      : 37
unique pages     : 154
candidate versions kept : 0
hash method      : phash (threshold hamming <= 6)
alerts:
  - [no_clue] no page-number clue available; completeness is not claimed
```

## Content-level repeat-scan merge demo (real page + perturbed rescan)

- phash distance between the two scans: **2** (<= 6 => near-dup merge)
- at threshold 6: **1** cluster(s) (2 candidate version(s) kept)
- at threshold 1 (reversible split): **2** cluster(s)

> Merging is reversible: candidate pages are retained and re-clustering
> at a stricter threshold splits any false merge (拆分误合并).
