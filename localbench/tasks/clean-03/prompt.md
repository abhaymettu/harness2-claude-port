The file `shipments.csv` records parcel weights and lengths in mixed units. Convert everything to metric and write `output/shipments_metric.csv`.

Rules:

- Output columns, in this order, with a header row: `shipment_id,weight_kg,length_cm`.
- Weight units that appear: `kg`, `g`, `lb` (also written `lbs`) and `oz`. Length units: `cm`, `m` and `in`. Units may be in any letter case and may or may not have a space after the number.
- Use these factors: 1 g = 0.001 kg, 1 lb = 0.45359237 kg, 1 oz = 0.028349523125 kg, 1 m = 100 cm, 1 in = 2.54 cm.
- Round `weight_kg` to exactly 3 decimal places and `length_cm` to exactly 1 decimal place, always writing that many digits (`2.5 kg` becomes `2.500`, `30 cm` becomes `30.0`).
- Keep the rows in the same order as the input and keep `shipment_id` unchanged.
