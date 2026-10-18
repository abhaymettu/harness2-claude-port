"""A tiny CSV reader for comma-separated text with double-quoted fields."""


def parse_line(line):
    """Split one CSV line into a list of field strings."""
    fields = []
    buf = []
    in_quotes = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"':
            if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                buf.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    fields.append("".join(buf))
    return fields


def parse(text):
    """Parse CSV text whose first line is a header into a list of dicts. Blank lines are skipped."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    header = parse_line(lines[0])
    return [dict(zip(header, parse_line(line))) for line in lines[1:]]
