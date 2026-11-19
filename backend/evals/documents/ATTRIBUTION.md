# Evaluation documents

The evaluation (SMA-51) uses three Wikipedia articles, exported to PDF by Wikipedia's own
REST API on 19 November 2026 and frozen here, so the page numbers in `../cases.jsonl` never
drift when the articles change online.

| File | Article | Revision | Pages |
|---|---|---|---|
| `french_revolution.pdf` | [French Revolution](https://en.wikipedia.org/w/index.php?title=French_Revolution&oldid=1384853060) | 1384853060 (10 Nov 2026) | 39 |
| `photosynthesis.pdf` | [Photosynthesis](https://en.wikipedia.org/w/index.php?title=Photosynthesis&oldid=1385696147) | 1385696147 (14 Nov 2026) | 27 |
| `thermodynamics.pdf` | [Thermodynamics](https://en.wikipedia.org/w/index.php?title=Thermodynamics&oldid=1386227873) | 1386227873 (17 Nov 2026) | 15 |

**Licence:** the text is © Wikipedia contributors and available under the
[Creative Commons Attribution-ShareAlike 4.0 License](https://creativecommons.org/licenses/by-sa/4.0/).
These PDFs are unmodified exports from `https://en.wikipedia.org/api/rest_v1/page/pdf/<title>`;
they are redistributed here under the same licence, for testing only.

Public material on purpose: the evaluation sends these texts to free AI APIs, and Gemini's
free tier may use prompts for training (CLAUDE.md).
