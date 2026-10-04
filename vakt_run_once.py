"""Run one Vakt subscription explicitly; no scheduler or automatic retries."""
import argparse
from contextlib import closing, contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile

from web_app import (
    DATABASE,
    get_vakt_candidates,
    vakt_delivery_plan,
    mark_vakt_jobs_sent,
    send_vakt_job_alert_email,
    update_vakt_communication,
)
from nav_database import initialize_database


def read_connection(database):
    return sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True)


@contextmanager
def dry_run_database(database):
    # Candidate selection initializes the schema. Confine that to a snapshot.
    # The existing ACTIVE-job loader still reads the live job catalogue read-only.
    with tempfile.TemporaryDirectory(prefix="jobbpeil-vakt-preview-") as directory:
        snapshot = Path(directory) / "nav_jobs.db"
        with closing(read_connection(database)) as source:
            with closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
        yield snapshot


def list_subscriptions(email, database):
    initialize_database(database)
    with closing(read_connection(database)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, profession_query, fylke FROM vakt_subscriptions "
            "WHERE email=? AND active=1 AND verified_at IS NOT NULL ORDER BY id",
            (email,),
        ).fetchall()
    print(json.dumps([dict(row) for row in rows], ensure_ascii=False))
    return 0


def run_subscription(subscription_id, database, dry_run=False):
    initialize_database(database)
    with closing(read_connection(database)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT id, email, profession_query, profession_query_key, fylke, "
            "active, verified_at, unsubscribe_token, last_vakt_email_at, "
            "last_status_email_at FROM vakt_subscriptions "
            "WHERE id=? AND active=1 AND verified_at IS NOT NULL",
            (subscription_id,),
        ).fetchone()
    if row is None:
        print("Subscription not found, inactive or unverified. Nothing sent.")
        return 1
    subscription = dict(row)
    print("Subscription:")
    print(json.dumps({key: subscription[key] for key in
                      ("id", "email", "profession_query", "fylke",
                       "last_vakt_email_at", "last_status_email_at")},
                     ensure_ascii=False), flush=True)
    candidates_snapshot = get_vakt_candidates(subscription, limit=4, database=database)
    plan = vakt_delivery_plan(subscription, database=database,
                              candidates_override=candidates_snapshot)
    mode = plan["mode"]
    candidates = plan["strict"] or plan["fallback"] or plan["regional"]
    print(json.dumps({
        "strict_count": len(plan["strict"]),
        "fallback_count": len(plan["fallback"]),
        "regional_count": len(plan["regional"]),
        "email_mode": mode,
        "would_send": mode != "NO_NEW_SKIPPED_RECENT_STATUS",
    }, ensure_ascii=False))
    if mode == "INACTIVE":
        print("No new candidates.")
        return 0
    if mode == "NO_NEW_SKIPPED_RECENT_STATUS":
        print("No new status needed yet.")
        return 0
    print("Candidates:")
    for candidate in candidates:
        print(json.dumps({key: candidate.get(key) for key in
                          ("vacancy_uuid", "title", "employer", "fylke")},
                         ensure_ascii=False), flush=True)
    if dry_run:
        print("Dry run: nothing sent; no vacancies marked sent.")
        return 0

    try:
        sent = send_vakt_job_alert_email(subscription, candidates, email_mode=mode)
    except Exception as error:
        # Exception text can contain SMTP credentials or tokens: show type only.
        print(f"Email sending failed ({type(error).__name__}); no vacancies marked sent.")
        return 1
    if sent is not True:
        print("Email sending was not confirmed; no vacancies marked sent.")
        return 1

    sent_uuids = [candidate["vacancy_uuid"] for candidate in candidates]
    try:
        if sent_uuids:
            mark_vakt_jobs_sent(subscription["id"], sent_uuids, database=database)
        update_vakt_communication(subscription["id"], mode, database=database)
    except Exception as error:
        print(f"Email sent, but recording sent vacancies failed ({type(error).__name__}). "
              "Check sent records before retrying.")
        return 1
    try:
        remaining = get_vakt_candidates(subscription, limit=4, database=database)
    except Exception as error:
        print(f"Email sent and recorded; dedupe check failed ({type(error).__name__}).")
        return 1
    if set(sent_uuids).intersection(candidate["vacancy_uuid"] for candidate in remaining):
        print("Dedupe check: FAIL")
        return 1
    print("Dedupe check: PASS")
    return 0


def positive_id(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("subscription-id must be a positive integer") from None
    if number < 1:
        raise argparse.ArgumentTypeError("subscription-id must be a positive integer")
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--subscription-id", type=positive_id)
    mode.add_argument("--list", action="store_true", dest="list_mode")
    parser.add_argument("--email", help="Email to look up in --list mode")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending or marking sent")
    args = parser.parse_args(argv)
    if args.list_mode and (not args.email or not args.email.strip()):
        parser.error("--list requires --email")
    if args.list_mode and args.dry_run:
        parser.error("--dry-run requires --subscription-id")
    if not args.list_mode and args.email is not None:
        parser.error("--email is only supported with --list")
    try:
        if args.list_mode:
            return list_subscriptions(args.email.strip().lower(), DATABASE)
        if args.dry_run:
            with dry_run_database(DATABASE) as snapshot:
                return run_subscription(args.subscription_id, snapshot, dry_run=True)
        return run_subscription(args.subscription_id, DATABASE)
    except Exception as error:
        print(f"Vakt runner failed ({type(error).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
