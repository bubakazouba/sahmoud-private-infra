# LA Weekend Events — weirdest 10

Rolling 4-weekend curated list of the weirdest 10 LA events per weekend.

Dashboard: https://bubakazouba.github.io/la-weekend-events/

## How it works

Every Monday at ~10:08 AM PT, `@sahmoud_remind_bot` fires a reminder. Claude then:

1. Scrapes the 14 aggregator sites in `events.json` (11 from Becky + 3 I added).
2. Curates to the 10 weirdest for the upcoming weekend — cyphers, jump rope, puppets, pop-up choirs, immersive performance, costume parties, weird food fests, niche meetups.
3. Skips mainstream concerts / sports / galas.
4. Updates `events.json` and pushes.

## Filter semantics

- **Weirdness**: 1 = on-the-nose mainstream-adjacent, 2 = niche, 3 = wtf-did-I-just-read
- **Free only** hides anything paid
- Click any column header to sort

## Update cadence

| Weekend   | Fires on  | Reminder # |
|-----------|-----------|------------|
| Apr 25-26 | seeded    | —          |
| May 2-3   | Mon 4/27  | #10        |
| May 9-10  | Mon 5/4   | #11        |
| May 16-17 | Mon 5/11  | #12        |
