"""
app.py - WhatsApp "Smart Deadlines" prototype (Streamlit).

Run:  streamlit run app.py

This simulates a feature that would live INSIDE WhatsApp. It uses a fake inbox
(sample groups + messages) instead of real chats.
"""
import html
from datetime import datetime, timedelta

import streamlit as st

from detector import extract_deadline, similarity, content_words

st.set_page_config(page_title="WhatsApp + Deadlines", page_icon="💬", layout="centered")

GREEN = "#128C7E"
st.markdown(
    f"""
    <style>
      h1, h2, h3 {{ color: {GREEN}; }}
      .card {{ border-left: 6px solid #25D366; background: #f4fbf7; padding: 10px 14px;
               border-radius: 8px; margin-bottom: 10px; }}
      .card.urgent {{ border-left-color: #e53935; background: #fdf1f0; }}
      .card.soon {{ border-left-color: #fb8c00; background: #fff6ea; }}
      .card.done {{ opacity: 0.5; }}
      .meta {{ color: #667781; font-size: 0.85rem; }}
      .msg {{ background: #e7ffdb; padding: 6px 10px; border-radius: 8px; margin: 4px 0; }}
      .msg.hit {{ border: 2px solid #25D366; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------- Sample inbox (dates are relative so the demo always works) ----------
def build_sample_inbox(now: datetime) -> dict:
    def d(days):
        return (now + timedelta(days=days)).strftime("%d %B")

    return {
        "DBMS Class 2026": [
            ("Priya", "Hey everyone! Please submit the DBMS record by Monday 5 pm."),
            ("Rohan", "Lab was fun today haha"),
            ("Ananya", "Assignment 3 due on " + d(4) + ". Upload here: https://example.com/upload"),
        ],
        "IEEE WIE VIT": [
            ("Core Team", "Event registration closes on " + d(6) + " 11 pm, don't forget!"),
            ("Meera", "Who's coming for the workshop??"),
        ],
        "Hostel Block C": [
            ("Warden", "Reminder: pay the hostel fee before " + d(11) + "."),
            ("Karan", "Anyone up for biryani tonight?"),
            ("Sana", "Lights out at 11 so keep it down lol"),
        ],
        "Project Team": [
            ("Aarav", "Final project report by tomorrow 11:59 pm, please!"),
            ("Priya", "Meeting at the library, see you all there"),
        ],
        "College Friends": [
            ("Rohan", "That movie last night was soooo good"),
            ("Neha", "Assignment due on " + d(5) + ", start early guys"),
        ],
        "Family": [
            ("Mom", "Did you eat dinner?"),
            ("Dad", "Call me when you are free beta"),
        ],
    }


# ---------- Session state ----------
if "now" not in st.session_state:
    st.session_state.now = datetime.now()
if "inbox" not in st.session_state:
    st.session_state.inbox = build_sample_inbox(st.session_state.now)
if "deadlines" not in st.session_state:
    st.session_state.deadlines = []  # list of dicts
    st.session_state.scanned = set()


def process_message(group: str, sender: str, text: str):
    """Runs on every message (the 'on-device detection' step)."""
    found = extract_deadline(text, st.session_state.now)
    if not found:
        return None

    # Is this about a task we already have in this group? (same task restated, new date)
    same_group = [x for x in st.session_state.deadlines if x["group"] == group]
    best, best_score = None, 0.0
    for x in same_group:
        score = similarity(text, x["original"])
        if score > best_score:
            best, best_score = x, score

    target = None
    if found["is_update"]:
        # "deadline extended to Friday": best match, else most recent in the group
        target = best if best_score >= 0.3 else (same_group[-1] if same_group else None)
    elif best is not None and best_score >= 0.6:
        # "hostel mess review due on 21st" after "...due on 23rd": same task, new date
        target = best

    if target is not None:
        target["due"] = found["due"]
        if content_words(text):  # message names the task -> refresh the heading too
            target["title"] = found["title"]
        target["original"] = text
        target["updated"] = True
        target["done"] = False
        return "updated"

    st.session_state.deadlines.append(
        {
            "title": found["title"],
            "due": found["due"],
            "group": group,
            "sender": sender,
            "link": found["link"],
            "original": text,
            "done": False,
            "updated": False,
        }
    )
    return "new"


# Scan the sample inbox once
for grp, msgs in st.session_state.inbox.items():
    for i, (sender, text) in enumerate(msgs):
        key = (grp, i)
        if key not in st.session_state.scanned:
            st.session_state.scanned.add(key)
            process_message(grp, sender, text)


def days_left(due: datetime):
    delta = due - st.session_state.now
    return delta


def label_for(due: datetime) -> str:
    delta = days_left(due)
    if delta.total_seconds() < 0:
        return "Overdue"
    if due.date() == st.session_state.now.date():
        return "Due today"
    days = (due.date() - st.session_state.now.date()).days
    if days == 1:
        return "Due tomorrow"
    return f"{days} days left"


# ---------- Sidebar: simulate a new message ----------
with st.sidebar:
    st.header("📩 Simulate a new message")
    st.caption("Type a message as if it just arrived in a group.")
    group_choice = st.selectbox("Group", list(st.session_state.inbox.keys()))
    sender = st.text_input("Sender", value="Priya")
    new_text = st.text_area("Message", placeholder="Submit the OS record by Friday 6 pm")
    if st.button("Send message", type="primary"):
        if new_text.strip():
            idx = len(st.session_state.inbox[group_choice])
            st.session_state.inbox[group_choice].append((sender, new_text.strip()))
            st.session_state.scanned.add((group_choice, idx))
            result = process_message(group_choice, sender, new_text.strip())
            if result == "new":
                st.success("📌 Deadline detected and added!")
            elif result == "updated":
                st.success("🔄 Existing deadline updated!")
            else:
                st.info("No deadline found in this message.")
    st.divider()
    st.caption("Try: 'Deadline extended to next Friday' in DBMS Class 2026 to see an entry update.")

# ---------- Main ----------
st.title("💬 WhatsApp + Deadlines")
tab_deadlines, tab_chats = st.tabs(["📌 Deadlines", "💬 Chats"])

with tab_deadlines:
    active = sorted(
        [x for x in st.session_state.deadlines if not x["done"]], key=lambda x: x["due"]
    )

    # Reminder banner: anything due within 24 hours
    soon = [x for x in active if timedelta(0) <= days_left(x["due"]) <= timedelta(hours=24)]
    if soon:
        names = ", ".join(x["title"][:30] for x in soon)
        st.warning(f"⏰ Reminder: {len(soon)} deadline(s) due within 24 hours: {names}")

    st.caption(f"{len(active)} upcoming deadlines found across {len(st.session_state.inbox)} chats")

    sections = {"Due today / tomorrow": [], "This week": [], "Later": []}
    overdue = []
    for item in active:
        delta = days_left(item["due"])
        days = (item["due"].date() - st.session_state.now.date()).days
        if delta.total_seconds() < 0:
            overdue.append(item)
        elif days <= 1:
            sections["Due today / tomorrow"].append(item)
        elif days <= 7:
            sections["This week"].append(item)
        else:
            sections["Later"].append(item)
    if overdue:
        sections = {"Overdue": overdue, **sections}

    for title, items in sections.items():
        if not items:
            continue
        st.subheader(title)
        for item in items:
            days = (item["due"].date() - st.session_state.now.date()).days
            css = "urgent" if days <= 1 else "soon" if days <= 3 else ""
            updated_tag = " 🔄 updated" if item["updated"] else ""
            link_html = f' · <a href="{html.escape(item["link"])}">link</a>' if item["link"] else ""
            st.markdown(
                f"""<div class="card {css}">
                <b>{html.escape(item["title"])}</b>{updated_tag}<br>
                <span class="meta">{html.escape(item["group"])} · {item["due"].strftime("%a, %d %b %Y, %I:%M %p")}
                · <b>{label_for(item["due"])}</b>{link_html}</span>
                </div>""",
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns([1, 1])
            with c1:
                if st.button("✅ Mark complete", key=f"done-{id(item)}"):
                    item["done"] = True
                    st.rerun()
            with c2:
                with st.expander("Original message"):
                    st.write(f"**{item['sender']}** in *{item['group']}*:")
                    st.write(item["original"])

    completed = [x for x in st.session_state.deadlines if x["done"]]
    if completed:
        with st.expander(f"Completed ({len(completed)})"):
            for x in completed:
                st.write("✅ " + x["title"])

with tab_chats:
    st.caption("Messages tagged 📌 were picked up by the deadline detector. Everything else is ignored.")
    for grp, msgs in st.session_state.inbox.items():
        with st.expander(f"{grp} ({len(msgs)} messages)"):
            for sender_name, text in msgs:
                hit = extract_deadline(text, st.session_state.now) is not None
                tag = "📌 " if hit else ""
                cls = "msg hit" if hit else "msg"
                st.markdown(
                    f'<div class="{cls}"><b>{html.escape(sender_name)}</b>: {tag}{html.escape(text)}</div>',
                    unsafe_allow_html=True,
                )

st.divider()
st.caption(
    "Prototype note: in the real WhatsApp feature, detection, storage and reminders would run "
    "on-device to keep end-to-end encryption intact. This demo uses a sample inbox."
)
