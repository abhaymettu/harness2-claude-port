"""Date ranges that include both their start and end day."""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def __post_init__(self):
        if self.end < self.start:
            raise ValueError("end is before start")

    def contains(self, day):
        return self.start <= day <= self.end

    def length(self):
        """Number of days covered, counting both ends."""
        return (self.end - self.start).days + 1

    def days(self):
        return [self.start + timedelta(days=n) for n in range(self.length())]

    def overlaps(self, other):
        return self.start <= other.end and other.start <= self.end


def filter_events(events, date_range):
    """Keep the (name, day) pairs whose day falls inside `date_range`."""
    return [event for event in events if date_range.contains(event[1])]


def ranges_on(day, ranges):
    """Return the ranges that cover `day`, in their original order."""
    return [r for r in ranges if r.contains(day)]
