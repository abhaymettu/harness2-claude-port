The file `lab_report.txt` is a water quality report listing measurements for several samples. Extract every measurement into `output/measurements.csv`.

Rules:

- Columns, in this order, with a header row: `sample_id,analyte,value_mg_l`.
- One row per measurement line in the report.
- `sample_id` is the code after `Sample` (for example `CW-03`).
- `analyte` is the analyte name exactly as printed (for example `Nitrate`).
- `value_mg_l` is the value in milligrams per litre. Values given in `ug/L` must be divided by 1000. Write every number with exactly 4 decimal places (`4.2 mg/L` becomes `4.2000`, `3.1 ug/L` becomes `0.0031`).
- If a value is written with `<` (below the detection limit), write `BDL` instead of a number.
- Sort rows by `sample_id`, then by `analyte`, both A to Z.
