Two exports describe the same members: `crm.csv` (columns `email,name,phone,city`) and `signup.csv` (columns `email,full_name,phone,city,plan`). Merge them into `output/members.csv`.

Rules:

- Output columns, in this order, with a header row: `email,name,phone,city,plan`.
- Trim leading and trailing spaces from every value. A value that is empty after trimming counts as missing.
- Match records by email, ignoring letter case. Write emails in lowercase. Include every email found in either file, once.
- `name`: the crm `name` if present, otherwise the signup `full_name`.
- `phone`: the signup phone if present, otherwise the crm phone. Normalise it by keeping only the digits; if that leaves 11 digits starting with `1`, drop the leading `1`; write the 10 digits as `NNN-NNN-NNNN`. Leave it empty if neither file has a phone.
- `city`: the crm city if present, otherwise the signup city.
- `plan`: the signup `plan`, or `none` if the email appears only in crm.
- Sort rows by email, A to Z.
