"""Test-only people, created and removed by the verification suites.

Why this exists
---------------
The demo roster is deliberately small: one HR partner (Priya), one manager
(Arjun), and eleven exiting employees who all report to him. That is what the
product demo wants, but it leaves the suites with nobody to play two roles
they need in order to prove isolation actually holds:

* **a peer with no exit case** — needed to show that opening your own case
  works, and that another employee gets 404 (not 403) on someone else's case.
  Every demo employee already has a case, so none can stand in.
* **a manager of another team** — needed to show a manager cannot read cases
  outside their own reports. With a single manager there is no "other team".

The alternative was to bend the demo roster around the tests, or to delete the
assertions. Both are worse: the first puts people on the dashboards who exist
only for testing, and the second quietly drops two real security properties.
So the suites create exactly the people they need and remove them afterwards.

These accounts never appear in the app during normal use — they exist only
while a suite is running. `ensure()` is idempotent and `remove()` is safe to
call on a database that has never seen them, so a crashed run self-heals the
next time a suite starts.
"""

from __future__ import annotations

PASSWORD = "ExitDemo!2026"

PEER = "qa.peer@example.com"
"""An employee with no exit case, reporting to Arjun."""

OTHER_MANAGER = "qa.other.manager@example.com"
"""A manager with no reports, standing in for a different team."""

SUBJECT = "qa.subject@example.com"
"""The employee the suite opens its test case on.

This used to be Kirthana. The suite deletes and recreates its subject's case
on every run, and deleting a case cascades to that person's documents — so
running the tests silently destroyed whatever had been uploaded in the demo.
A throwaway subject keeps the suite from touching data anyone is looking at.
"""

SUBJECT_NAME = "QA Subject"

_PEOPLE = [
    (PEER, "QA Peer", "QA-PEER", "Engineering", "Engineer II", "employee", True),
    (OTHER_MANAGER, "QA Other Manager", "QA-MGR", "Sales", "Sales Manager", "manager", False),
    (SUBJECT, SUBJECT_NAME, "QA-SUBJ", "Engineering", "Senior Engineer", "employee", True),
]

_INSTANCE = "00000000-0000-0000-0000-000000000000"


def ensure(conn) -> None:
    """Create the fixture accounts if they are not already there."""
    arjun = conn.execute(
        "select id from employees where work_email = %s", ("arjun.menon@example.com",)
    ).fetchone()
    if not arjun:
        raise SystemExit("Arjun Menon is missing — run apply_migrations.py --seed first.")

    for email, name, code, dept, title, role, reports_to_arjun in _PEOPLE:
        found = conn.execute("select id from auth.users where email = %s", (email,)).fetchone()
        if found:
            auth_id = found[0]
            conn.execute(
                "update auth.users set encrypted_password = crypt(%s, gen_salt('bf')), "
                "email_confirmed_at = coalesce(email_confirmed_at, now()) where id = %s",
                (PASSWORD, auth_id),
            )
        else:
            auth_id = conn.execute(
                """
                insert into auth.users (
                  instance_id, id, aud, role, email, encrypted_password,
                  email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
                  created_at, updated_at,
                  confirmation_token, email_change, email_change_token_new, recovery_token
                ) values (
                  %(instance)s::uuid, gen_random_uuid(), 'authenticated', 'authenticated',
                  %(email)s::text, crypt(%(password)s::text, gen_salt('bf')), now(),
                  '{"provider":"email","providers":["email"]}'::jsonb,
                  jsonb_build_object('full_name', %(name)s::text),
                  now(), now(), '', '', '', ''
                ) returning id
                """,
                {"instance": _INSTANCE, "email": email, "password": PASSWORD, "name": name},
            ).fetchone()[0]
            conn.execute(
                """
                insert into auth.identities (
                  id, user_id, provider_id, identity_data, provider,
                  last_sign_in_at, created_at, updated_at
                ) values (
                  gen_random_uuid(), %(auth_id)s::uuid, %(auth_id)s::text,
                  jsonb_build_object('sub', %(auth_id)s::text, 'email', %(email)s::text,
                                     'email_verified', true),
                  'email', now(), now(), now()
                )
                """,
                {"auth_id": auth_id, "email": email},
            )

        conn.execute(
            """
            insert into employees (
              auth_user_id, emp_code, full_name, work_email,
              department, designation, date_of_joining, manager_id, app_role
            ) values (
              %(auth_id)s, %(code)s, %(name)s, %(email)s,
              %(dept)s, %(title)s, date '2022-01-03', %(manager)s, %(role)s
            )
            on conflict (emp_code) do update set
              auth_user_id = excluded.auth_user_id,
              manager_id   = excluded.manager_id,
              app_role     = excluded.app_role
            """,
            {
                "auth_id": auth_id, "code": code, "name": name, "email": email,
                "dept": dept, "title": title, "role": role,
                "manager": arjun[0] if reports_to_arjun else None,
            },
        )

    conn.commit()


def remove(conn) -> None:
    """Delete the fixture accounts and anything they own."""
    emails = [p[0] for p in _PEOPLE]
    ids = [
        r[0]
        for r in conn.execute(
            "select id from employees where work_email = any(%s)", (emails,)
        ).fetchall()
    ]
    if ids:
        # exit_cases holds employee_id ON DELETE RESTRICT, and employee_profiles
        # blocks too, so both have to go before the employee row will.
        conn.execute("delete from audit_log where actor_id = any(%s)", (ids,))
        conn.execute("delete from exit_cases where employee_id = any(%s)", (ids,))
        conn.execute("delete from employee_profiles where employee_id = any(%s)", (ids,))
        conn.execute("delete from employees where id = any(%s)", (ids,))
    conn.execute("delete from auth.users where email = any(%s)", (emails,))
    conn.commit()
