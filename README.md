# JobbPeil

**Finn din retning**

JobbPeil is a Norwegian job-search and labour-market navigation platform built to help users not only find vacancies, but also understand where to move next.

Live site: https://jobbpeil.no

## Main features

- Search real job vacancies
- Filter by profession
- Filter by fylke
- Filter by kommune
- Guided Explore flow with 5 questions
- Vacancy detail pages
- Application/contact handling
- JobbPeil Vakt email alerts
- Email verification
- Duplicate protection for alerts
- Responsive UI

## Data sources

Current source:

- NAV / Arbeidsplassen

Planned:

- SSB labour-market statistics
- additional trusted Norwegian labour-market sources

## Tech stack

- Python
- SQLite
- server-side rendered HTML
- custom vacancy matching
- Ubuntu VPS
- Nginx
- systemd
- HTTPS / Let's Encrypt
- SMTP
- Google Analytics 4

## JobbPeil Vakt

JobbPeil Vakt automatically checks for new relevant vacancies.

Current logic:

- runs daily at 08:00 Europe/Oslo
- only verified active subscriptions are processed
- up to 4 vacancies per email
- duplicate vacancies are not sent twice
- maximum one alert email per day
- no email is sent if there are no new relevant vacancies

## Security

Production setup includes:

- SSH key authentication
- password SSH login disabled
- root SSH login disabled
- UFW firewall
- fail2ban
- HTTPS
- HSTS
- Content Security Policy
- secrets stored outside the repository

## Testing

Automated tests cover:

- vacancy search
- pagination
- filters
- Explore
- application/contact handling
- Vakt verification
- candidate matching
- deduplication
- daily send guard

Current test suite:

**91 tests passing**

## My role

I designed and built JobbPeil as an end-to-end project, including:

- product concept
- UX structure
- backend development
- vacancy search and filtering
- matching logic
- email alert system
- production deployment
- server configuration
- analytics
- testing and debugging

## Status

JobbPeil is live and under active development.

https://jobbpeil.no
