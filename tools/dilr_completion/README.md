# Completing withheld book DILR sets

Pipeline, run in order (S = a scratch folder holding `v72/streakrunner_v73.html` and `books/pdf/*.pdf`):

1. `ocr_extract.py` + `ocr_run.py`: OCR the header of every book set scan and flag sets with fewer questions than the "Directions for Questions a to b" range (produces INCOMPLETE73).
2. `book_ocr.py` / `col_ocr.py`: render the Arun Sharma chapter PDFs and OCR each page column with line positions.
3. `locate.py`: find each flagged set's header and question numbers in the PDFs and extract question text and options.
4. `complete.py`: match existing questions, read the answer keys, and accept a missing question only when its answer comes from a key block (or solution) that agrees with the bank on the set's existing questions.

`status_2026-10-10.json` is the last result. All 168 sets are blocked: the screenshots show only 3 of 4 answer-key columns (Q4, Q8, Q12, ... have no answer), and the solution pages are mostly absent.
