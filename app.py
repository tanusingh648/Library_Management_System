import streamlit as st
import sqlite3
import pandas as pd
from datetime import date, timedelta
from pathlib import Path

st.set_page_config(
    page_title="Library Management System",
    page_icon="📚",
    layout="wide"
)

DB_PATH = Path("/content/library.db")

# Connect to the same SQLite database used in Colab
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# Create tables if they do not already exist
with get_connection() as conn:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS Books (
        book_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL,
        category TEXT,
        total_copies INTEGER NOT NULL,
        available_copies INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS Members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE
    );

    CREATE TABLE IF NOT EXISTS Loans (
        loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        book_id INTEGER NOT NULL,
        member_id INTEGER NOT NULL,
        issue_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        return_date TEXT,
        FOREIGN KEY(book_id) REFERENCES Books(book_id),
        FOREIGN KEY(member_id) REFERENCES Members(member_id)
    );
    """)

st.title("📚 Library Management System")
st.caption("Manage books, members, borrowing, and returns in one place.")

# Sidebar navigation
page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Manage Books",
        "Manage Members",
        "Issue Book",
        "Return Book",
        "Loan History"
    ]
)

def read_data(query, params=()):
    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)

# ---------------- DASHBOARD ----------------
if page == "Dashboard":
    books = read_data("SELECT * FROM Books")
    members = read_data("SELECT * FROM Members")
    loans = read_data("SELECT * FROM Loans")

    total_titles = len(books)
    total_copies = int(books["total_copies"].sum()) if not books.empty else 0
    available = int(books["available_copies"].sum()) if not books.empty else 0
    active_loans = int(loans["return_date"].isna().sum()) if not loans.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Book Titles", total_titles)
    c2.metric("Total Copies", total_copies)
    c3.metric("Available Copies", available)
    c4.metric("Registered Members", len(members))

    st.subheader("Currently Issued Books")
    st.metric("Active Loans", active_loans)

    if not books.empty:
        st.subheader("Book Inventory")
        st.dataframe(books, use_container_width=True, hide_index=True)

# ---------------- MANAGE BOOKS ----------------
elif page == "Manage Books":
    st.subheader("Add a New Book")

    with st.form("add_book_form"):
        title = st.text_input("Book Title")
        author = st.text_input("Author")
        category = st.text_input("Category")
        copies = st.number_input("Number of Copies", min_value=1, value=1, step=1)
        submitted = st.form_submit_button("Add Book")

        if submitted:
            if not title.strip() or not author.strip():
                st.error("Title and author are required.")
            else:
                with get_connection() as conn:
                    conn.execute("""
                        INSERT INTO Books
                        (title, author, category, total_copies, available_copies)
                        VALUES (?, ?, ?, ?, ?)
                    """, (title.strip(), author.strip(), category.strip(),
                          int(copies), int(copies)))
                st.success("Book added successfully!")
                st.rerun()

    st.subheader("Search and View Books")
    keyword = st.text_input("Search by title, author, or category")

    books = read_data("""
        SELECT * FROM Books
        WHERE title LIKE ? OR author LIKE ? OR category LIKE ?
        ORDER BY book_id
    """, (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"))

    st.dataframe(books, use_container_width=True, hide_index=True)

# ---------------- MANAGE MEMBERS ----------------
elif page == "Manage Members":
    st.subheader("Register a Member")

    with st.form("member_form"):
        name = st.text_input("Member Name")
        email = st.text_input("Email Address")
        submitted = st.form_submit_button("Register Member")

        if submitted:
            if not name.strip() or not email.strip():
                st.error("Name and email are required.")
            else:
                try:
                    with get_connection() as conn:
                        conn.execute("""
                            INSERT INTO Members (name, email)
                            VALUES (?, ?)
                        """, (name.strip(), email.strip()))
                    st.success("Member registered successfully!")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("This email is already registered.")

    st.subheader("Registered Members")
    members = read_data("SELECT * FROM Members ORDER BY member_id")
    st.dataframe(members, use_container_width=True, hide_index=True)

# ---------------- ISSUE BOOK ----------------
elif page == "Issue Book":
    st.subheader("Issue a Book")

    books = read_data("""
        SELECT book_id, title, available_copies
        FROM Books WHERE available_copies > 0
    """)
    members = read_data("SELECT member_id, name, email FROM Members")

    if books.empty:
        st.warning("No books are currently available.")
    elif members.empty:
        st.warning("Register a member before issuing a book.")
    else:
        book_options = {
            f"{r.title} (Available: {r.available_copies}) — ID {r.book_id}":
            int(r.book_id)
            for r in books.itertuples()
        }
        member_options = {
            f"{r.name} — ID {r.member_id}":
            int(r.member_id)
            for r in members.itertuples()
        }

        with st.form("issue_form"):
            selected_book = st.selectbox("Select Book", list(book_options))
            selected_member = st.selectbox("Select Member", list(member_options))
            submitted = st.form_submit_button("Issue Book")

            if submitted:
                today = date.today()
                due = today + timedelta(days=14)

                with get_connection() as conn:
                    cursor = conn.execute("""
                        UPDATE Books
                        SET available_copies = available_copies - 1
                        WHERE book_id = ? AND available_copies > 0
                    """, (book_options[selected_book],))

                    if cursor.rowcount == 1:
                        conn.execute("""
                            INSERT INTO Loans
                            (book_id, member_id, issue_date, due_date)
                            VALUES (?, ?, ?, ?)
                        """, (
                            book_options[selected_book],
                            member_options[selected_member],
                            str(today),
                            str(due)
                        ))
                        st.success(f"Book issued! Return by {due}.")
                    else:
                        st.error("No copies are available.")

# ---------------- RETURN BOOK ----------------
elif page == "Return Book":
    st.subheader("Return a Book")

    loans = read_data("""
        SELECT l.loan_id, b.title, m.name, l.issue_date, l.due_date
        FROM Loans l
        JOIN Books b ON l.book_id = b.book_id
        JOIN Members m ON l.member_id = m.member_id
        WHERE l.return_date IS NULL
        ORDER BY l.due_date
    """)

    if loans.empty:
        st.info("There are no outstanding loans.")
    else:
        st.dataframe(loans, use_container_width=True, hide_index=True)

        loan_ids = loans["loan_id"].tolist()
        selected_loan = st.selectbox("Select Loan ID to Return", loan_ids)

        if st.button("Confirm Return"):
            with get_connection() as conn:
                loan = conn.execute("""
                    SELECT book_id, due_date
                    FROM Loans
                    WHERE loan_id = ? AND return_date IS NULL
                """, (selected_loan,)).fetchone()

                if loan:
                    book_id, due_date = loan
                    today = date.today()
                    overdue_days = max(
                        0, (today - date.fromisoformat(due_date)).days
                    )
                    fine = overdue_days * 5

                    conn.execute("""
                        UPDATE Loans SET return_date = ?
                        WHERE loan_id = ? AND return_date IS NULL
                    """, (str(today), selected_loan))

                    conn.execute("""
                        UPDATE Books
                        SET available_copies = available_copies + 1
                        WHERE book_id = ?
                    """, (book_id,))

                    st.success("Book returned successfully!")
                    st.write(f"Overdue days: {overdue_days}")
                    st.write(f"Fine due: ₹{fine}")
                else:
                    st.error("This loan has already been returned.")

# ---------------- LOAN HISTORY ----------------
elif page == "Loan History":
    st.subheader("Borrowing History")

    history = read_data("""
        SELECT
            l.loan_id,
            b.title AS book_title,
            m.name AS member_name,
            l.issue_date,
            l.due_date,
            l.return_date,
            CASE
                WHEN l.return_date IS NOT NULL THEN 'Returned'
                WHEN l.due_date < date('now') THEN 'Overdue'
                ELSE 'Issued'
            END AS status
        FROM Loans l
        JOIN Books b ON l.book_id = b.book_id
        JOIN Members m ON l.member_id = m.member_id
        ORDER BY l.loan_id DESC
    """)

    st.dataframe(history, use_container_width=True, hide_index=True)

st.sidebar.divider()
st.sidebar.caption("Library Management System | Python + SQLite")
