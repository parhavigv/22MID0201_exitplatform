"""Fill in the exit interviews that were never submitted.

Why this is needed
------------------
Eleven cases have an interview record; three have answers. A trend agent
reading three responses cannot find a trend — and the one theme it did find
would look like a company-wide pattern on the strength of a single person
saying it.

The answers below are written to disagree with each other on purpose. Real exit
interviews do not all cite the same reason, and a seed where everyone says
"career progression" produces an analysis that is technically correct and
tells HR nothing. There are two people leaving over pay, two over progression,
one following a relocating partner, one for a career change, plus a retirement
and an end-of-contract — roughly the spread a small engineering org would see.

Some praise recurs across people (engineering autonomy, supportive managers)
and some criticism recurs (weekend releases, an unclear senior IC track),
because that repetition is the signal HR is actually looking for.

Sentiment, themes and summary are written here too. Normally the interview
summarizer agent produces those on submission; this backfills them so the data
is complete without eleven model calls.

The live path is untouched: an employee submitting through the app writes to
the same table and joins the same pool.

Re-running is safe — an interview already submitted is left alone.

Usage
-----
    cd backend
    .venv/Scripts/python.exe scripts/seed_exit_interviews.py
    .venv/Scripts/python.exe scripts/seed_exit_interviews.py --undo
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from app.deps import service_db  # noqa: E402

QUESTIONS = (
    "reason_for_leaving",
    "role_and_responsibilities",
    "manager_and_team",
    "growth_and_development",
    "compensation_and_benefits",
    "organisation_and_culture",
    "anything_else",
)

# email -> (sentiment, themes, summary, answers)
INTERVIEWS: dict[str, tuple[str, list[str], str, dict[str, str]]] = {
    "aditya.sharma@example.com": (
        "mixed",
        ["compensation below market", "limited mentoring for juniors", "liked the codebase"],
        "Early-career engineer leaving for a materially higher offer. Cites a "
        "40% gap rather than dissatisfaction. Praises code quality and review "
        "culture; the one gap is structured mentoring for people at their level.",
        {
            "reason_for_leaving": "I was offered around 40% more elsewhere. I wasn't looking, but at my stage that difference is hard to turn down.",
            "role_and_responsibilities": "Accurate to what I was hired for. I got real work early rather than being parked on documentation.",
            "manager_and_team": "Arjun was good with me. Code review was where I learnt the most.",
            "growth_and_development": "Learning came from reviews and from asking people. There was no structured mentoring for juniors — it worked because the team is kind, not because there was a system.",
            "compensation_and_benefits": "Below market for my level. That is the whole reason I am leaving.",
            "organisation_and_culture": "Keep the review culture, it is genuinely good. Revisit junior pay bands before more people get offers like mine.",
            "anything_else": "I would come back if the pay gap closed. No bad feeling at all.",
        },
    ),
    "nandini.reddy@example.com": (
        "mixed",
        ["career progression blocked", "title lagged scope", "strong team", "unclear IC track"],
        "Regretted attrition. Took a lead title elsewhere that was not available "
        "here on any stated timeline. Had been running the scope of a lead for "
        "roughly a year without the title or pay. Echoes the unclear senior IC "
        "track raised by others.",
        {
            "reason_for_leaving": "I have been doing lead-level work for about a year without the title. I asked twice about the path and got 'soon' both times, so I took a lead role elsewhere.",
            "role_and_responsibilities": "It grew well beyond the original description. That was fine while it was heading somewhere.",
            "manager_and_team": "Genuinely strong team, and I will miss them. Arjun advocated for me — I don't think this was his decision to make.",
            "growth_and_development": "Technically excellent. Structurally unclear. Nobody could tell me what the senior IC track actually looks like.",
            "compensation_and_benefits": "Fair for my title, low for my actual scope.",
            "organisation_and_culture": "Define the senior track and publish it. People are leaving to find out what their next step is.",
            "anything_else": "Please make sure my successor gets the title before the responsibility, not after.",
        },
    ),
    "farhan.qureshi@example.com": (
        "positive",
        ["career change", "strong technical autonomy", "planning churn", "long handover"],
        "Planned exit to move into academia after nine years — not prompted by "
        "anything at work. Consistently positive. The one recurring structural "
        "criticism is quarterly planning changing direction mid-cycle.",
        {
            "reason_for_leaving": "I am moving into teaching. It is a career change I have been considering for a couple of years, not a reaction to anything here.",
            "role_and_responsibilities": "The principal role was what I wanted and I was trusted to shape it.",
            "manager_and_team": "Excellent throughout. I was given room to make technical decisions and backed when they were unpopular.",
            "growth_and_development": "Nine years and I was still learning. Little to fault.",
            "compensation_and_benefits": "Reviewed properly and fairly.",
            "organisation_and_culture": "Keep the technical autonomy — it is the best thing about this place. The planning cycle changes direction mid-quarter too often and it wastes good work.",
            "anything_else": "Happy to stay available for architecture questions for a few months. I have given a long notice deliberately.",
        },
    ),
    "ishita.banerjee@example.com": (
        "negative",
        ["weekend releases", "burnout", "on-call load", "no QA headcount"],
        "Leaving over sustained workload rather than pay or progression. Names "
        "release slippage into weekends and being the only QA lead across three "
        "teams. The strongest signal in this set and the second person to raise "
        "weekend releases.",
        {
            "reason_for_leaving": "Burnout, honestly. I have been the only QA lead across three teams for eight months and every release seems to land on a Friday.",
            "role_and_responsibilities": "The role tripled without anyone deciding it should. I kept absorbing it because dropping it meant releases stopped.",
            "manager_and_team": "The team is good and nobody did this deliberately. It just was never anyone's job to stop it.",
            "growth_and_development": "There was no room for it. I spent the year keeping up.",
            "compensation_and_benefits": "Pay was not the problem.",
            "organisation_and_culture": "Stop releasing on Fridays. Hire a second QA before backfilling me, or whoever replaces me leaves the same way.",
            "anything_else": "I want to be clear this is about workload, not people. I would recommend the team to anyone if the staffing were fixed.",
        },
    ),
    "rohan.kulkarni@example.com": (
        "mixed",
        ["on-call load", "compensation below market", "weekend releases", "liked ownership"],
        "SRE leaving for a role with a larger platform team. Cites on-call "
        "carried by too few people and pay below market for the responsibility. "
        "Third person to mention weekend releases.",
        {
            "reason_for_leaving": "The new role has a platform team of twelve. Here on-call is three of us, and I have carried the pager most alternate weeks for two years.",
            "role_and_responsibilities": "I had genuine ownership of the infrastructure, which I valued.",
            "manager_and_team": "No complaints. The constraint was headcount, not management.",
            "growth_and_development": "I learnt a lot by necessity. Less by design.",
            "compensation_and_benefits": "Below market once you account for the on-call load. The allowance does not cover what it actually costs you.",
            "organisation_and_culture": "Either grow the on-call rota or reduce what is on it. Three people is not a rota, it is a rota-shaped problem.",
            "anything_else": "The runbooks are in good shape. My successor will be fine if the staffing is addressed.",
        },
    ),
    "divya.pillai@example.com": (
        "positive",
        ["relocation", "supportive manager", "flexible working", "slow data access"],
        "Leaving for family relocation, not dissatisfaction. Strongly positive "
        "about flexibility and management. Only operational criticism is how "
        "long data access takes for new joiners.",
        {
            "reason_for_leaving": "My partner is relocating to Pune and we decided to go together. I would have stayed otherwise.",
            "role_and_responsibilities": "Exactly as described and it grew sensibly.",
            "manager_and_team": "Very supportive, particularly around flexible hours when I needed them.",
            "growth_and_development": "Good. I moved from reporting into modelling work over two years.",
            "compensation_and_benefits": "Fair and reviewed on time.",
            "organisation_and_culture": "Keep the flexibility, it is why I stayed as long as I did. Data access for new joiners takes about three weeks and that is too slow.",
            "anything_else": "I would happily return if a remote arrangement ever became possible.",
        },
    ),
    "tanvi.mehta@example.com": (
        "negative",
        ["unclear senior IC track", "career progression blocked", "handover stalled"],
        "Left with the handover incomplete — case is on hold. Reports asking "
        "about progression three times without a clear answer. Fourth person to "
        "raise the senior IC track, which is now the most repeated structural "
        "theme in this set.",
        {
            "reason_for_leaving": "I asked about the path to senior three times over eighteen months and never got a straight answer. Eventually I stopped asking and started looking.",
            "role_and_responsibilities": "Fine, but static. I was doing the same work in year three as in year one.",
            "manager_and_team": "Team was good. I do not think my manager had the authority to answer what I was asking.",
            "growth_and_development": "This is the whole issue. There was no visible next step and no criteria for reaching one.",
            "compensation_and_benefits": "Acceptable. Not the reason.",
            "organisation_and_culture": "Write down what each level requires and let people see it. Right now progression looks like it depends on who notices you.",
            "anything_else": "I am sorry the handover is unfinished. I ran out of notice period.",
        },
    ),
    "kirthana.mekala@example.com": (
        "mixed",
        ["career progression blocked", "compensation below market", "strong engineering culture"],
        "Senior engineer leaving for a step up that was not available internally. "
        "Praises engineering standards and autonomy. Repeats both dominant themes "
        "in this set: progression clarity and pay relative to market.",
        {
            "reason_for_leaving": "A more senior role elsewhere, with a clearer scope than anything available here.",
            "role_and_responsibilities": "Matched the description. The work itself was good.",
            "manager_and_team": "Strong team, and Arjun was straightforward with me about what he could and could not influence.",
            "growth_and_development": "The engineering culture teaches you a lot. The career structure around it does not keep up.",
            "compensation_and_benefits": "Somewhat below market for a senior engineer in this city.",
            "organisation_and_culture": "Keep the code review standards and the autonomy. Fix the gap between how good the engineering is and how vague the progression is.",
            "anything_else": "The KT is documented. My successor should start with the billing reconciliation job.",
        },
    ),
}


def seed(undo: bool) -> int:
    db = service_db()

    employees = {
        e["work_email"]: e["id"]
        for e in db.table("employees").select("id, work_email").execute().data
    }
    case_for = {
        c["employee_id"]: c["id"]
        for c in db.table("exit_cases").select("id, employee_id").execute().data
    }

    if undo:
        removed = 0
        for email in INTERVIEWS:
            case_id = case_for.get(employees.get(email, ""))
            if not case_id:
                continue
            db.table("exit_interviews").update(
                {
                    "responses": {},
                    "submitted_at": None,
                    "sentiment": None,
                    "themes": None,
                    "summary": None,
                    "analysed_at": None,
                }
            ).eq("case_id", case_id).execute()
            removed += 1
        print(f"Cleared {removed} seeded interview(s).")
        return 0

    now = datetime.now(timezone.utc)
    written = 0

    for offset, (email, (sentiment, themes, summary, answers)) in enumerate(
        INTERVIEWS.items()
    ):
        case_id = case_for.get(employees.get(email, ""))
        if not case_id:
            print(f"  ? {email} has no case — skipped")
            continue

        existing = (
            db.table("exit_interviews")
            .select("submitted_at")
            .eq("case_id", case_id)
            .limit(1)
            .execute()
        )
        if existing.data and existing.data[0]["submitted_at"]:
            print(f"  = {email.split('@')[0]:<18} already submitted")
            continue

        missing = [q for q in QUESTIONS if q not in answers]
        if missing:
            print(f"  ! {email.split('@')[0]} is missing answers: {missing}")

        # Spread submission dates so "recent" means something on the trend panel.
        submitted = (now - timedelta(days=3 + offset * 4)).isoformat()

        db.table("exit_interviews").update(
            {
                "responses": answers,
                "submitted_at": submitted,
                "sentiment": sentiment,
                "themes": themes,
                "summary": summary,
                "analysed_at": submitted,
            }
        ).eq("case_id", case_id).execute()

        print(f"  + {email.split('@')[0]:<18}{sentiment:<10}{', '.join(themes[:2])}")
        written += 1

    print(f"\n{written} interview(s) written.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--undo", action="store_true", help="Clear the seeded answers.")
    args = parser.parse_args()
    raise SystemExit(seed(args.undo))
