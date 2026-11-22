export const RESTAURANT_TIMEZONE = 'Asia/Bishkek';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

/** Weekday (0 = Monday, DATABASE_SCHEMA.md §10.2) "now" in the restaurant time zone. */
export function restaurantWeekday(now: Date = new Date()): number {
  const name = new Intl.DateTimeFormat('en-US', {
    weekday: 'short',
    timeZone: RESTAURANT_TIMEZONE,
  }).format(now);
  return WEEKDAYS.indexOf(name);
}
