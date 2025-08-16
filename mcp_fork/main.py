# from mcp.server.fastmcp import FastMCP
try:
    from mcp_fork.server.fastmcp import FastMCP
except ModuleNotFoundError:
    # Fallback: try local import if running from source
    from fastmcp import FastMCP
from typing import List

# --- Added for pg_dump/pg_restore tools ---
import subprocess
import os
from typing import Optional
import psycopg2


def _run_cmd(cmd: list[str], env: Optional[dict] = None, timeout: int = 600) -> str:
    """Run a command safely (no shell), capture stdout/stderr, and return a summary string."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or os.environ.copy(),
            timeout=timeout,
            check=False,
            text=True,
        )
        output = []
        output.append(f"$ {' '.join(cmd)}")
        if proc.stdout:
            output.append("--- stdout ---\n" + proc.stdout.strip())
        if proc.stderr:
            output.append("--- stderr ---\n" + proc.stderr.strip())
        output.append(f"exit_code={proc.returncode}")
        return "\n".join(output)
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s: {' '.join(cmd)}"
    except FileNotFoundError:
        return f"Command not found: {cmd[0]} (is it installed and on PATH?)"


# PostgreSQL integration

def get_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST"),
        port=os.environ.get("DB_PORT"),
        dbname=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("PGPASSWORD")
    )

# Utility: Disconnect all sessions to a database
def disconnect_all(dbname, user, host, password):
    conn = psycopg2.connect(dbname="postgres", user=user, host=host, password=password)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("""
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = %s AND pid <> pg_backend_pid();
        """, (dbname,))
    conn.close()
#safe_dname before dropping database
import re

def safe_dbname(name):
    if re.match(r'^[A-Za-z0-9_]+$', name):
        return name
    raise ValueError("Invalid database name")

# Utility: Drop a database if exists
def drop_database(dbname, user, host, password):
    conn = psycopg2.connect(dbname="postgres", user=user, host=host, password=password)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{dbname}";')
    conn.close()

# Create MCP server
mcp = FastMCP("LeaveManager")

# Tool: Check Leave Balance
@mcp.tool()
def get_leave_balance(employee_id: str) -> str:
    """Check how many leave days are left for the employee"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM employee_leaves WHERE emp_id = %s", (employee_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return f"{employee_id} has {row[0]} leave days remaining."
        return "Employee ID not found."
    except Exception as e:
        return f"Database error: {e}"

# Tool: Apply for Leave
@mcp.tool()
def apply_leave(employee_id: str, leave_dates: List[str]) -> str:
    """Apply leave for specific dates"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM employee_leaves WHERE emp_id = %s", (employee_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return "Employee ID not found."
        available_balance = row[0]
        requested_days = len(leave_dates)
        if available_balance < requested_days:
            cur.close()
            conn.close()
            return f"Insufficient leave balance. You requested {requested_days} day(s) but have only {available_balance}."
        new_balance = available_balance - requested_days
        cur.execute("UPDATE employee_leaves SET balance = %s WHERE emp_id = %s", (new_balance, employee_id))
        for date in leave_dates:
            cur.execute(
                "INSERT INTO leave_history (emp_id, leave_date) VALUES (%s, %s)",
                (employee_id, date)
            )
        conn.commit()
        cur.close()
        conn.close()
        return f"Leave applied for {requested_days} day(s). Remaining balance: {new_balance}."
    except Exception as e:
        return f"Database error: {e}"

# Tool: Leave history
@mcp.tool()
def get_leave_history(employee_id: str) -> str:
    """Get leave history for the employee"""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT leave_date FROM leave_history WHERE emp_id = %s ORDER BY leave_date", (employee_id,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        if rows:
            history = ', '.join(row[0].strftime("%Y-%m-%d") for row in rows)
            return f"Leave history for {employee_id}: {history}"
        else:
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM employee_leaves WHERE emp_id = %s", (employee_id,))
            exists = cur.fetchone()
            cur.close()
            conn.close()
            if exists:
                return f"Leave history for {employee_id}: No leaves taken."
            else:
                return "Employee ID not found."
    except Exception as e:
        return f"Database error: {e}"

# Tool: pg_dump
PG_DUMP_PATH = "C:\\Program Files\\PostgreSQL\\17\\bin\\pg_dump.exe"

@mcp.tool()
def pg_dump_tool(dbname: str, output_file: str, fmt: str = "t") -> str:
    """Run pg_dump to back up a database"""
    try:
        cmd = [PG_DUMP_PATH, "-F", fmt, "-f", output_file, dbname]
        subprocess.run(cmd, check=True)
        return f"Backup completed: {output_file}"
    except subprocess.CalledProcessError as e:
        return f"pg_dump failed: {e}"

# Tool: pg_restore with auto disconnect + drop
#PG_RESTORE_PATH = "/Applications/Postgres.app/Contents/Versions/latest/bin/pg_restore"

PG_RESTORE_PATH = "C:\\Program Files\\PostgreSQL\\17\\bin\\pg_restore.exe"

@mcp.tool()
def pg_restore_tool(
    archive_file: str,
    target_db: str,
    user: str = "postgres",
    host: str = "localhost",
    port: int = 5432,
    clean: bool = False,
    create: bool = False,
    verbose: bool = True,
    password: str = "",
    auto_drop: bool = True,
    extra_args: List[str] = [],
) -> str:
    """
    Restore a PostgreSQL database from an archive.
    Optionally disconnects users and drops the DB first if create=True.
    """
    try:
        if auto_drop and create:
            disconnect_all(target_db, user, host, password)
            drop_database(target_db, user, host, password)

        cmd = [PG_RESTORE_PATH, "-h", host, "-p", str(port), "-U", user]
        if clean:
            cmd.append("--clean")
        if create:
            cmd.append("-C")
        if verbose:
            cmd.append("-v")
        cmd.extend(["-d", target_db, archive_file])
        if extra_args:
            cmd.extend(extra_args)

        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        return _run_cmd(cmd, env=env)
    except Exception as e:
        return f"Restore error: {e}"


# Resource: Greeting
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}! How can I assist you with leave management today?"

if __name__ == "__main__":
    mcp.run()
