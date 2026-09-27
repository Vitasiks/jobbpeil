"""Process active, verified Vakt subscriptions once; no scheduling or retries."""
import argparse
from contextlib import closing, contextmanager
import errno
import json
import os
from pathlib import Path
import sqlite3

from vakt_run_once import dry_run_database, read_connection
from web_app import (
    DATABASE,
    get_vakt_candidates,
    mark_vakt_jobs_sent,
    send_vakt_job_alert_email,
)
from vakt_daily import alert_sent_today


class BatchAlreadyRunning(Exception):
    pass


@contextmanager
def batch_lock(path):
    # Keep the file: deleting it introduces an inode/recreation race. The OS
    # releases the actual lock on exit/crash, so stale files never block a run.
    with open(path, "a+b") as lock_file:
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                # Windows can lock a byte beyond EOF, including an empty file.
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise BatchAlreadyRunning from None
                    raise
            else:
                import fcntl
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise BatchAlreadyRunning from None
            locked = True
            yield
        finally:
            if locked:
                if os.name == "nt":
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def active_subscriptions(database):
    with closing(read_connection(database)) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(
            "SELECT id, email, profession_query, profession_query_key, fylke, "
            "active, verified_at, unsubscribe_token FROM vakt_subscriptions "
            "WHERE active=1 AND verified_at IS NOT NULL ORDER BY id"
        )]


def run_batch(database, dry_run=False):
    checked = sent = no_new = already_sent = errors = 0
    for subscription in active_subscriptions(database):
        checked += 1
        result = {key: subscription[key] for key in ("id", "profession_query", "fylke")}
        result["candidates_count"] = None
        phase = "matching"
        try:
            if alert_sent_today(subscription["id"], database):
                already_sent += 1
                result["status"] = "SKIP_ALREADY_SENT_TODAY"
                print(json.dumps(result, ensure_ascii=False), flush=True)
                continue
            candidates = get_vakt_candidates(subscription, limit=4, database=database)
            if not isinstance(candidates, list) or len(candidates) > 4:
                raise ValueError("Invalid candidate list")
            result["candidates_count"] = len(candidates)
            if not candidates:
                no_new += 1
                result["status"] = "NO_NEW"
            else:
                phase = "candidate validation"
                uuids = [candidate["vacancy_uuid"] for candidate in candidates]
                if any(not isinstance(uuid, str) or not uuid.strip() for uuid in uuids):
                    raise ValueError("Invalid candidate UUID")
                if dry_run:
                    # A preview must not be reported as SENT.
                    result["status"] = "DRY_RUN"
                else:
                    phase = "SMTP"
                    if send_vakt_job_alert_email(subscription, candidates) is not True:
                        raise RuntimeError("Sending not confirmed")
                    sent += 1
                    phase = "recording sent vacancies"
                    mark_vakt_jobs_sent(subscription["id"], uuids, database=database)
                    result["status"] = "SENT"
        except Exception as error:
            errors += 1
            result["status"] = "ERROR"
            # Never log exception messages: they may contain credentials/tokens.
            result["error"] = f"{phase}: {type(error).__name__}"
            if phase == "recording sent vacancies":
                result["warning"] = "Email sent; check sent records before retrying."
        print(json.dumps(result, ensure_ascii=False), flush=True)
    print(f"Subscriptions checked: {checked}")
    print(f"Emails sent: {sent}")
    print(f"No new jobs: {no_new}")
    print(f"Already sent today: {already_sent}")
    print(f"Errors: {errors}")
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview; no email or sent records")
    args = parser.parse_args(argv)
    lock_path = Path(DATABASE).resolve().with_name("vakt_run_all.lock")
    try:
        with batch_lock(lock_path):
            if args.dry_run:
                with dry_run_database(DATABASE) as snapshot:
                    return run_batch(snapshot, dry_run=True)
            return run_batch(DATABASE)
    except BatchAlreadyRunning:
        print("Another Vakt batch is already running. Nothing sent.")
        return 2
    except Exception as error:
        print(f"Vakt batch failed ({type(error).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
