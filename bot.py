import discord
from discord.ext import commands
import asyncio
import subprocess
import json
from datetime import datetime, timedelta
import shlex
import logging
import shutil
import os
from typing import Optional, List, Dict, Any
import threading
import time
import sqlite3
import random
import requests
import string
import secrets
from dotenv import load_dotenv
import re
import paramiko
from flask import Flask, render_template, request, jsonify
from flask_cors import CORS

# Load environment variables from .env file
load_dotenv()

# Load environment variables
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
BOT_NAME = os.getenv('BOT_NAME', 'SVM V10')
PREFIX = os.getenv('PREFIX', '!')
YOUR_SERVER_IP = os.getenv('YOUR_SERVER_IP', '127.0.0.1')
MAIN_ADMIN_ID = int(os.getenv('MAIN_ADMIN_ID', '1210291131301101618'))
VPS_USER_ROLE_ID = int(os.getenv('VPS_USER_ROLE_ID', '1210291131301101618'))
DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', 'default')
HOST_MOTD = os.getenv('HOST_MOTD', 'bash <(curl -fsSL https://raw.githubusercontent.com/ankitcoder/linux/main/atyro-water-mark.sh)')
BOT_VERSION = os.getenv('BOT_VERSION', '11.2-PRO')
BOT_DEVELOPER = os.getenv('BOT_DEVELOPER', 'AnkitCoder')
BOT_THUMBNAIL_URL = 'https://i.postimg.cc/XYsyy94s/file-000000008e748211ae382f76fb5cd51b.png'
BOT_ICON_URL = 'https://i.postimg.cc/XYsyy94s/file-000000008e748211ae382f76fb5cd51b.png'

# VPS Expiration Settings
DEFAULT_VPS_EXPIRATION_DAYS = int(os.getenv('DEFAULT_VPS_EXPIRATION_DAYS', '30'))
EXPIRATION_WARNING_DAYS = int(os.getenv('EXPIRATION_WARNING_DAYS', '1'))

# Public VPS Creation Settings
PUBLIC_VPS_ENABLED = os.getenv('PUBLIC_VPS_ENABLED', 'true').lower() == 'true'
PUBLIC_VPS_MAX_RAM = int(os.getenv('PUBLIC_VPS_MAX_RAM', '4'))
PUBLIC_VPS_MAX_CPU = int(os.getenv('PUBLIC_VPS_MAX_CPU', '2'))
PUBLIC_VPS_MAX_DISK = int(os.getenv('PUBLIC_VPS_MAX_DISK', '50'))
PUBLIC_VPS_EXPIRY_DAYS = int(os.getenv('PUBLIC_VPS_EXPIRY_DAYS', '30'))
PUBLIC_VPS_MAX_PER_USER = int(os.getenv('PUBLIC_VPS_MAX_PER_USER', '1'))
PUBLIC_VPS_MAX_PER_IP = int(os.getenv('PUBLIC_VPS_MAX_PER_IP', '3'))
PUBLIC_VPS_REQUIRE_VERIFICATION = os.getenv('PUBLIC_VPS_REQUIRE_VERIFICATION', 'false').lower() == 'true'

# Public VPS Renewal Settings
PUBLIC_VPS_RENEWAL_ENABLED = os.getenv('PUBLIC_VPS_RENEWAL_ENABLED', 'true').lower() == 'true'
PUBLIC_VPS_RENEWAL_DAYS = int(os.getenv('PUBLIC_VPS_RENEWAL_DAYS', '30'))

# Web SSH Terminal Settings
WEBSSH_ENABLED = os.getenv('WEBSSH_ENABLED', 'true').lower() == 'true'
WEBSSH_PORT = int(os.getenv('WEBSSH_PORT', '5000'))
WEBSSH_SERVER_IP = os.getenv('WEBSSH_SERVER_IP', '127.0.0.1')
WEBSSH_URL_FORMAT = os.getenv('WEBSSH_URL_FORMAT', 'http://{SERVER_IP}:{PORT}')

# SSH Configuration
SSH_FIX_SCRIPT = """#!/bin/bash
cat > /etc/ssh/sshd_config << 'SSHEOF'
Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
SyslogFacility AUTH
LogLevel INFO
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
PermitUserEnvironment no
Subsystem sftp /usr/lib/openssh/sftp-server
SSHEOF
systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true
"""

# OS Options for VPS Creation and Reinstall
OS_OPTIONS = [
    {"label": "Ubuntu 20.04 LTS", "value": "ubuntu:20.04"},
    {"label": "Ubuntu 22.04 LTS", "value": "ubuntu:22.04"},
    {"label": "Ubuntu 24.04 LTS", "value": "ubuntu:24.04"},
    {"label": "Debian 10 (Buster)", "value": "images:debian/10"},
    {"label": "Debian 11 (Bullseye)", "value": "images:debian/11"},
    {"label": "Debian 12 (Bookworm)", "value": "images:debian/12"},
    {"label": "Debian 13 (Trixie)", "value": "images:debian/13"},
]

# Configure logging to file and console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(f'{BOT_NAME.lower()}_vps_bot')

# ═══════════════════════════════════════════════════════════════════════════
# ROBUST SQLITE DATABASE SYSTEM - PERSISTENT + CRASH SAFE + SILENT SAVES
# ═══════════════════════════════════════════════════════════════════════════

import atexit
from pathlib import Path

# Always keep the database beside this Python file.
# This prevents a restart from another working directory creating a new vps.db.
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = str(BASE_DIR / "vps.db")
DB_BACKUP_DIR = BASE_DIR / "db_backups"
DB_LOCK = threading.RLock()

DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    """Open a reliable SQLite connection for persistent bot data."""
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row

    # WAL is configured once during init_db(). These settings are safe
    # for concurrent reads and writes and avoid unnecessary lock errors.
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA wal_autocheckpoint=1000")
    return conn


def backup_database():
    """Create a consistent SQLite backup without noisy console output."""
    try:
        if not os.path.exists(DB_FILE):
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = DB_BACKUP_DIR / f"vps_backup_{timestamp}.db"

        with DB_LOCK:
            source = get_db()
            try:
                destination = sqlite3.connect(str(backup_path))
                try:
                    source.backup(destination)
                finally:
                    destination.close()
            finally:
                source.close()

        backups = sorted(DB_BACKUP_DIR.glob("vps_backup_*.db"))
        for old_backup in backups[:-10]:
            try:
                old_backup.unlink()
            except OSError:
                pass
    except Exception as e:
        logger.error(f"Database backup failed: {e}")


def init_db():
    """Create/migrate every persistent table and verify database integrity."""
    with DB_LOCK:
        conn = get_db()
        try:
            # Configure WAL once instead of running journal_mode=WAL on every
            # connection. Repeated journal changes can cause lock errors.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")

            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                    user_id TEXT PRIMARY KEY,
                    added_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute(
                "INSERT OR IGNORE INTO admins (user_id) VALUES (?)",
                (str(MAIN_ADMIN_ID),),
            )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    location TEXT,
                    total_vps INTEGER,
                    tags TEXT DEFAULT '[]',
                    api_key TEXT,
                    url TEXT,
                    is_local INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Make sure a local node always exists.
            cur.execute("SELECT id FROM nodes WHERE is_local = 1 ORDER BY id LIMIT 1")
            if cur.fetchone() is None:
                cur.execute("""
                    INSERT INTO nodes
                    (name, location, total_vps, tags, api_key, url, is_local)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("Local Node", "Local", 100, "[]", None, None, 1))

            cur.execute("""
                CREATE TABLE IF NOT EXISTS vps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    node_id INTEGER NOT NULL DEFAULT 1,
                    container_name TEXT UNIQUE NOT NULL,
                    ram TEXT NOT NULL,
                    cpu TEXT NOT NULL,
                    storage TEXT NOT NULL,
                    config TEXT NOT NULL,
                    os_version TEXT DEFAULT 'ubuntu:22.04',
                    status TEXT DEFAULT 'stopped',
                    suspended INTEGER DEFAULT 0,
                    whitelisted INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    shared_with TEXT DEFAULT '[]',
                    suspension_history TEXT DEFAULT '[]',
                    expiration_date TEXT DEFAULT NULL,
                    root_password TEXT DEFAULT NULL,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (node_id) REFERENCES nodes(id)
                )
            """)

            # Safe migrations for databases created by older bot versions.
            cur.execute("PRAGMA table_info(vps)")
            columns = {row[1] for row in cur.fetchall()}
            migrations = [
                ("os_version", "ALTER TABLE vps ADD COLUMN os_version TEXT DEFAULT 'ubuntu:22.04'"),
                ("node_id", "ALTER TABLE vps ADD COLUMN node_id INTEGER DEFAULT 1"),
                ("expiration_date", "ALTER TABLE vps ADD COLUMN expiration_date TEXT DEFAULT NULL"),
                ("root_password", "ALTER TABLE vps ADD COLUMN root_password TEXT DEFAULT NULL"),
                ("last_modified", "ALTER TABLE vps ADD COLUMN last_modified TEXT DEFAULT CURRENT_TIMESTAMP"),
            ]
            for col_name, migration_sql in migrations:
                if col_name not in columns:
                    try:
                        cur.execute(migration_sql)
                    except sqlite3.OperationalError:
                        pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for key, value in (("cpu_threshold", "90"), ("ram_threshold", "90")):
                cur.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                    (key, value),
                )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS port_allocations (
                    user_id TEXT PRIMARY KEY,
                    allocated_ports INTEGER DEFAULT 0,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS port_forwards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    vps_container TEXT NOT NULL,
                    vps_port INTEGER NOT NULL,
                    host_port INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    last_modified TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create table for fraud detection - track user IPs and device fingerprints
            cur.execute("""
                CREATE TABLE IF NOT EXISTS user_device_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    ip_address TEXT,
                    device_fingerprint TEXT,
                    username TEXT,
                    avatar_hash TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
                    vps_created INTEGER DEFAULT 0
                )
            """)
            
            # Index for faster lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_device_ip ON user_device_tracking(ip_address)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_device_fingerprint ON user_device_tracking(device_fingerprint)
            """)

            # Repair old node tag values that may have been double-encoded.
            cur.execute("SELECT id, tags FROM nodes")
            for row in cur.fetchall():
                raw = row["tags"]
                try:
                    parsed = json.loads(raw or "[]")
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    if not isinstance(parsed, list):
                        parsed = []
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = []
                cur.execute(
                    "UPDATE nodes SET tags = ? WHERE id = ?",
                    (json.dumps(parsed), row["id"]),
                )

            conn.commit()

            # SQLite integrity check. This does not modify user data.
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(
                    f"SQLite integrity check failed: {integrity}"
                )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_setting(key: str, default: Any = None):
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default
        finally:
            conn.close()


def set_setting(key: str, value: str):
    with DB_LOCK:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO settings (key, value, last_modified)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    last_modified = CURRENT_TIMESTAMP
            """, (key, value))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_nodes() -> List[Dict]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
            nodes = []
            for row in rows:
                node = dict(row)
                try:
                    tags = json.loads(node.get("tags") or "[]")
                    if isinstance(tags, str):
                        tags = json.loads(tags)
                    node["tags"] = tags if isinstance(tags, list) else []
                except (TypeError, ValueError, json.JSONDecodeError):
                    node["tags"] = []
                node["is_local"] = int(node.get("is_local", 1)) == 1
                nodes.append(node)
            return nodes
        finally:
            conn.close()


def get_node(node_id: int) -> Optional[Dict]:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if not row:
                return None
            node = dict(row)
            try:
                tags = json.loads(node.get("tags") or "[]")
                if isinstance(tags, str):
                    tags = json.loads(tags)
                node["tags"] = tags if isinstance(tags, list) else []
            except (TypeError, ValueError, json.JSONDecodeError):
                node["tags"] = []
            node["is_local"] = int(node.get("is_local", 1)) == 1
            return node
        finally:
            conn.close()


def _decode_vps_row(row) -> Dict[str, Any]:
    vps = dict(row)
    try:
        vps["shared_with"] = json.loads(vps.get("shared_with") or "[]")
        if not isinstance(vps["shared_with"], list):
            vps["shared_with"] = []
    except (TypeError, ValueError, json.JSONDecodeError):
        vps["shared_with"] = []

    try:
        vps["suspension_history"] = json.loads(
            vps.get("suspension_history") or "[]"
        )
        if not isinstance(vps["suspension_history"], list):
            vps["suspension_history"] = []
    except (TypeError, ValueError, json.JSONDecodeError):
        vps["suspension_history"] = []

    vps["suspended"] = bool(vps.get("suspended", 0))
    vps["whitelisted"] = bool(vps.get("whitelisted", 0))
    vps["os_version"] = vps.get("os_version") or "ubuntu:22.04"
    return vps


def get_vps_by_id(vps_id: int) -> Optional[Dict]:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM vps WHERE id = ?", (vps_id,)
            ).fetchone()
            return _decode_vps_row(row) if row else None
        finally:
            conn.close()


def get_current_vps_count(node_id: int) -> int:
    with DB_LOCK:
        conn = get_db()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM vps WHERE node_id = ?", (node_id,)
            ).fetchone()[0]
        finally:
            conn.close()


def get_vps_data() -> Dict[str, List[Dict[str, Any]]]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute("SELECT * FROM vps ORDER BY id").fetchall()
            data: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                vps = _decode_vps_row(row)
                user_id = str(vps["user_id"])
                data.setdefault(user_id, []).append(vps)
            return data
        finally:
            conn.close()


def get_admins() -> List[str]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT user_id FROM admins ORDER BY user_id"
            ).fetchall()
            return [str(row["user_id"]) for row in rows]
        finally:
            conn.close()


def save_vps_data():
    """
    Persist the complete in-memory VPS state.

    Important:
    - UPSERT is based on container_name (UNIQUE), not the in-memory id.
    - This fixes the old 'UPDATE affected 0 rows' problem where data could
      disappear after restart.
    - One transaction writes the whole VPS state atomically.
    - No normal save-success messages are printed to the console.
    """
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")

            for user_id, vps_list in list(vps_data.items()):
                for vps in list(vps_list):
                    container_name = str(vps.get("container_name") or "").strip()
                    if not container_name:
                        raise ValueError("Cannot persist VPS without container_name")

                    shared_json = json.dumps(
                        vps.get("shared_with", []),
                        ensure_ascii=False,
                    )
                    history_json = json.dumps(
                        vps.get("suspension_history", []),
                        ensure_ascii=False,
                    )

                    cur.execute("""
                        INSERT INTO vps (
                            user_id, node_id, container_name, ram, cpu, storage,
                            config, os_version, status, suspended, whitelisted,
                            created_at, shared_with, suspension_history,
                            expiration_date, root_password, last_modified
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(container_name) DO UPDATE SET
                            user_id = excluded.user_id,
                            node_id = excluded.node_id,
                            ram = excluded.ram,
                            cpu = excluded.cpu,
                            storage = excluded.storage,
                            config = excluded.config,
                            os_version = excluded.os_version,
                            status = excluded.status,
                            suspended = excluded.suspended,
                            whitelisted = excluded.whitelisted,
                            created_at = excluded.created_at,
                            shared_with = excluded.shared_with,
                            suspension_history = excluded.suspension_history,
                            expiration_date = excluded.expiration_date,
                            root_password = excluded.root_password,
                            last_modified = CURRENT_TIMESTAMP
                    """, (
                        str(user_id),
                        int(vps.get("node_id", 1)),
                        container_name,
                        str(vps.get("ram", "0GB")),
                        str(vps.get("cpu", "0")),
                        str(vps.get("storage", "0GB")),
                        str(vps.get("config", "Custom")),
                        str(vps.get("os_version", "ubuntu:22.04")),
                        str(vps.get("status", "stopped")),
                        1 if vps.get("suspended", False) else 0,
                        1 if vps.get("whitelisted", False) else 0,
                        str(vps.get("created_at") or datetime.now().isoformat()),
                        shared_json,
                        history_json,
                        vps.get("expiration_date"),
                        vps.get("root_password"),
                    ))

                    row = cur.execute(
                        "SELECT id FROM vps WHERE container_name = ?",
                        (container_name,),
                    ).fetchone()
                    if row:
                        vps["id"] = row[0]

            conn.commit()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Database error while saving VPS data: {e}", exc_info=True)
            raise
        finally:
            conn.close()


def save_vps_data_immediate():
    """Persist VPS data immediately; keep normal successful saves silent."""
    try:
        save_vps_data()
    except Exception as e:
        logger.error(f"Critical VPS database save failed: {e}")
        backup_database()


def save_admin_data():
    """Persist administrator data atomically."""
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.cursor()
            cur.execute("BEGIN IMMEDIATE")

            # Keep the main admin in the database as well.
            admin_ids = {str(x) for x in admin_data.get("admins", [])}
            admin_ids.add(str(MAIN_ADMIN_ID))

            cur.execute("DELETE FROM admins")
            cur.executemany(
                "INSERT INTO admins (user_id) VALUES (?)",
                [(admin_id,) for admin_id in sorted(admin_ids)],
            )
            conn.commit()

            # Keep in-memory state consistent with the database.
            admin_data["admins"] = sorted(admin_ids)
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.error(f"Database error while saving admin data: {e}", exc_info=True)
            raise
        finally:
            conn.close()


def save_admin_data_immediate():
    try:
        save_admin_data()
    except Exception as e:
        logger.error(f"Critical admin database save failed: {e}")
        backup_database()


def get_user_allocation(user_id: str) -> int:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT allocated_ports FROM port_allocations WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()


def get_user_used_ports(user_id: str) -> int:
    with DB_LOCK:
        conn = get_db()
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM port_forwards WHERE user_id = ?",
                (str(user_id),),
            ).fetchone()[0]
        finally:
            conn.close()


def allocate_ports(user_id: str, amount: int):
    with DB_LOCK:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO port_allocations (user_id, allocated_ports, last_modified)
                VALUES (?, MAX(0, ?), CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    allocated_ports = MAX(0, port_allocations.allocated_ports + excluded.allocated_ports),
                    last_modified = CURRENT_TIMESTAMP
            """, (str(user_id), int(amount)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def deallocate_ports(user_id: str, amount: int):
    with DB_LOCK:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO port_allocations (user_id, allocated_ports, last_modified)
                VALUES (?, 0, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id) DO UPDATE SET
                    allocated_ports = MAX(0, port_allocations.allocated_ports - ?),
                    last_modified = CURRENT_TIMESTAMP
            """, (str(user_id), int(amount)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_available_host_port(node_id: int) -> Optional[int]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute("""
                SELECT host_port
                FROM port_forwards
                WHERE vps_container IN (
                    SELECT container_name FROM vps WHERE node_id = ?
                )
            """, (node_id,)).fetchall()
            used_ports = {int(row[0]) for row in rows}

            for _ in range(100):
                port = random.randint(20000, 50000)
                if port not in used_ports:
                    return port
            return None
        finally:
            conn.close()


async def create_port_forward(
    user_id: str, container: str, vps_port: int, node_id: int
) -> Optional[int]:
    host_port = get_available_host_port(node_id)
    if not host_port:
        logger.error(f"No available port found for container {container}")
        return None

    try:
        await execute_lxc(
            container,
            f"config device add {container} tcp_proxy_{host_port} "
            f"proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}",
            node_id=node_id,
        )
        await execute_lxc(
            container,
            f"config device add {container} udp_proxy_{host_port} "
            f"proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}",
            node_id=node_id,
        )

        with DB_LOCK:
            conn = get_db()
            try:
                conn.execute("""
                    INSERT INTO port_forwards
                    (user_id, vps_container, vps_port, host_port, created_at, last_modified)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (
                    str(user_id), container, int(vps_port), int(host_port),
                    datetime.now().isoformat(),
                ))
                conn.commit()
                return host_port
            except Exception as db_error:
                conn.rollback()
                logger.error(
                    f"Database error creating port forward: {db_error}",
                    exc_info=True,
                )
                return None
            finally:
                conn.close()
    except Exception as e:
        logger.error(f"Failed to create port forward: {e}", exc_info=True)
        return None


async def remove_port_forward(
    forward_id: int, is_admin: bool = False
) -> tuple[bool, Optional[str]]:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT user_id, vps_container, host_port FROM port_forwards WHERE id = ?",
                (forward_id,),
            ).fetchone()
            if not row:
                return False, None
            user_id, container, host_port = row
        finally:
            conn.close()

    node_id = find_node_id_for_container(container)
    try:
        await execute_lxc(
            container,
            f"config device remove {container} tcp_proxy_{host_port}",
            node_id=node_id,
        )
        await execute_lxc(
            container,
            f"config device remove {container} udp_proxy_{host_port}",
            node_id=node_id,
        )

        with DB_LOCK:
            conn = get_db()
            try:
                conn.execute(
                    "DELETE FROM port_forwards WHERE id = ?", (forward_id,)
                )
                conn.commit()
            finally:
                conn.close()
        return True, user_id
    except Exception as e:
        logger.error(f"Failed to remove port forward {forward_id}: {e}")
        return False, None


def get_user_forwards(user_id: str) -> List[Dict]:
    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT * FROM port_forwards WHERE user_id = ? ORDER BY created_at DESC",
                (str(user_id),),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


async def recreate_port_forwards(container_name: str) -> int:
    node_id = find_node_id_for_container(container_name)
    readded_count = 0

    with DB_LOCK:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT vps_port, host_port FROM port_forwards WHERE vps_container = ?",
                (container_name,),
            ).fetchall()
        finally:
            conn.close()

    for row in rows:
        vps_port = row["vps_port"]
        host_port = row["host_port"]
        try:
            await execute_lxc(
                container_name,
                f"config device add {container_name} tcp_proxy_{host_port} "
                f"proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:{vps_port}",
                node_id=node_id,
            )
            await execute_lxc(
                container_name,
                f"config device add {container_name} udp_proxy_{host_port} "
                f"proxy listen=udp:0.0.0.0:{host_port} connect=udp:127.0.0.1:{vps_port}",
                node_id=node_id,
            )
            readded_count += 1
        except Exception as e:
            logger.error(
                f"Failed to re-add port forward {host_port}->{vps_port} "
                f"for {container_name}: {e}"
            )

    return readded_count


def find_node_id_for_container(container_name: str) -> int:
    with DB_LOCK:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT node_id FROM vps WHERE container_name = ?",
                (container_name,),
            ).fetchone()
            return int(row[0]) if row else 1
        finally:
            conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# FRAUD DETECTION & PUBLIC VPS CREATION SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

def create_device_fingerprint(user: discord.User) -> str:
    """Create a device fingerprint from user's Discord profile"""
    import hashlib
    user_name = user.name if hasattr(user, 'name') else (user.username if hasattr(user, 'username') else str(user.id))
    fingerprint_data = f"{user.id}:{user_name}:{user.avatar}:{user.created_at.isoformat()}"
    return hashlib.sha256(fingerprint_data.encode()).hexdigest()

def track_user_device(user_id: str, ip_address: str, user: discord.User) -> None:
    """Track user device information for fraud detection"""
    try:
        device_fingerprint = create_device_fingerprint(user)
        user_name = user.name if hasattr(user, 'name') else (user.username if hasattr(user, 'username') else str(user.id))
        avatar_hash = user.avatar.key if user.avatar else None
        
        with DB_LOCK:
            conn = get_db()
            conn.execute("""
                INSERT OR REPLACE INTO user_device_tracking 
                (user_id, ip_address, device_fingerprint, username, avatar_hash, created_at, last_seen, vps_created)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 
                    COALESCE((SELECT vps_created FROM user_device_tracking WHERE user_id = ?), 0))
            """, (str(user_id), ip_address, device_fingerprint, user_name, avatar_hash, str(user_id)))
            conn.commit()
            conn.close()
            logger.info(f"[OK] Tracked device for user {user_id}: IP={ip_address}, FP={device_fingerprint[:16]}...")
    except Exception as e:
        logger.warning(f"Could not track device: {e}")

async def check_fraud_indicators(user_id: str, ip_address: str, user: discord.User, ctx) -> Dict[str, Any]:
    """
    Check for fraud indicators:
    - Multiple VPS per user
    - Multiple accounts from same IP
    - Suspicious account patterns
    - Discord account age
    """
    fraud_score = 0
    flags = []
    
    # Check 1: Account age - handle timezone aware/naive datetime
    try:
        account_created = user.created_at
        current_time = datetime.now(account_created.tzinfo) if account_created.tzinfo else datetime.now()
        account_age_days = (current_time - account_created).days
    except:
        account_age_days = 0
    
    if account_age_days < 7:
        fraud_score += 30
        flags.append(f"⚠️ New Discord account ({account_age_days} days old)")
    elif account_age_days < 30:
        fraud_score += 10
        flags.append(f"⚠️ Recent account ({account_age_days} days old)")
    
    # Check 2: User already has VPS
    with DB_LOCK:
        conn = get_db()
        user_vps_count = conn.execute(
            "SELECT COUNT(*) FROM vps WHERE user_id = ?",
            (str(user_id),)
        ).fetchone()[0]
        
        # Check 3: Multiple accounts from same IP
        same_ip_users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM user_device_tracking WHERE ip_address = ?",
            (ip_address,)
        ).fetchone()[0]
        
        conn.close()
    
    if user_vps_count >= PUBLIC_VPS_MAX_PER_USER:
        fraud_score += 100
        flags.append(f"❌ User already has {user_vps_count} VPS (max: {PUBLIC_VPS_MAX_PER_USER})")
    
    if same_ip_users > PUBLIC_VPS_MAX_PER_IP:
        fraud_score += 50
        flags.append(f"⚠️ {same_ip_users} accounts from this IP (limit: {PUBLIC_VPS_MAX_PER_IP})")
    
    # Check 4: Guild membership
    if ctx.guild:
        member = ctx.guild.get_member(user.id)
        if member and member.joined_at:
            try:
                join_time = member.joined_at
                current_time = datetime.now(join_time.tzinfo) if join_time.tzinfo else datetime.now()
                join_age_days = (current_time - join_time).days
                if join_age_days < 3:
                    fraud_score += 15
                    flags.append(f"⚠️ Recently joined server ({join_age_days} days ago)")
            except:
                pass
    
    # Check 5: Username patterns
    user_name = user.name if hasattr(user, 'name') else (user.username if hasattr(user, 'username') else str(user.id))
    username_suspicious = False
    if len(user_name) < 3:
        fraud_score += 10
        username_suspicious = True
    if any(char.isdigit() for char in user_name) and user_name.replace(str(user.id), "").isdigit():
        fraud_score += 10
        username_suspicious = True
    
    if username_suspicious:
        flags.append("⚠️ Suspicious username pattern")
    
    is_risky = fraud_score >= 50
    
    return {
        'fraud_score': fraud_score,
        'is_risky': is_risky,
        'flags': flags,
        'account_age': account_age_days,
        'vps_count': user_vps_count,
        'same_ip_users': same_ip_users
    }

async def get_user_ip(ctx) -> Optional[str]:
    """Attempt to get user IP from Discord context"""
    try:
        # This is a placeholder - Discord doesn't provide IP directly
        # In production, you might use additional methods or database tracking
        # For now, use user ID as a proxy identifier
        return f"discord_user_{ctx.author.id}"
    except:
        return None


# Initialize database. Any initialization error must stop startup rather
# than allowing the bot to run with a blank/new in-memory state.
try:
    init_db()
except Exception as db_init_error:
    logger.error(f"Fatal database initialization error: {db_init_error}", exc_info=True)
    raise

# Load persistent state after the schema is ready.
vps_data = get_vps_data()
admin_data = {"admins": get_admins()}

# Make sure the main admin can never disappear from the persistent admin list.
if str(MAIN_ADMIN_ID) not in admin_data["admins"]:
    admin_data["admins"].append(str(MAIN_ADMIN_ID))
    save_admin_data()

# Silent background persistence. Immediate saves are still used by critical
# operations, while this catches any future mutation that forgot to save.
async def auto_save_task():
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            await asyncio.sleep(15)
            save_vps_data()
            save_admin_data()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Background database save failed: {e}")


def cleanup_on_shutdown():
    """Final persistent save without normal database-success console messages."""
    try:
        save_vps_data()
        save_admin_data()
    except Exception as e:
        logger.error(f"Final database save failed: {e}")
        backup_database()


atexit.register(cleanup_on_shutdown)

# Global settings from DB
CPU_THRESHOLD = int(get_setting('cpu_threshold', 90))
RAM_THRESHOLD = int(get_setting('ram_threshold', 90))

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ═══════════════════════════════════════════════════════════════════════════
# FLASK WEB SSH SERVER
# ═══════════════════════════════════════════════════════════════════════════

app = Flask(__name__)
CORS(app)

# Store SSH sessions
ssh_sessions = {}

@app.route('/')
def index():
    """Serve the web SSH HTML"""
    try:
        with open('webssh.html', 'r', encoding='utf-8') as f:
            html_content = f.read()
        # Replace bot name in HTML
        html_content = html_content.replace('id="page-title"', f'id="page-title" data-bot-name="{BOT_NAME}"')
        return html_content
    except FileNotFoundError:
        return '''
        <html>
            <head><title>Web SSH</title></head>
            <body style="background: #f0f0f0; display: flex; justify-content: center; align-items: center; height: 100vh;">
                <h1 style="color: #333;">⚠️ webssh.html not found</h1>
            </body>
        </html>
        ''', 404

# ═══════════════════════════════════════════════════════════════════════════
# LIVE SSH STREAMING ENDPOINTS (xterm.js compatible)
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/ssh/connect', methods=['POST'])
def ssh_connect():
    """Open an interactive SSH shell and start a reader thread."""
    try:
        data = request.json
        host     = data.get('host')
        port     = int(data.get('port', 22))
        username = data.get('username')
        password = data.get('password')

        if not all([host, port, username, password]):
            return jsonify({'success': False, 'error': 'Missing connection details'}), 400

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            ssh.connect(host, port=port, username=username,
                        password=password, timeout=15, allow_agent=False, look_for_keys=False)

            transport = ssh.get_transport()
            transport.set_keepalive(30)

            channel = transport.open_session()
            channel.get_pty(term='xterm-256color', width=120, height=30)
            channel.invoke_shell()

            session_id = secrets.token_hex(16)

            # buffer to accumulate server output between reads
            ssh_sessions[session_id] = {
                'ssh': ssh,
                'transport': transport,
                'channel': channel,
                'host': host,
                'port': port,
                'username': username,
                'created_at': datetime.now(),
                'last_activity': datetime.now(),
                'buffer': '',           # accumulated output not yet read
                'closed': False,
                'lock': threading.Lock()
            }

            session = ssh_sessions[session_id]

            # background reader: pushes every chunk of server output into buffer
            def reader():
                chan = session['channel']
                try:
                    while True:
                        if chan.recv_ready():
                            chunk = chan.recv(65536)
                            if not chunk:
                                break
                            try:
                                text = chunk.decode('utf-8', errors='replace')
                            except Exception:
                                text = chunk.decode('latin-1', errors='replace')
                            with session['lock']:
                                # cap buffer size so we don't leak memory
                                session['buffer'] += text
                                if len(session['buffer']) > 500_000:
                                    session['buffer'] = session['buffer'][-250_000:]
                        elif chan.exit_status_ready() and not chan.recv_ready():
                            break
                        else:
                            time.sleep(0.02)
                except Exception as e:
                    logger.debug(f"SSH reader ended for {session_id[:8]}: {e}")
                finally:
                    session['closed'] = True

            session['reader_thread'] = threading.Thread(target=reader, daemon=True)
            session['reader_thread'].start()

            logger.info(f"✅ Live SSH session started: {username}@{host}:{port} ({session_id[:8]})")
            return jsonify({
                'success': True,
                'session_id': session_id,
                'message': f'Connected to {username}@{host}:{port}'
            })

        except paramiko.AuthenticationException:
            return jsonify({'success': False, 'error': 'Authentication failed - wrong username/password'}), 401
        except paramiko.SSHException as e:
            return jsonify({'success': False, 'error': f'SSH error: {str(e)}'}), 400
        except Exception as e:
            return jsonify({'success': False, 'error': f'Connection failed: {str(e)}'}), 400

    except Exception as e:
        logger.error(f"SSH connect error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ssh/read', methods=['POST'])
def ssh_read():
    """Return any new output from the SSH channel since last_index."""
    try:
        data = request.json
        session_id = data.get('session_id')
        last_index = int(data.get('last_index', 0))

        session = ssh_sessions.get(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Invalid or expired session'}), 401

        with session['lock']:
            buf = session['buffer']

            # if client is far behind (buffer was trimmed), resync
            if last_index > len(buf):
                last_index = 0

            new_data = buf[last_index:]
            new_index = len(buf)
            closed = session.get('closed', False)

        session['last_activity'] = datetime.now()

        return jsonify({
            'success': True,
            'data': new_data,
            'last_index': new_index,
            'closed': closed
        })

    except Exception as e:
        logger.error(f"SSH read error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ssh/write', methods=['POST'])
def ssh_write():
    """Send user keystrokes to the SSH channel."""
    try:
        data = request.json
        session_id = data.get('session_id')
        payload = data.get('data', '')

        session = ssh_sessions.get(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Invalid or expired session'}), 401

        chan = session['channel']
        if not chan or chan.closed:
            return jsonify({'success': False, 'error': 'Channel closed'}), 410

        try:
            chan.send(payload)
        except Exception as e:
            return jsonify({'success': False, 'error': f'Send failed: {e}'}), 500

        session['last_activity'] = datetime.now()
        return jsonify({'success': True})

    except Exception as e:
        logger.error(f"SSH write error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ssh/resize', methods=['POST'])
def ssh_resize():
    """Resize the remote PTY when the browser terminal is resized."""
    try:
        data = request.json
        session_id = data.get('session_id')
        cols = int(data.get('cols', 80))
        rows = int(data.get('rows', 24))

        session = ssh_sessions.get(session_id)
        if not session:
            return jsonify({'success': False, 'error': 'Invalid session'}), 401

        chan = session['channel']
        try:
            chan.resize_pty(width=cols, height=rows)
        except Exception:
            pass

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/ssh/disconnect', methods=['POST'])
def ssh_disconnect():
    """Close SSH session."""
    try:
        data = request.json
        session_id = data.get('session_id')

        session = ssh_sessions.pop(session_id, None)
        if session:
            try:
                session['channel'].close()
                session['transport'].close()
                session['ssh'].close()
            except Exception:
                pass
            logger.info(f"SSH session closed: {session.get('username')}@{session.get('host')}")
            return jsonify({'success': True, 'message': 'Disconnected'})

        return jsonify({'success': False, 'error': 'Session not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'bot_name': BOT_NAME,
        'active_sessions': len(ssh_sessions)
    })

def cleanup_expired_sessions():
    """Clean up expired SSH sessions"""
    while True:
        try:
            now = datetime.now()
            expired_sessions = []
            
            for session_id, session in list(ssh_sessions.items()):
                # Close session if inactive for more than 30 minutes
                if (now - session['last_activity']).total_seconds() > 1800:
                    try:
                        session['ssh'].close()
                    except:
                        pass
                    expired_sessions.append(session_id)
            
            for session_id in expired_sessions:
                del ssh_sessions[session_id]
                logger.info(f"Cleaned up expired SSH session: {session_id[:8]}...")
            
            time.sleep(300)  # Check every 5 minutes
        except Exception as e:
            logger.error(f"Session cleanup error: {e}")
            time.sleep(300)

# Start session cleanup thread
cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
cleanup_thread.start()

# Resource monitoring settings (logging only)
resource_monitor_active = True

# ═══════════════════════════════════════════════════════════════════════════
# MODERN UI/UX SYSTEM - Beautiful Discord Embeds
# ═══════════════════════════════════════════════════════════════════════════

# Professional Color Palette
COLOR_PRIMARY = 0x2c3e50      # Dark slate blue
COLOR_SUCCESS = 0x27ae60      # Modern green  
COLOR_ERROR = 0xe74c3c        # Bright red
COLOR_WARNING = 0xf39c12      # Amber
COLOR_INFO = 0x3498db         # Ocean blue
COLOR_NETWORK = 0x16a085      # Teal
COLOR_EXPIRED = 0xc0392b      # Dark red
COLOR_ACTIVE = 0x16a085       # Teal green
COLOR_SUSPENDED = 0x95a5a6    # Gray
COLOR_NODE = 0x8e44ad         # Purple

# Helper function to truncate text
def truncate_text(text, max_length=1024):
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

# Password generation and management functions
def generate_strong_password(length=16):
    """Generate a cryptographically strong password"""
    # Use mix of uppercase, lowercase, digits, and special characters
    charset = string.ascii_letters + string.digits + "!@#$%^&*"
    password = ''.join(secrets.choice(charset) for _ in range(length))
    return password

def sanitize_username_for_container(username: str) -> str:
    """
    Sanitize username for LXC container naming.
    LXC only allows alphanumeric and hyphen characters.
    Replace underscores, spaces, and other invalid chars with hyphens.
    """
    # Replace underscores and spaces with hyphens
    sanitized = username.replace('_', '-').replace(' ', '-')
    # Remove any character that's not alphanumeric or hyphen
    sanitized = ''.join(c for c in sanitized if c.isalnum() or c == '-')
    # Ensure it doesn't start or end with hyphen (LXC requirement)
    sanitized = sanitized.strip('-').lower()
    # Limit length to avoid issues (LXC container names have limits)
    sanitized = sanitized[:30]
    return sanitized

def get_vps_password(container_name):
    """Get password from VPS data"""
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                return vps.get('root_password', None)
    return None

def set_vps_password(container_name, password):
    """Set password for VPS"""
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                vps['root_password'] = password
                save_vps_data_immediate()
                return True
    return False

async def configure_ssh(container_name, node_id, password):
    """Configure SSH on VPS and set root password"""
    try:
        # Simple SSH configuration commands
        ssh_config_content = """Port 22
AddressFamily any
ListenAddress 0.0.0.0
ListenAddress ::
PasswordAuthentication yes
PubkeyAuthentication yes
PermitRootLogin yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM yes
MaxAuthTries 6
MaxSessions 10
SyslogFacility AUTH
LogLevel INFO
X11Forwarding yes
X11DisplayOffset 10
PrintMotd no
PrintLastLog yes
TCPKeepAlive yes
PermitUserEnvironment no
Subsystem sftp /usr/lib/openssh/sftp-server"""

        # Create SSH config using Python string, escaping properly
        config_cmd = ssh_config_content.replace('\n', '\\n')
        
        # Apply SSH configuration
        await execute_lxc(container_name, 
            f'exec {container_name} -- bash -c "echo -e \\"{config_cmd}\\" > /etc/ssh/sshd_config"',
            node_id=node_id)
        logger.info(f"SSH config file written on {container_name}")
        
        # Restart SSH service with multiple fallbacks
        restart_cmd = "systemctl restart ssh 2>/dev/null || service ssh restart 2>/dev/null || /etc/init.d/ssh restart 2>/dev/null || true"
        await execute_lxc(container_name,
            f'exec {container_name} -- bash -c "{restart_cmd}"',
            node_id=node_id)
        logger.info(f"SSH service restarted on {container_name}")
        
        # Set root password using chpasswd (non-interactive and reliable)
        await execute_lxc(container_name,
            f"exec {container_name} -- bash -c \"echo 'root:{password}' | chpasswd\"",
            node_id=node_id)
        logger.info(f"Root password set for {container_name}")
        
        # Store password
        set_vps_password(container_name, password)
        return True, password
    except Exception as e:
        logger.error(f"Failed to configure SSH for {container_name}: {e}")
        return False, str(e)

def truncate_text(text, max_length=1024):
    if not text:
        return text
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."

# Create professional embeds with modern styling
def create_embed(title, description="", color=COLOR_PRIMARY):
    """Create a beautiful, modern embed"""
    embed = discord.Embed(
        title=f"🌟 {title}",
        description=truncate_text(description, 4096),
        color=color
    )
    embed.set_thumbnail(url=BOT_THUMBNAIL_URL)
    embed.set_footer(
        text=f"Made by AnkitCoder • v{BOT_VERSION} • {datetime.now().strftime('%H:%M:%S')}",
        icon_url=BOT_ICON_URL
    )
    embed.timestamp = datetime.now()
    return embed

def add_field(embed, name, value, inline=False):
    """Add a field with professional formatting"""
    embed.add_field(
        name=f"➤ {name}",
        value=truncate_text(value, 1024),
        inline=inline
    )
    return embed

def create_success_embed(title, description=""):
    """Create a success embed (green)"""
    return create_embed(title, description, COLOR_SUCCESS)

def create_error_embed(title, description=""):
    """Create an error embed (red)"""
    return create_embed(title, description, COLOR_ERROR)

def create_info_embed(title, description=""):
    """Create an info embed (blue)"""
    return create_embed(title, description, COLOR_INFO)

def create_warning_embed(title, description=""):
    """Create a warning embed (orange)"""
    return create_embed(title, description, COLOR_WARNING)

# Visual helper functions
def create_progress_bar(value, max_value=100, length=15):
    """Create a visual progress bar with emoji blocks"""
    if max_value == 0:
        percentage = 0
    else:
        percentage = int((value / max_value) * 100)
    filled = int((percentage / 100) * length)
    bar = "🟩" * filled + "⬜" * (length - filled)
    return f"{bar} `{percentage}%`"

def format_expiration(vps):
    """Format expiration date with visual badge"""
    if not vps.get('expiration_date'):
        return "🔵 No expiration"
    
    exp_dt = datetime.fromisoformat(vps['expiration_date'])
    days = (exp_dt - datetime.now()).days
    
    if days < 0:
        return f"🔴 **EXPIRED** (`{abs(days)}d ago`)"
    elif days <= EXPIRATION_WARNING_DAYS:
        return f"🟡 **EXPIRING** (`{days}d left`)"
    else:
        return f"🟢 **ACTIVE** (`{days}d left`)"

def create_vps_card(vps, index):
    """Create a formatted VPS information card"""
    node = get_node(vps.get('node_id', 1))
    status_emoji = "🟢" if (vps.get('status') == 'running' and not vps.get('suspended')) else "🟡" if vps.get('suspended') else "🔴"
    node_emoji = "📍" if (node and node.get('is_local')) else "🌐"
    
    card = (
        f"**#{index}** `{vps['container_name']}`\n"
        f"{status_emoji} {vps.get('status', 'unknown').upper()}"
    )
    if vps.get('suspended'):
        card += " (SUSPENDED)"
    
    card += (
        f"\n⚙️ **Config:** {vps.get('config', 'Custom')}\n"
        f"💾 **RAM:** {vps['ram']} | **CPU:** {vps['cpu']} | **Disk:** {vps['storage']}\n"
        f"{node_emoji} **Node:** {node['name'] if node else 'Unknown'}\n"
        f"⏰ **Expiration:** {format_expiration(vps)}"
    )
    return card

# Admin checks
def is_admin():
    async def predicate(ctx):
        user_id = str(ctx.author.id)
        if user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", []):
            return True
        raise commands.CheckFailure("You need admin permissions to use this command. Contact support.")
    return commands.check(predicate)

def is_main_admin():
    async def predicate(ctx):
        if str(ctx.author.id) == str(MAIN_ADMIN_ID):
            return True
        raise commands.CheckFailure("Only the main admin can use this command.")
    return commands.check(predicate)

# LXC command execution with multi-node support
async def execute_lxc(container_name: str, command: str, timeout=120, node_id: Optional[int] = None):
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    
    if not node:
        raise Exception(f"Node {node_id} not found")
    
    full_command = f"lxc {command}"
    
    # is_local is already boolean from get_node()
    if node['is_local']:
        try:
            cmd = shlex.split(full_command)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise asyncio.TimeoutError(f"Command timed out after {timeout} seconds")
            
            if proc.returncode != 0:
                error = stderr.decode().strip() if stderr else "Command failed with no error output"
                # Add more context to error
                raise Exception(f"Local LXC command failed: {error}\nCommand: {full_command}")
            return stdout.decode().strip() if stdout else True
        except asyncio.TimeoutError as te:
            logger.error(f"LXC command timed out: {full_command} - {str(te)}")
            raise
        except Exception as e:
            logger.error(f"LXC Error: {full_command} - {str(e)}")
            raise
    else:
        # Use Remote Node API - handle unreachable nodes gracefully with proper error reporting
        url = f"{node['url']}/api/execute"
        data = {"command": full_command}
        params = {"api_key": node["api_key"]}
        try:
            response = requests.post(url, json=data, params=params, timeout=timeout)
            
            # Check for HTTP errors first
            if response.status_code != 200:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_detail = response.json()
                    if 'detail' in error_detail:
                        error_msg = error_detail['detail']
                    elif 'error' in error_detail:
                        error_msg = error_detail['error']
                    elif 'stderr' in error_detail:
                        error_msg = error_detail['stderr']
                except:
                    pass
                raise Exception(f"Remote execution failed on {node['name']}: {error_msg}\nCommand: {full_command}")
            
            # Parse successful response
            res = response.json()
            if res.get("returncode", 1) != 0:
                stderr = res.get("stderr", "Command failed")
                logger.warning(f"Remote command failed on node {node['name']}: {stderr}")
                raise Exception(f"Remote LXC command failed on {node['name']}: {stderr}\nCommand: {full_command}")
            
            return res.get("stdout", True)
            
        except requests.exceptions.ConnectionError as ce:
            # Network error - node is unreachable (log as debug to avoid spam)
            logger.debug(f"Node {node['name']} unreachable at {node['url']} - network connection failed")
            raise Exception(f"Node {node['name']} is unreachable (network error). The remote node may be offline.")
        except requests.exceptions.Timeout:
            # Timeout error
            logger.warning(f"Remote execution timed out on node {node['name']}")
            raise Exception(f"Remote execution timed out on {node['name']} (timeout after {timeout}s)")
        except requests.exceptions.RequestException as e:
            # Other request errors
            logger.warning(f"Remote execution error on node {node['name']}: {str(e)}")
            raise Exception(f"Remote execution failed on {node['name']}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error executing command on node {node['name']}: {str(e)}")
            raise

# Apply LXC config
async def apply_lxc_config(container_name: str, node_id: int):
    try:
        await execute_lxc(container_name, f"config set {container_name} security.nesting true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.privileged true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.mknod true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} security.syscalls.intercept.setxattr true", node_id=node_id)
        await execute_lxc(container_name, f"config set {container_name} linux.kernel_modules overlay,loop,nf_nat,ip_tables,ip6_tables,netlink_diag,br_netfilter", node_id=node_id)
        try:
            await execute_lxc(container_name, f"config device add {container_name} fuse unix-char path=/dev/fuse", node_id=node_id)
        except:
            pass
        raw_lxc_config = (
            "lxc.apparmor.profile = unconfined\n"
            "lxc.apparmor.allow_nesting = 1\n"
            "lxc.apparmor.allow_incomplete = 1\n"
            "\n"
            "lxc.cap.drop =\n"
            "lxc.cgroup.devices.allow = a\n"
            "lxc.cgroup2.devices.allow = a\n"
            "\n"
            "lxc.mount.auto = proc:rw sys:rw cgroup:rw shmounts:rw\n"
            "\n"
            "lxc.mount.entry = /dev/fuse dev/fuse none bind,create=file 0 0\n"
        )
        await execute_lxc(container_name, f"config set {container_name} raw.lxc '{raw_lxc_config}'", node_id=node_id)
        logger.info(f"LXC permissions applied to {container_name} on node {node_id}")
    except Exception as e:
        logger.error(f"Failed to apply LXC config to {container_name}: {e}")

# Apply internal permissions
async def apply_internal_permissions(container_name: str, node_id: int):
    try:
        await asyncio.sleep(5)
        commands = [
            "mkdir -p /etc/sysctl.d/",
            "echo 'net.ipv4.ip_unprivileged_port_start=0' > /etc/sysctl.d/99-custom.conf",
            "echo 'net.ipv4.ping_group_range=0 2147483647' >> /etc/sysctl.d/99-custom.conf",
            "echo 'fs.inotify.max_user_watches=524288' >> /etc/sysctl.d/99-custom.conf",
            "echo 'kernel.unprivileged_userns_clone=1' >> /etc/sysctl.d/99-custom.conf",
            "sysctl -p /etc/sysctl.d/99-custom.conf || true"
        ]
        for cmd in commands:
            try:
                await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{cmd}\"", node_id=node_id)
            except Exception as cmd_error:
                logger.warning(f"Command failed in {container_name}: {cmd} - {cmd_error}")
        logger.info(f"Internal permissions applied to {container_name}")
    except Exception as e:
        logger.error(f"Failed to apply internal permissions to {container_name}: {e}")

# Get or create VPS role
async def get_or_create_vps_role(guild):
    global VPS_USER_ROLE_ID

    me = guild.me
    if not me or not me.guild_permissions.manage_roles:
        return None

    role_name = f"{BOT_NAME} VPS User"

    # Try cached role
    if VPS_USER_ROLE_ID:
        role = guild.get_role(VPS_USER_ROLE_ID)
        if role and role < me.top_role:
            return role
        VPS_USER_ROLE_ID = None

    # Find by name
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        if role >= me.top_role:
            try:
                await role.delete(reason="Role above bot, recreating")
            except discord.Forbidden:
                return None
            role = None
        else:
            VPS_USER_ROLE_ID = role.id
            return role

    # Create safely below bot
    try:
        role = await guild.create_role(
            name=role_name,
            color=discord.Color.dark_purple(),
            permissions=discord.Permissions.none(),
            reason=f"{BOT_NAME} VPS User role"
        )
        await role.edit(position=me.top_role.position - 1)
        VPS_USER_ROLE_ID = role.id
        logger.info(f"Created VPS role: {role.id}")
        return role
    except Exception as e:
        logger.error(f"Failed to create VPS role: {e}")
        return None

# Host resource functions
def get_host_cpu_usage():
    """Get host CPU usage - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            # Windows: Use wmic or psutil as fallback
            try:
                import psutil
                return psutil.cpu_percent(interval=1)
            except ImportError:
                # Fallback for Windows without psutil
                try:
                    result = subprocess.run(['wmic', 'os', 'get', 'TotalVisibleMemorySize'], 
                                          capture_output=True, text=True, timeout=5)
                    return 0.0  # Default value on Windows
                except:
                    return 0.0
        else:
            # Linux/Unix: Use mpstat or top
            if shutil.which("mpstat"):
                result = subprocess.run(['mpstat', '1', '1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if 'all' in line and '%' in line:
                        parts = line.split()
                        idle = float(parts[-1])
                        return 100.0 - idle
            else:
                result = subprocess.run(['top', '-bn1'], capture_output=True, text=True, timeout=10)
                output = result.stdout
                for line in output.split('\n'):
                    if '%Cpu(s):' in line:
                        # Parse CPU line - format: %Cpu(s): us,sy,ni,id,wa,hi,si,st
                        cpu_data = line.split('%Cpu(s):')[1].strip()
                        parts = []
                        for item in cpu_data.split(','):
                            val = item.split()[0].strip()
                            try:
                                parts.append(float(val))
                            except ValueError:
                                parts.append(0.0)
                        
                        if len(parts) >= 8:
                            us = parts[0]
                            sy = parts[1]
                            ni = parts[2]
                            id_ = parts[3]
                            wa = parts[4]
                            hi = parts[5]
                            si = parts[6]
                            st = parts[7]
                            usage = us + sy + ni + wa + hi + si + st
                            return usage
            return 0.0
    except Exception as e:
        logger.debug(f"Error getting CPU usage: {e}")
        return 0.0

def get_host_ram_usage():
    """Get host RAM usage - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            # Windows: Use psutil or wmic
            try:
                import psutil
                mem = psutil.virtual_memory()
                return mem.percent
            except ImportError:
                # Fallback for Windows without psutil
                try:
                    result = subprocess.run(['wmic', 'OS', 'get', 'TotalVisibleMemorySize,FreePhysicalMemory'], 
                                          capture_output=True, text=True, timeout=5)
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        values = lines[1].split()
                        if len(values) >= 2:
                            total = int(values[0])
                            free = int(values[1])
                            used = total - free
                            return (used / total * 100) if total > 0 else 0.0
                except:
                    pass
                return 0.0
        else:
            # Linux/Unix: Use free command
            result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                mem = lines[1].split()
                total = int(mem[1])
                used = int(mem[2])
                return (used / total * 100) if total > 0 else 0.0
            return 0.0
    except Exception as e:
        logger.debug(f"Error getting RAM usage: {e}")
        return 0.0

async def get_host_stats(node_id: int) -> Dict:
    node = get_node(node_id)
    if node['is_local']:
        return {
            "cpu": get_host_cpu_usage(),
            "ram": get_host_ram_usage(),
            "disk": get_host_disk_usage()
        }
    else:
        # Remote node - handle gracefully if unreachable
        url = f"{node['url']}/api/get_host_stats"
        params = {"api_key": node["api_key"]}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            stats = response.json()
            # Fallbacks if remote API doesn't provide
            stats['disk'] = stats.get('disk', 'Unknown')
            return stats
        except requests.exceptions.ConnectionError:
            # Remote node unreachable - return graceful defaults
            logger.debug(f"Remote node {node['name']} unreachable - returning default stats")
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}
        except Exception as e:
            logger.debug(f"Failed to get stats from remote node {node['name']}: {e}")
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}

def check_vps_expiration():
    """Check and auto-suspend expired VPS"""
    global bot
    try:
        warned_users = set()
        
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps.get('expiration_date'):
                    expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    days_remaining = (expiration_dt - datetime.now()).days
                    hours_remaining = ((expiration_dt - datetime.now()).total_seconds() / 3600)
                    
                    container_name = vps['container_name']
                    node_id = vps.get('node_id', 1)
                    
                    # Auto-suspend if expired
                    if days_remaining < 0:
                        if not vps.get('suspended', False):
                            try:
                                # Suspend the VPS
                                asyncio.run(execute_lxc(container_name, f"stop {container_name}", node_id=node_id))
                                vps['status'] = 'stopped'
                                vps['suspended'] = True
                                vps['suspension_history'].append({
                                    'time': datetime.now().isoformat(),
                                    'reason': f'Auto-suspended due to VPS expiration on {expiration_dt.strftime("%Y-%m-%d")}',
                                    'by': 'Expiration Monitor'
                                })
                                save_vps_data_immediate()
                                logger.warning(f"VPS {container_name} auto-suspended due to expiration")
                                
                                # Notify owner
                                try:
                                    owner = asyncio.run(bot.fetch_user(int(user_id)))
                                    dm_embed = create_error_embed("🔴 VPS Expired and Suspended",
                                        f"Your VPS `{container_name}` has expired and been suspended.\n\n"
                                        f"**Expiration Date:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                        f"Contact an admin to renew your VPS.")
                                    asyncio.run(owner.send(embed=dm_embed))
                                except Exception as e:
                                    logger.debug(f"Failed to notify user {user_id}: {e}")
                            except Exception as e:
                                logger.error(f"Failed to auto-suspend VPS {container_name}: {e}")
                    
                    # Send warning if expiring soon
                    elif 0 < hours_remaining <= (EXPIRATION_WARNING_DAYS * 24):
                        if user_id not in warned_users:
                            try:
                                owner = asyncio.run(bot.fetch_user(int(user_id)))
                                dm_embed = create_warning_embed("⏰ VPS Expiring Soon",
                                    f"Your VPS `{container_name}` will expire in {days_remaining} day(s)!\n\n"
                                    f"**Expiration Date:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                    f"Contact an admin to renew your VPS before it's automatically suspended.")
                                asyncio.run(owner.send(embed=dm_embed))
                                warned_users.add(user_id)
                                logger.info(f"Sent expiration warning to user {user_id}")
                            except Exception as e:
                                logger.debug(f"Failed to notify user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error in VPS expiration check: {e}")

def resource_monitor():
    global resource_monitor_active
    last_expiration_check = time.time()
    expiration_check_interval = 3600  # Check every hour
    
    while resource_monitor_active:
        try:
            # Check VPS expiration every hour
            if time.time() - last_expiration_check > expiration_check_interval:
                check_vps_expiration()
                last_expiration_check = time.time()
            
            nodes = get_nodes()
            for node in nodes:
                # Only monitor LOCAL nodes - skip remote nodes to avoid "No route to host" errors
                if node['is_local']:
                    stats = asyncio.run(get_host_stats(node['id']))
                    cpu = stats['cpu']
                    ram = stats['ram']
                    logger.info(f"Node {node['name']}: CPU {cpu:.1f}%, RAM {ram:.1f}%")
                    if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                        logger.warning(f"Node {node['name']} exceeded thresholds (CPU: {CPU_THRESHOLD}%, RAM: {RAM_THRESHOLD}%). Manual intervention required.")
                else:
                    # Remote nodes - skip monitoring to avoid connection errors
                    logger.debug(f"Skipping remote node {node['name']} - remote nodes monitored on-demand only")
            
            time.sleep(60)
        except Exception as e:
            logger.error(f"Error in resource monitor: {e}")
            time.sleep(60)

# Start resource monitoring thread
monitor_thread = threading.Thread(target=resource_monitor, daemon=True)
monitor_thread.start()

# Container stats with multi-node
async def get_container_stats(container_name: str, node_id: Optional[int] = None) -> Dict:
    if node_id is None:
        node_id = find_node_id_for_container(container_name)
    node = get_node(node_id)
    if node['is_local']:
        status = await get_container_status_local(container_name)
        cpu = await get_container_cpu_pct_local(container_name)
        ram = await get_container_ram_local(container_name)
        disk = await get_container_disk_local(container_name)
        uptime = await get_container_uptime_local(container_name)
        return {"status": status, "cpu": cpu, "ram": ram, "disk": disk, "uptime": uptime}
    else:
        # Remote node - handle unreachable nodes gracefully without spamming logs
        url = f"{node['url']}/api/get_container_stats"
        data = {"container": container_name}
        params = {"api_key": node["api_key"]}
        try:
            response = requests.post(url, json=data, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            # Remote node unreachable - return graceful defaults
            logger.debug(f"Remote node {node['name']} unreachable for container {container_name}")
            return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}
        except Exception as e:
            logger.debug(f"Failed to get container stats from remote node {node['name']}: {e}")
            return {"status": "unknown", "cpu": 0.0, "ram": {"used": 0, "total": 0, "pct": 0.0}, "disk": "Unknown", "uptime": "Unknown"}

async def get_container_status_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "info", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if line.startswith("Status: "):
                return line.split(": ", 1)[1].strip().lower()
        return "unknown"
    except Exception:
        return "unknown"

async def get_container_cpu_pct_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "top", "-bn1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode()
        for line in output.splitlines():
            if '%Cpu(s):' in line:
                # Parse CPU line - format: %Cpu(s): us,sy,ni,id,wa,hi,si,st
                # Remove label and split by commas
                cpu_data = line.split('%Cpu(s):')[1].strip()
                parts = []
                for item in cpu_data.split(','):
                    # Extract number before the percentage/label
                    val = item.split()[0].strip()
                    try:
                        parts.append(float(val))
                    except ValueError:
                        parts.append(0.0)
                
                if len(parts) >= 8:
                    us = parts[0]  # user
                    sy = parts[1]  # system
                    ni = parts[2]  # nice
                    id_ = parts[3] # idle
                    wa = parts[4]  # wait
                    hi = parts[5]  # hardware interrupt
                    si = parts[6]  # software interrupt
                    st = parts[7]  # steal
                    return us + sy + ni + wa + hi + si + st
        return 0.0
    except Exception as e:
        logger.error(f"Error getting container CPU for {container_name}: {e}")
        return 0.0

async def get_container_ram_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "free", "-m",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        if len(lines) > 1:
            parts = lines[1].split()
            total = int(parts[1])
            used = int(parts[2])
            pct = (used / total * 100) if total > 0 else 0.0
            return {'used': used, 'total': total, 'pct': pct}
        return {'used': 0, 'total': 0, 'pct': 0.0}
    except Exception as e:
        logger.error(f"Error getting RAM for {container_name}: {e}")
        return {'used': 0, 'total': 0, 'pct': 0.0}

async def get_container_disk_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "df", "-h", "/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        for line in lines:
            if '/dev/' in line and ' /' in line:
                parts = line.split()
                if len(parts) >= 5:
                    used = parts[2]
                    size = parts[1]
                    perc = parts[4]
                    return f"{used}/{size} ({perc})"
        return "Unknown"
    except Exception:
        return "Unknown"

async def get_container_uptime_local(container_name: str):
    try:
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "uptime",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip() if stdout else "Unknown"
    except Exception:
        return "Unknown"

async def get_container_status(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['status']

async def get_container_cpu(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return f"{stats['cpu']:.1f}%"

async def get_container_cpu_pct(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['cpu']

async def get_container_memory(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    ram = stats['ram']
    return f"{ram['used']}/{ram['total']} MB ({ram['pct']:.1f}%)"

async def get_container_ram_pct(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['ram']['pct']

async def get_container_networks(container_name: str, node_id: Optional[int] = None) -> Dict[str, str]:
    """Get all network interfaces and their IPs from a container using ip addr command"""
    try:
        if node_id is None:
            node_id = find_node_id_for_container(container_name)
        
        # First attempt: Use simple ip addr show command
        proc = await asyncio.create_subprocess_exec(
            "lxc", "exec", container_name, "--", "ip", "addr", "show",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        networks = {}
        
        if proc.returncode == 0:
            output = stdout.decode().strip()
            
            # Parse ip addr show output
            # Format: 
            # 2: eth0: <BROADCAST,RUNNING> mtu 1500
            #     inet 10.0.0.10/24 brd 10.0.0.255 scope global eth0
            
            lines = output.split('\n')
            current_interface = None
            
            for line in lines:
                # Check for interface line (starts with number and interface name)
                if line and line[0].isdigit():
                    # Extract interface name from line like "2: eth0: <BROADCAST>"
                    parts = line.split(':')
                    if len(parts) >= 2:
                        current_interface = parts[1].strip()
                
                # Check for inet line (IPv4 address)
                elif 'inet ' in line and current_interface:
                    # Extract IP from line like "    inet 10.0.0.10/24 brd 10.0.0.255 scope global eth0"
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[0] == 'inet':
                        ip_with_cidr = parts[1]
                        ip = ip_with_cidr.split('/')[0]
                        
                        # Skip loopback
                        if ip != "127.0.0.1" and current_interface != "lo":
                            networks[current_interface] = ip
        else:
            logger.warning(f"Failed to get network info for {container_name}: {stderr.decode()}")
        
        if networks:
            logger.info(f"Found {len(networks)} network interfaces on {container_name}: {networks}")
        else:
            logger.warning(f"No usable network interfaces found for {container_name}")
        
        return networks
    except Exception as e:
        logger.error(f"Error getting networks for {container_name}: {e}")
        return {}

async def get_container_disk(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['disk']

async def get_container_uptime(container_name: str, node_id: Optional[int] = None):
    stats = await get_container_stats(container_name, node_id)
    return stats['uptime']

def get_uptime():
    """Get system uptime - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            try:
                result = subprocess.run(['net', 'statistics', 'server'], 
                                      capture_output=True, text=True, timeout=5)
                output = result.stdout
                for line in output.split('\n'):
                    if 'Statistics since' in line:
                        return line.strip()
                return "Unknown"
            except:
                # Fallback: use wmic
                try:
                    result = subprocess.run(['wmic', 'os', 'get', 'lastbootuptime'], 
                                          capture_output=True, text=True, timeout=5)
                    return result.stdout.strip() if result.stdout else "Unknown"
                except:
                    return "Unknown"
        else:
            # Linux/Unix: Use uptime command
            result = subprocess.run(['uptime'], capture_output=True, text=True, timeout=5)
            return result.stdout.strip()
    except Exception as e:
        logger.debug(f"Error getting uptime: {e}")
        return "Unknown"

# Try to detect default storage pool or use common defaults
def get_default_storage_pool():
    try:
        result = subprocess.run(['lxc', 'storage', 'list', '--format', 'csv'], 
                              capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        if lines and lines[0]:
            # Get first storage pool
            return lines[0].split(',')[0]
    except:
        pass
    return "default"  # Fallback to 'default'

DEFAULT_STORAGE_POOL = os.getenv('DEFAULT_STORAGE_POOL', get_default_storage_pool())

# Bot events
@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BOT_NAME} VPS Manager"))
    logger.info(f"{BOT_NAME} Bot is ready!")
    
    # Start Flask web SSH server (only once)
    if not hasattr(bot, 'flask_started'):
        def run_flask():
            try:
                logger.info("Starting Flask Web SSH server on http://0.0.0.0:5000")
                app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
            except Exception as e:
                logger.error(f"Flask server error: {e}")
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        bot.flask_started = True
        logger.info("Flask Web SSH server thread started")
    
    # Start auto-save background task (only once)
    if not any(task.get_name() == 'auto_save_task' for task in asyncio.all_tasks()):
        bot.loop.create_task(auto_save_task())

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=create_error_embed("Missing Argument", f"Please check command usage with `{PREFIX}help`."))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=create_error_embed("Invalid Argument", "Please check your input and try again."))
    elif isinstance(error, commands.CheckFailure):
        error_msg = str(error) if str(error) else "You need admin permissions for this command. Contact support."
        await ctx.send(embed=create_error_embed("Access Denied", error_msg))
    elif isinstance(error, discord.NotFound):
        await ctx.send(embed=create_error_embed("Error", "The requested resource was not found. Please try again."))
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(embed=create_error_embed("System Error", "An unexpected error occurred. Support has been notified."))

# Bot commands
@bot.command(name='ping')
async def ping(ctx):
    """Check bot latency"""
    latency = round(bot.latency * 1000)
    embed = create_success_embed(
        "🏓 Pong!",
        f"Bot is responding perfectly!"
    )
    add_field(embed, "Latency", f"`{latency}ms`", inline=True)
    add_field(embed, "Status", "✅ Online", inline=True)
    add_field(embed, "Bot", f"`{BOT_NAME} v{BOT_VERSION}`", inline=True)
    await ctx.send(embed=embed)

@bot.command(name='uptime')
async def uptime(ctx):
    up = get_uptime()
    embed = create_info_embed("Host Uptime", up)
    await ctx.send(embed=embed)

@bot.command(name='thresholds')
@is_admin()
async def thresholds(ctx):
    embed = create_info_embed("Resource Thresholds", f"**CPU:** {CPU_THRESHOLD}%\n**RAM:** {RAM_THRESHOLD}%")
    await ctx.send(embed=embed)

@bot.command(name='set-threshold')
@is_admin()
async def set_threshold(ctx, cpu: int, ram: int):
    global CPU_THRESHOLD, RAM_THRESHOLD
    if cpu < 0 or ram < 0:
        await ctx.send(embed=create_error_embed("Invalid Thresholds", "Thresholds must be non-negative."))
        return
    CPU_THRESHOLD = cpu
    RAM_THRESHOLD = ram
    set_setting('cpu_threshold', str(cpu))
    set_setting('ram_threshold', str(ram))
    embed = create_success_embed("Thresholds Updated", f"**CPU:** {cpu}%\n**RAM:** {ram}%")
    await ctx.send(embed=embed)

@bot.command(name='set-status')
@is_admin()
async def set_status(ctx, activity_type: str, *, name: str):
    types = {
        'playing': discord.ActivityType.playing,
        'watching': discord.ActivityType.watching,
        'listening': discord.ActivityType.listening,
        'streaming': discord.ActivityType.streaming,
    }
    if activity_type.lower() not in types:
        await ctx.send(embed=create_error_embed("Invalid Type", "Valid types: playing, watching, listening, streaming"))
        return
    await bot.change_presence(activity=discord.Activity(type=types[activity_type.lower()], name=name))
    embed = create_success_embed("Status Updated", f"Set to {activity_type}: {name}")
    await ctx.send(embed=embed)

@bot.command(name="myvps")
async def my_vps(ctx):
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])

    # ─── No VPS Case ───────────────────────────────────────────
    if not vps_list:
        embed = create_error_embed(
            "❌ No VPS Found",
            f"You don’t have any **{BOT_NAME} VPS** yet."
        )
        embed.add_field(
            name="🚀 Quick Actions",
            value=(
                f"• `{PREFIX}manage` – Manage VPS\n"
                f"• Contact an admin to request a VPS"
            ),
            inline=False
        )
        await ctx.send(embed=embed)
        return

    # ─── Embed ────────────────────────────────────────────────
    embed = create_info_embed(
        title="🖥️ My VPS Dashboard",
        description="Your personal VPS overview"
    )

    total_vps = len(vps_list)
    running = suspended = whitelisted = 0
    vps_cards = []

    # ─── VPS Processing ───────────────────────────────────────
    for i, vps in enumerate(vps_list, start=1):
        node = get_node(vps.get("node_id"))
        node_name = node["name"] if node else "Unknown"

        config = vps.get("config", "Custom")
        ram = vps.get("ram", "0GB")
        cpu = vps.get("cpu", "0")
        storage = vps.get("storage", "0GB")

        if vps.get("suspended"):
            status = "⛔ SUSPENDED"
            suspended += 1
        elif vps.get("status") == "running":
            status = "🟢 RUNNING"
            running += 1
        else:
            status = "🔴 STOPPED"

        if vps.get("whitelisted"):
            whitelisted += 1

        # Build VPS card
        card = (
            f"**{i}.** `{vps['container_name']}`\n"
            f"{status} • `{config}`\n"
            f"⚙️ `{ram}` RAM • `{cpu}` CPU • `{storage}` Disk\n"
            f"📍 Node: `{node_name}`"
        )
        
        # Add expiration info if set
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                expiration_badge = "🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_badge = "🟡 EXPIRING"
            else:
                expiration_badge = "🟢 ACTIVE"
            
            card += f"\n⏰ {expiration_badge} • Expires: `{expiration_dt.strftime('%Y-%m-%d')}`"
        
        vps_cards.append(card)

    # ─── Row 1 : Summary ──────────────────────────────────────
    embed.add_field(
        name="📊 Summary",
        value=(
            f"🖥️ `{total_vps}` VPS\n"
            f"🟢 `{running}` Running\n"
            f"⛔ `{suspended}` Suspended\n"
            f"✅ `{whitelisted}` Whitelisted"
        ),
        inline=True
    )

    embed.add_field(
        name="⚡ Quick Actions",
        value=(
            f"`{PREFIX}manage`\n"
            f"`{PREFIX}reinstall`\n"
            f"`{PREFIX}status`"
        ),
        inline=True
    )

    embed.add_field(
        name="🧭 Tip",
        value="Use **manage** to control your VPS",
        inline=True
    )

    # ─── VPS Cards (Full Width) ───────────────────────────────
    vps_text = "\n\n".join(vps_cards)
    for i in range(0, len(vps_text), 1024):
        embed.add_field(
            name="🖥️ Your VPS",
            value=vps_text[i:i + 1024],
            inline=False
        )

    embed.set_footer(text=f"Made by AnkitCoder • VPS Control Panel")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name='vps')
async def public_vps_command(ctx, action: str = None, *args):
    """Public VPS command: !vps create, !vps info, !vps help"""
    
    if not PUBLIC_VPS_ENABLED:
        await ctx.send(embed=create_error_embed("Disabled", "Public VPS creation is currently disabled."))
        return
    
    if action is None or action.lower() == 'help':
        embed = discord.Embed(
            title="🖥️ Public VPS Creation System",
            description="Create and manage your free VPS!",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="📖 Available Commands",
            value=(
                f"`{PREFIX}vps create` – Create your VPS\n"
                f"`{PREFIX}vps renew` – Renew your VPS expiration\n"
                f"`{PREFIX}vps info` – View your VPS info\n"
                f"`{PREFIX}vps help` – Show this help message"
            ),
            inline=False
        )
        embed.add_field(
            name="⚙️ VPS Specs",
            value=(
                f"**RAM:** Up to {PUBLIC_VPS_MAX_RAM}GB\n"
                f"**CPU:** Up to {PUBLIC_VPS_MAX_CPU} cores\n"
                f"**Disk:** Up to {PUBLIC_VPS_MAX_DISK}GB\n"
                f"**Expiry:** {PUBLIC_VPS_EXPIRY_DAYS} days"
            ),
            inline=False
        )
        embed.add_field(
            name="📋 Rules",
            value=(
                f"✅ Max {PUBLIC_VPS_MAX_PER_USER} VPS per user\n"
                f"✅ Max {PUBLIC_VPS_MAX_PER_IP} VPS per IP/device\n"
                f"⚠️ Fraud detection enabled\n"
                f"⚠️ Abuse will result in permanent ban"
            ),
            inline=False
        )
        embed.add_field(
            name="🚀 Get Started",
            value=f"Run `{PREFIX}vps create` to start!",
            inline=False
        )
        await ctx.send(embed=embed)
        return
    
    elif action.lower() == 'create':
        await handle_public_vps_creation(ctx)
        return
    
    elif action.lower() == 'info':
        user_id = str(ctx.author.id)
        vps_list = vps_data.get(user_id, [])
        
        if not vps_list:
            await ctx.send(embed=create_error_embed("No VPS", f"You don't have any VPS. Use `{PREFIX}vps create` to create one!"))
            return
        
        embed = discord.Embed(
            title="🖥️ Your VPS Information",
            color=discord.Color.green()
        )
        
        for i, vps in enumerate(vps_list, 1):
            vps_info = (
                f"**Container:** `{vps['container_name']}`\n"
                f"**Status:** {vps.get('status', 'stopped').upper()}\n"
                f"**Config:** {vps.get('config', 'N/A')}\n"
                f"**Created:** {vps.get('created_at', 'N/A')[:10]}"
            )
            if vps.get('expiration_date'):
                exp_date = vps['expiration_date'][:10]
                days_left = (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days
                vps_info += f"\n**Expires:** `{exp_date}` ({days_left} days)"
            
            embed.add_field(name=f"VPS #{i}", value=vps_info, inline=False)
        
        await ctx.send(embed=embed)
        return
    
    elif action.lower() == 'renew':
        await handle_public_vps_renewal(ctx)
        return
    
    else:
        await ctx.send(embed=create_error_embed("Unknown Action", f"Use `{PREFIX}vps help` for available commands."))

async def handle_public_vps_creation(ctx):
    """Handle public VPS creation with fraud detection"""
    user_id = str(ctx.author.id)
    user = ctx.author
    
    # Get user IP identifier
    ip_address = await get_user_ip(ctx)
    
    # Track device
    track_user_device(user_id, ip_address, user)
    
    # Check for fraud indicators
    fraud_check = await check_fraud_indicators(user_id, ip_address, user, ctx)
    
    if fraud_check['is_risky']:
        embed = discord.Embed(
            title="⚠️ Security Check Failed",
            description="Your request cannot be processed due to fraud detection.",
            color=discord.Color.red()
        )
        embed.add_field(
            name="⛔ Flags",
            value="\n".join(fraud_check['flags']) if fraud_check['flags'] else "Multiple fraud indicators detected",
            inline=False
        )
        embed.add_field(
            name="💡 What to do?",
            value="• Contact admins if you believe this is a mistake\n• Wait a few days if your account is new\n• Ensure you're not using multiple accounts",
            inline=False
        )
        await ctx.send(embed=embed, ephemeral=True)
        logger.warning(f"Fraud check failed for {user.name} ({user_id}): Score={fraud_check['fraud_score']}, Flags={fraud_check['flags']}")
        return
    
    # Check if user already has VPS
    if user_id in vps_data and len(vps_data[user_id]) >= PUBLIC_VPS_MAX_PER_USER:
        await ctx.send(embed=create_error_embed(
            "Limit Reached",
            f"You already have {PUBLIC_VPS_MAX_PER_USER} VPS. You can only create 1 VPS per account."
        ), ephemeral=True)
        return
    
    # Show VPS specs confirmation
    embed = discord.Embed(
        title="🚀 Create Your VPS",
        description="Your VPS will be created with the following specifications:",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="⚙️ Default Specifications",
        value=(
            f"**RAM:** {PUBLIC_VPS_MAX_RAM}GB\n"
            f"**CPU:** {PUBLIC_VPS_MAX_CPU} cores\n"
            f"**Disk:** {PUBLIC_VPS_MAX_DISK}GB\n"
            f"**Expiry:** {PUBLIC_VPS_EXPIRY_DAYS} days"
        ),
        inline=False
    )
    embed.add_field(
        name="ℹ️ What's Included",
        value=(
            "✅ Ubuntu 22.04 LTS\n"
            "✅ SSH access with password auth\n"
            "✅ Full root access\n"
            "✅ Port forwarding enabled\n"
            "✅ Docker ready"
        ),
        inline=False
    )
    embed.add_field(
        name="⚠️ Rules",
        value=(
            "• No illegal content\n"
            "• No spam or abuse\n"
            "• No sharing accounts\n"
            "• Violation = permanent ban"
        ),
        inline=False
    )
    
    # Create confirmation view
    class ConfirmCreateView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.confirmed = False
        
        @discord.ui.button(label="✅ Create VPS", style=discord.ButtonStyle.success)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            if str(interaction.user.id) != user_id:
                await interaction.response.send_message("This is not for you!", ephemeral=True)
                return
            
            self.confirmed = True
            await interaction.response.defer(ephemeral=True)
            
            # Create VPS with public specs using the proper view flow
            try:
                loading_embed = create_info_embed("Creating VPS", "Provisioning your VPS... This may take a minute.")
                await interaction.followup.send(embed=loading_embed)
                
                # Use default node (Local Node = 1)
                node_id = 1
                
                # Create the VPS using OSSelectView directly with the default node
                # Get next global VPS ID from database
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT MAX(id) FROM vps")
                max_id = cur.fetchone()[0] or 0
                global_vps_id = max_id + 1
                conn.close()
                
                # Sanitize username for container name
                username = ctx.author.name.lower().replace(" ", "-")[:15]
                sanitized_username = sanitize_username_for_container(username)
                container_name = f"{sanitized_username}-vps-{global_vps_id}"
                ram_mb = PUBLIC_VPS_MAX_RAM * 1024
                
                # Create VPS container
                os_version = "ubuntu:22.04"  # Default OS for public users
                
                await execute_lxc(container_name, f"init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}", node_id=node_id)
                await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=node_id)
                await execute_lxc(container_name, f"config set {container_name} limits.cpu {PUBLIC_VPS_MAX_CPU}", node_id=node_id)
                await execute_lxc(container_name, f"config device set {container_name} root size={PUBLIC_VPS_MAX_DISK}GB", node_id=node_id)
                await apply_lxc_config(container_name, node_id)
                await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
                await apply_internal_permissions(container_name, node_id)
                
                # Generate password
                root_password = generate_strong_password()
                
                # Configure SSH
                success, result = await configure_ssh(container_name, node_id, root_password)
                if not success:
                    logger.warning(f"SSH configuration partially failed: {result}")
                
                # Execute HOST_MOTD
                if HOST_MOTD:
                    try:
                        await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{HOST_MOTD}\"", node_id=node_id)
                    except Exception as e:
                        logger.warning(f"HOST_MOTD execution failed: {e}")
                
                # Create VPS info object
                config_str = f"{PUBLIC_VPS_MAX_RAM}GB RAM / {PUBLIC_VPS_MAX_CPU} CPU / {PUBLIC_VPS_MAX_DISK}GB Disk"
                vps_info = {
                    "container_name": container_name,
                    "node_id": node_id,
                    "ram": f"{PUBLIC_VPS_MAX_RAM}GB",
                    "cpu": str(PUBLIC_VPS_MAX_CPU),
                    "storage": f"{PUBLIC_VPS_MAX_DISK}GB",
                    "config": config_str,
                    "os_version": os_version,
                    "status": "running",
                    "suspended": False,
                    "whitelisted": False,
                    "suspension_history": [],
                    "created_at": datetime.now().isoformat(),
                    "shared_with": [],
                    "expiration_date": (datetime.now() + timedelta(days=PUBLIC_VPS_EXPIRY_DAYS)).isoformat(),
                    "root_password": root_password,
                    "id": global_vps_id
                }
                
                # Add to VPS data
                if user_id not in vps_data:
                    vps_data[user_id] = []
                vps_data[user_id].append(vps_info)
                
                # Allocate port
                try:
                    with DB_LOCK:
                        conn = get_db()
                        existing = conn.execute(
                            "SELECT allocated_ports FROM port_allocations WHERE user_id = ?",
                            (str(user_id),)
                        ).fetchone()
                        
                        if not existing:
                            conn.execute(
                                "INSERT INTO port_allocations (user_id, allocated_ports, last_modified) VALUES (?, 1, CURRENT_TIMESTAMP)",
                                (str(user_id),)
                            )
                            conn.commit()
                        conn.close()
                except Exception as e:
                    logger.warning(f"Could not allocate port: {e}")
                
                save_vps_data_immediate()
                
                # Auto-create SSH port forward
                try:
                    ssh_port = await create_port_forward(str(user_id), container_name, 22, node_id)
                    ssh_command = f"ssh root@{YOUR_SERVER_IP} -p {ssh_port}"
                except Exception as ssh_err:
                    logger.warning(f"Could not auto-create SSH port forward: {ssh_err}")
                    ssh_command = "SSH port forward failed - contact admin"
                
                # Auto-create Web SSH port forward (port 5000 - Flask server)
                try:
                    webssh_port = await create_port_forward(str(user_id), container_name, 5000, node_id)
                    webssh_url = WEBSSH_URL_FORMAT.format(SERVER_IP=YOUR_SERVER_IP, PORT=webssh_port)
                    
                    # Store webssh details in VPS info
                    vps_info['webssh_port'] = webssh_port
                    vps_info['webssh_url'] = webssh_url
                except Exception as webssh_err:
                    logger.warning(f"Could not auto-create Web SSH port forward: {webssh_err}")
                    webssh_url = "Web SSH port forward creation failed - contact admin"
                
                # Send success message
                success_embed = create_success_embed(
                    "🎉 VPS Created Successfully!",
                    "Your new VPS is ready to use!"
                )
                success_embed.add_field(
                    name="📊 VPS Details",
                    value=(
                        f"**Container:** `{container_name}`\n"
                        f"**Configuration:** {config_str}\n"
                        f"**OS:** Ubuntu 22.04 LTS\n"
                        f"**Status:** 🟢 Running\n"
                        f"**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                        f"**Expiration:** {(datetime.now() + timedelta(days=PUBLIC_VPS_EXPIRY_DAYS)).strftime('%Y-%m-%d')}"
                    ),
                    inline=False
                )
                success_embed.add_field(
                    name="🔐 SSH Access",
                    value=(
                        f"**Command:** ```bash\n{ssh_command}\n```\n"
                        f"**Username:** `root`\n"
                        f"**Password:** Check DM\n"
                        f"**Server:** `{YOUR_SERVER_IP}`"
                    ),
                    inline=False
                )
                success_embed.add_field(
                    name="🌐 Web SSH Terminal",
                    value=(
                        f"[🔗 Open Web SSH](file://{webssh_url})\n\n"
                        f"No installation needed!\n"
                        f"Works in any browser"
                    ),
                    inline=False
                )
                success_embed.add_field(
                    name="✨ Features",
                    value=(
                        "✅ Full root access\n"
                        "✅ Docker ready\n"
                        "✅ Port forwarding enabled\n"
                        "✅ Web SSH terminal\n"
                        "✅ 30-day free access"
                    ),
                    inline=False
                )
                
                await interaction.followup.send(embed=success_embed)
                
                # Send DM with credentials
                try:
                    user = await bot.fetch_user(int(user_id))
                    dm_embed = discord.Embed(
                        title="🎉 VPS Created Successfully!",
                        description=f"Your new VPS `{container_name}` is ready!",
                        color=discord.Color.green()
                    )
                    dm_embed.add_field(
                        name="🔐 SSH Access",
                        value=f"```bash\n{ssh_command}\n```",
                        inline=False
                    )
                    dm_embed.add_field(
                        name="📋 Credentials",
                        value=(
                            f"**Username:** `root`\n"
                            f"**Password:** `{root_password}`\n"
                            f"**Server:** `{YOUR_SERVER_IP}`"
                        ),
                        inline=False
                    )
                    dm_embed.add_field(
                        name="🌐 Web SSH Terminal",
                        value=(
                            f"[🔗 Open Web SSH Terminal]({webssh_url})\n\n"
                            f"**Features:**\n"
                            f"✅ Browser-based SSH client\n"
                            f"✅ No software installation\n"
                            f"✅ Works on any device\n"
                            f"✅ Use same credentials"
                        ),
                        inline=False
                    )
                    dm_embed.add_field(
                        name="⏱️ Expiration",
                        value=(
                            f"**Expires:** {(datetime.now() + timedelta(days=PUBLIC_VPS_EXPIRY_DAYS)).strftime('%Y-%m-%d')}\n"
                            f"**Renew:** Use `{PREFIX}vps renew` before expiration"
                        ),
                        inline=False
                    )
                    await user.send(embed=dm_embed)
                except Exception as dm_err:
                    logger.warning(f"Could not send DM: {dm_err}")
                
                logger.info(f"[OK] VPS created for public user {ctx.author.name} ({user_id}): {container_name}")
                
            except Exception as e:
                error_embed = create_error_embed("Creation Failed", f"Error: {str(e)}")
                await interaction.followup.send(embed=error_embed)
                logger.error(f"VPS creation failed for {user_id}: {e}", exc_info=True)
            
            self.stop()
        
        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            if str(interaction.user.id) != user_id:
                await interaction.response.send_message("This is not for you!", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            self.stop()
    
    view = ConfirmCreateView()
    await ctx.send(embed=embed, view=view, ephemeral=True)

@bot.command(name='lxc-list')
@is_admin()
async def lxc_list(ctx, node_id: int = 1):
    try:
        result = await execute_lxc("", "list", node_id=node_id)
        node = get_node(node_id)
        embed = create_info_embed(f"LXC Containers List on {node['name']}", result)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Error", str(e)))

class NodeSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, expiry_days: int = None):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        nodes = get_nodes()
        options = []
        for n in nodes:
            # Show BOTH local and remote nodes for VPS creation (multi-node support)
            current_count = get_current_vps_count(n['id'])
            if current_count < n['total_vps']:
                node_type = "📍 Local" if n['is_local'] else "🌐 Remote"
                options.append(discord.SelectOption(label=f"{n['name']} {node_type}", value=str(n['id']), description=f"{n['location']} - Available: {n['total_vps'] - current_count}"))
        if not options:
            self.add_item(discord.ui.Select(placeholder="No available nodes", disabled=True))
        else:
            self.select = discord.ui.Select(placeholder="Select a Node for the VPS", options=options)
            self.select.callback = self.select_node
            self.add_item(self.select)

    async def select_node(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        node_id = int(self.select.values[0])
        self.select.disabled = True
        await interaction.response.edit_message(view=self)
        os_view = OSSelectView(self.ram, self.cpu, self.disk, self.user, self.ctx, node_id, self.expiry_days)
        await interaction.followup.send(embed=create_info_embed("Select OS", "Choose the OS for the VPS."), view=os_view)

class OSSelectView(discord.ui.View):
    def __init__(self, ram: int, cpu: int, disk: int, user: discord.Member, ctx, node_id: int, expiry_days: int = None):
        super().__init__(timeout=300)
        self.ram = ram
        self.cpu = cpu
        self.disk = disk
        self.user = user
        self.ctx = ctx
        self.node_id = node_id
        self.expiry_days = expiry_days if expiry_days and expiry_days > 0 else DEFAULT_VPS_EXPIRATION_DAYS
        self.select = discord.ui.Select(
            placeholder="Select an OS for the VPS",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        if str(interaction.user.id) != str(self.ctx.author.id):
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "Only the command author can select."), ephemeral=True)
            return
        os_version = self.select.values[0]
        self.select.disabled = True
        creating_embed = create_info_embed("Creating VPS", f"Deploying {os_version} VPS for {self.user.mention} on node {self.node_id}...")
        await interaction.response.edit_message(embed=creating_embed, view=self)
        user_id = str(self.user.id)
        # Create shorter container name with GLOBAL VPS ID
        username = self.user.name.lower().replace(" ", "-")[:15]  # Limit to 15 chars
        
        # Get next global VPS ID from database (auto-increment)
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT MAX(id) FROM vps")
        max_id = cur.fetchone()[0] or 0
        global_vps_id = max_id + 1
        conn.close()
        
        # New naming format: <sanitized-username>-vps-<global-id>
        # Example: ankitcoder-vps-1, alexuser-vps-2, btw-infinite-vps-3
        # Sanitize username: remove underscores, spaces, special chars
        sanitized_username = sanitize_username_for_container(username)
        container_name = f"{sanitized_username}-vps-{global_vps_id}"
        ram_mb = self.ram * 1024
        try:
            await execute_lxc(container_name, f"init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}", node_id=self.node_id)
            await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=self.node_id)
            await execute_lxc(container_name, f"config set {container_name} limits.cpu {self.cpu}", node_id=self.node_id)
            await execute_lxc(container_name, f"config device set {container_name} root size={self.disk}GB", node_id=self.node_id)
            await apply_lxc_config(container_name, self.node_id)
            await execute_lxc(container_name, f"start {container_name}", node_id=self.node_id)
            await apply_internal_permissions(container_name, self.node_id)
            # Don't recreate port forwards here - VPS not in database yet
            # Port forwards will be handled by start_vps command
            
            # Generate strong password
            root_password = generate_strong_password()
            
            # Configure SSH and set password
            success, result = await configure_ssh(container_name, self.node_id, root_password)
            if not success:
                logger.warning(f"SSH configuration partially failed: {result}")
            
            # Execute HOST_MOTD command if configured
            if HOST_MOTD:
                try:
                    await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{HOST_MOTD}\"", node_id=self.node_id)
                    logger.info(f"HOST_MOTD executed on {container_name}")
                except Exception as e:
                    logger.warning(f"HOST_MOTD execution failed for {container_name}: {e}")
            
            config_str = f"{self.ram}GB RAM / {self.cpu} CPU / {self.disk}GB Disk"
            vps_info = {
                "container_name": container_name,
                "node_id": self.node_id,
                "ram": f"{self.ram}GB",
                "cpu": str(self.cpu),
                "storage": f"{self.disk}GB",
                "config": config_str,
                "os_version": os_version,
                "status": "running",
                "suspended": False,
                "whitelisted": False,
                "suspension_history": [],
                "created_at": datetime.now().isoformat(),
                "shared_with": [],
                "expiration_date": (datetime.now() + timedelta(days=self.expiry_days)).isoformat(),
                "root_password": root_password,
                "id": global_vps_id
            }
            logger.info(f"🆕 Creating VPS object: {vps_info['container_name']} for user {user_id}")
            if user_id not in vps_data:
                vps_data[user_id] = []
                logger.info(f"   Created new user entry in vps_data for {user_id}")
            vps_data[user_id].append(vps_info)
            logger.info(f"   [OK] VPS added to vps_data. Total VPS for user: {len(vps_data[user_id])}")
            logger.info(f"   Total users in vps_data: {len(vps_data)}")
            
            # Allocate 1 default port per user for SSH access
            try:
                with DB_LOCK:
                    conn = get_db()
                    # Check if user already has port allocation
                    existing = conn.execute(
                        "SELECT allocated_ports FROM port_allocations WHERE user_id = ?",
                        (str(user_id),)
                    ).fetchone()
                    
                    if not existing:
                        # Give new user 1 default port
                        conn.execute(
                            "INSERT INTO port_allocations (user_id, allocated_ports, last_modified) VALUES (?, 1, CURRENT_TIMESTAMP)",
                            (str(user_id),)
                        )
                        conn.commit()
                        logger.info(f"   [OK] Allocated 1 default port for user {user_id}")
                    conn.close()
            except Exception as e:
                logger.warning(f"Could not allocate port for user {user_id}: {e}")
            
            save_vps_data_immediate()
            logger.info(f"   [OK] save_vps_data_immediate() completed")
            
            # Auto-create SSH port forward (port 22)
            try:
                ssh_port = await create_port_forward(str(user_id), container_name, 22, self.node_id)
                logger.info(f"   [OK] Auto-created SSH port forward: port 22 -> {ssh_port}")
                ssh_command = f"ssh root@{YOUR_SERVER_IP} -p {ssh_port}"
            except Exception as ssh_err:
                logger.warning(f"Could not auto-create SSH port forward: {ssh_err}")
                ssh_command = "SSH port forward creation failed - contact admin"
            
            # Auto-create Web SSH port forward (port 5000 - Flask server)
            try:
                webssh_port = await create_port_forward(str(user_id), container_name, 5000, self.node_id)
                logger.info(f"   [OK] Auto-created Web SSH port forward: port 5000 -> {webssh_port}")
                webssh_url = WEBSSH_URL_FORMAT.format(SERVER_IP=YOUR_SERVER_IP, PORT=webssh_port)
                
                # Store webssh_url in VPS data for easy retrieval
                vps_info['webssh_port'] = webssh_port
                vps_info['webssh_url'] = webssh_url
            except Exception as webssh_err:
                logger.warning(f"Could not auto-create Web SSH port forward: {webssh_err}")
                webssh_url = "Web SSH port forward creation failed - contact admin"
            
            if self.ctx.guild:
                vps_role = await get_or_create_vps_role(self.ctx.guild)
                if vps_role:
                    try:
                        await self.user.add_roles(vps_role, reason=f"{BOT_NAME} VPS ownership granted")
                    except discord.Forbidden:
                        logger.warning(f"Failed to assign VPS role to {self.user.name}")
            success_embed = create_success_embed("VPS Created Successfully")
            add_field(success_embed, "Owner", self.user.mention, True)
            add_field(success_embed, "VPS ID", f"#{global_vps_id}", True)
            add_field(success_embed, "Container", f"`{container_name}`", True)
            add_field(success_embed, "Node", get_node(self.node_id)['name'], True)
            add_field(success_embed, "Resources", f"**RAM:** {self.ram}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.disk}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "SSH Configuration", "✅ Configured (PasswordAuth enabled)", True)
            add_field(success_embed, "🌐 Web SSH Access", f"[🔗 Open Web SSH Terminal]({webssh_url})", False)
            add_field(success_embed, "SSH & Password", "✅ SSH configured for password authentication\n🔐 Root password generated and sent via DM\n📧 Check your DMs for SSH credentials!", False)
            add_field(success_embed, "Features", "Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0", False)
            add_field(success_embed, "Disk Note", "Run `sudo resize2fs /` inside VPS if needed to expand filesystem.", False)
            await interaction.followup.send(embed=success_embed)
            dm_embed = create_success_embed("🎉 VPS Created Successfully!", f"Your new VPS is ready to use!")
            
            # VPS Details Section
            vps_details = f"""
**VPS ID:** #{global_vps_id}
**Container:** `{container_name}`
**Configuration:** {config_str}
**Operating System:** {os_version}
**Status:** 🟢 Running
**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Expiration:** {(datetime.now() + timedelta(days=self.expiry_days)).strftime('%Y-%m-%d %H:%M:%S')} ({self.expiry_days} days)
"""
            add_field(dm_embed, "📊 VPS Details", vps_details.strip(), False)
            
            # Get all network interfaces - with timeout to prevent hanging
            try:
                networks = await asyncio.wait_for(
                    get_container_networks(container_name, self.node_id),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"Timeout getting networks for {container_name}")
                networks = {}
            
            if networks:
                # Format SSH access info with all real interfaces
                ssh_access_info = f"**🔑 Quick SSH Command (External):**\n```bash\n{ssh_command}\n```\n\n**🖥️ Available Connection Points (Internal):**\n"
                for interface, ip in sorted(networks.items()):
                    ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                ssh_access_info += f"\n**🔑 Login Credentials:**\n"
                ssh_access_info += f"**Username:** `root`\n"
                ssh_access_info += f"**Password:** `{root_password}`\n"
                ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
            else:
                # If no interfaces found, still show credentials (important!)
                ssh_access_info = f"**🔑 SSH Command:**\n```bash\n{ssh_command}\n```\n\n**🔑 Login Credentials:**\n"
                ssh_access_info += f"**Username:** `root`\n"
                ssh_access_info += f"**Password:** `{root_password}`\n"
                ssh_access_info += f"\n**📡 Network Setup:**\n"
                ssh_access_info += "Your VPS is initializing its network interfaces.\n"
                ssh_access_info += "They will be available in a few seconds.\n"
                ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
            
            add_field(dm_embed, "🔐 SSH Credentials & Access", ssh_access_info, False)
            
            # Web SSH Section
            webssh_info = f"**🌐 Web SSH Terminal (Browser-Based SSH)**\n"
            webssh_info += f"```\n{webssh_url}\n```\n"
            webssh_info += f"**Features:**\n"
            webssh_info += f"✅ No installation required\n"
            webssh_info += f"✅ Works in any modern browser\n"
            webssh_info += f"✅ Same credentials as SSH\n"
            webssh_info += f"✅ Port forward auto-setup: `127.0.0.1:5000`"
            add_field(dm_embed, "🌐 Web SSH Terminal", webssh_info, False)
            
            # SSH Features
            features_info = """✅ **SSH:** Password authentication enabled
✅ **SFTP:** File transfer available
✅ **Root:** Full root access granted
✅ **Ports:** All ports available for forwarding
✅ **Docker:** Nesting, privileged mode, FUSE enabled
✅ **Features:** Complete Linux container with full capabilities"""
            add_field(dm_embed, "⚙️ Features & Capabilities", features_info, False)
            
            # Support Section
            support_info = f"""**Need Help?**
• Use `{PREFIX}manage` to start/stop/reinstall your VPS
• Click 🔐 in manage to regenerate password
• Contact admin for issues or upgrades
• Check logs with: `journalctl -xe`"""
            add_field(dm_embed, "📞 Support & Management", support_info, False)
            try:
                await self.user.send(embed=dm_embed)
            except discord.Forbidden:
                await self.ctx.send(embed=create_info_embed("Notification Failed", f"Couldn't send DM to {self.user.mention}. Please ensure DMs are enabled."))
        except Exception as e:
            error_embed = create_error_embed("Creation Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed)

@bot.command(name='create')
@is_admin()
async def create_vps(ctx, ram: int, cpu: int, disk: int, user: discord.Member, expiry_days: int = None):
    if ram <= 0 or cpu <= 0 or disk <= 0:
        await ctx.send(embed=create_error_embed("Invalid Specs", "RAM, CPU, and Disk must be positive integers."))
        return
    
    # Validate expiry_days if provided
    if expiry_days is not None and expiry_days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Expiry Days", "Expiry days must be a positive integer."))
        return
    
    expiry_text = f" with {expiry_days} days expiry" if expiry_days else f" with {DEFAULT_VPS_EXPIRATION_DAYS} days expiry (default)"
    embed = create_info_embed("VPS Creation", f"Creating VPS for {user.mention} with {ram}GB RAM, {cpu} CPU cores, {disk}GB Disk{expiry_text}.\nSelect node below.")
    view = NodeSelectView(ram, cpu, disk, user, ctx, expiry_days)
    await ctx.send(embed=embed, view=view)

class ReinstallOSSelectView(discord.ui.View):
    def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
        super().__init__(timeout=300)
        self.parent_view = parent_view
        self.container_name = container_name
        self.owner_id = owner_id
        self.actual_idx = actual_idx
        self.ram_gb = ram_gb
        self.cpu = cpu
        self.storage_gb = storage_gb
        self.node_id = node_id
        self.select = discord.ui.Select(
            placeholder="Select an OS for the reinstall",
            options=[discord.SelectOption(label=o["label"], value=o["value"]) for o in OS_OPTIONS]
        )
        self.select.callback = self.select_os
        self.add_item(self.select)

    async def select_os(self, interaction: discord.Interaction):
        os_version = self.select.values[0]
        self.select.disabled = True
        creating_embed = create_info_embed("Reinstalling VPS", f"Deploying {os_version} for `{self.container_name}`...")
        await interaction.response.edit_message(embed=creating_embed, view=self)
        ram_mb = self.ram_gb * 1024
        
        # Generate new password for reinstall
        new_password = generate_strong_password()
        
        try:
            # No need to delete again; already deleted in confirmation
            await execute_lxc(self.container_name, f"init {os_version} {self.container_name} -s {DEFAULT_STORAGE_POOL}", node_id=self.node_id)
            await execute_lxc(self.container_name, f"config set {self.container_name} limits.memory {ram_mb}MB", node_id=self.node_id)
            await execute_lxc(self.container_name, f"config set {self.container_name} limits.cpu {self.cpu}", node_id=self.node_id)
            await execute_lxc(self.container_name, f"config device set {self.container_name} root size={self.storage_gb}GB", node_id=self.node_id)
            await apply_lxc_config(self.container_name, self.node_id)
            await execute_lxc(self.container_name, f"start {self.container_name}", node_id=self.node_id)
            await apply_internal_permissions(self.container_name, self.node_id)
            
            # Configure SSH and set new password
            success, result = await configure_ssh(self.container_name, self.node_id, new_password)
            if not success:
                logger.warning(f"SSH configuration partially failed: {result}")
            
            # Execute HOST_MOTD command if configured
            if HOST_MOTD:
                try:
                    await execute_lxc(self.container_name, f"exec {self.container_name} -- bash -c \"{HOST_MOTD}\"", node_id=self.node_id)
                    logger.info(f"HOST_MOTD executed on {self.container_name}")
                except Exception as e:
                    logger.warning(f"HOST_MOTD execution failed for {self.container_name}: {e}")
            
            # Don't recreate port forwards here - save to database first
            target_vps = vps_data[self.owner_id][self.actual_idx]
            target_vps["os_version"] = os_version
            target_vps["status"] = "running"
            target_vps["suspended"] = False
            target_vps["created_at"] = datetime.now().isoformat()
            target_vps["root_password"] = new_password
            config_str = f"{self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk"
            target_vps["config"] = config_str
            # IMPORTANT: Preserve expiration date during reinstall
            # If expiration_date is missing or None, set it to current expiration + DEFAULT_VPS_EXPIRATION_DAYS
            if not target_vps.get('expiration_date'):
                # No expiration was set, so set it now
                target_vps['expiration_date'] = (datetime.now() + timedelta(days=DEFAULT_VPS_EXPIRATION_DAYS)).isoformat()
            # If expiration_date exists, keep it as is - don't reset on reinstall
            save_vps_data_immediate()
            
            # Recreate all port forwards (SSH and others) after reinstall - preserves all forwarding rules
            try:
                readded = await recreate_port_forwards(self.container_name)
                logger.info(f"[OK] Recreated {readded} port forwards after reinstall for {self.container_name}")
            except Exception as e:
                logger.warning(f"Could not recreate port forwards after reinstall: {e}")
            success_embed = create_success_embed("Reinstall Complete", f"VPS `{self.container_name}` has been successfully reinstalled!")
            add_field(success_embed, "Resources", f"**RAM:** {self.ram_gb}GB\n**CPU:** {self.cpu} Cores\n**Storage:** {self.storage_gb}GB", False)
            add_field(success_embed, "OS", os_version, True)
            add_field(success_embed, "SSH Configuration", "✅ Configured (PasswordAuth enabled)\n🔐 New password generated and sent via DM", True)
            add_field(success_embed, "Features", "Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0", False)
            add_field(success_embed, "Disk Note", "Run `sudo resize2fs /` inside VPS if needed to expand filesystem.", False)
            await interaction.followup.send(embed=success_embed, ephemeral=True)
            
            # Send DM to owner with new password
            try:
                owner = await bot.fetch_user(int(self.owner_id))
                dm_embed = create_success_embed("🔄 VPS Reinstalled Successfully!", f"Your VPS `{self.container_name}` is ready with a new operating system!")
                
                # VPS Details Section
                vps_details = f"""
**Container:** `{self.container_name}`
**New OS:** {os_version}
**Configuration:** {self.ram_gb}GB RAM / {self.cpu} CPU / {self.storage_gb}GB Disk
**Status:** 🟢 Running
**Reinstalled:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
                add_field(dm_embed, "📊 VPS Details", vps_details.strip(), False)
                
                # Get all network interfaces - with timeout to prevent hanging
                try:
                    networks = await asyncio.wait_for(
                        get_container_networks(self.container_name, self.node_id),
                        timeout=3.0
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout getting networks for {self.container_name}")
                    networks = {}
                
                if networks:
                    # Get SSH port forward if available
                    try:
                        with DB_LOCK:
                            conn = get_db()
                            ssh_forward = conn.execute(
                                "SELECT host_port FROM port_forwards WHERE vps_container = ? AND vps_port = 22",
                                (self.container_name,)
                            ).fetchone()
                            conn.close()
                        
                        if ssh_forward:
                            ssh_port = ssh_forward[0]
                            ssh_command = f"ssh root@{YOUR_SERVER_IP} -p {ssh_port}"
                            ssh_access_info = f"**🔑 Quick SSH Command (External):**\n```bash\n{ssh_command}\n```\n\n**🖥️ Available Connection Points (Internal):**\n"
                        else:
                            ssh_access_info = "**🖥️ Available Connection Points:**\n"
                    except:
                        ssh_access_info = "**🖥️ Available Connection Points:**\n"
                    
                    for interface, ip in sorted(networks.items()):
                        ssh_access_info += f"└─ **{interface}:** `ssh root@{ip}`\n"
                    ssh_access_info += f"\n**🔑 New Login Credentials:**\n"
                    ssh_access_info += f"**Username:** `root`\n"
                    ssh_access_info += f"**Password:** `{new_password}`\n"
                    ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
                else:
                    # If no interfaces found, still show credentials (important!)
                    # Try to get SSH port forward
                    try:
                        with DB_LOCK:
                            conn = get_db()
                            ssh_forward = conn.execute(
                                "SELECT host_port FROM port_forwards WHERE vps_container = ? AND vps_port = 22",
                                (self.container_name,)
                            ).fetchone()
                            conn.close()
                        
                        if ssh_forward:
                            ssh_port = ssh_forward[0]
                            ssh_command = f"ssh root@{YOUR_SERVER_IP} -p {ssh_port}"
                            ssh_access_info = f"**🔑 SSH Command:**\n```bash\n{ssh_command}\n```\n\n"
                        else:
                            ssh_access_info = ""
                    except:
                        ssh_access_info = ""
                    
                    ssh_access_info += "**🔑 New Login Credentials:**\n"
                    ssh_access_info += f"**Username:** `root`\n"
                    ssh_access_info += f"**Password:** `{new_password}`\n"
                    ssh_access_info += f"\n**📡 Network Setup:**\n"
                    ssh_access_info += "Your VPS is initializing its network interfaces.\n"
                    ssh_access_info += "They will be available in a few seconds.\n"
                    ssh_access_info += f"\n**⚠️ Important:** Save this password securely!"
                
                add_field(dm_embed, "🔐 SSH Credentials & Access", ssh_access_info, False)
                
                # SSH Features
                features_info = """✅ **SSH:** Password authentication enabled
✅ **SFTP:** File transfer available
✅ **Root:** Full root access granted
✅ **Ports:** All ports available for forwarding
✅ **Docker:** Nesting, privileged mode, FUSE enabled
✅ **Fresh:** Clean OS installation ready to use"""
                add_field(dm_embed, "⚙️ Features & Capabilities", features_info, False)
                
                # Support Section
                support_info = f"""**Need Help?**
• Use `{PREFIX}manage` to manage your VPS
• Click 🔐 in manage to regenerate password
• Contact admin for issues or upgrades
• Your data from the previous OS has been wiped"""
                add_field(dm_embed, "📞 Support & Management", support_info, False)
                
                await owner.send(embed=dm_embed)
            except Exception as e:
                logger.warning(f"Failed to send reinstall DM to {self.owner_id}: {e}")
            
            self.stop()
        except Exception as e:
            error_embed = create_error_embed("Reinstall Failed", f"Error: {str(e)}")
            await interaction.followup.send(embed=error_embed, ephemeral=True)
            self.stop()

class ManageView(discord.ui.View):
    def __init__(self, user_id, vps_list, is_shared=False, owner_id=None, is_admin=False, actual_index: Optional[int] = None):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.vps_list = vps_list[:]
        self.selected_index = None
        self.is_shared = is_shared
        self.owner_id = owner_id or user_id
        self.is_admin = is_admin
        self.actual_index = actual_index
        self.indices = list(range(len(vps_list)))
        if self.is_shared and self.actual_index is None:
            raise ValueError("actual_index required for shared views")
        if len(vps_list) > 1:
            options = [
                discord.SelectOption(
                    label=f"VPS {i+1} ({v.get('config', 'Custom')})",
                    description=f"Status: {v.get('status', 'unknown')}",
                    value=str(i)
                ) for i, v in enumerate(vps_list)
            ]
            self.select = discord.ui.Select(placeholder="Select a VPS to manage", options=options)
            self.select.callback = self.select_vps
            self.add_item(self.select)
            self.initial_embed = create_embed("VPS Management", "Select a VPS from the dropdown menu below.", 0x1a1a1a)
            add_field(self.initial_embed, "Available VPS", "\n".join([f"**VPS {i+1}:** `{v['container_name']}` - Status: `{v.get('status', 'unknown').upper()}`" for i, v in enumerate(vps_list)]), False)
        else:
            self.selected_index = 0
            self.initial_embed = None
            self.add_action_buttons()

    async def get_initial_embed(self):
        if self.initial_embed is not None:
            return self.initial_embed
        self.initial_embed = await self.create_vps_embed(self.selected_index)
        return self.initial_embed

    async def create_vps_embed(self, index):
        vps = self.vps_list[index]
        node = get_node(vps['node_id'])
        node_name = node['name'] if node else "Unknown"
        status = vps.get('status', 'unknown')
        suspended = vps.get('suspended', False)
        whitelisted = vps.get('whitelisted', False)
        status_color = 0x00ff88 if status == 'running' and not suspended else 0xffaa00 if suspended else 0xff3366
        container_name = vps['container_name']
        stats = await get_container_stats(container_name, vps['node_id'])
        # Use stored VPS status, not stats status (stats status may be unknown for remote nodes)
        status_text = f"{status.upper()}"
        if suspended:
            status_text += " (SUSPENDED)"
        if whitelisted:
            status_text += " (WHITELISTED)"
        owner_text = ""
        if self.is_admin and self.owner_id != self.user_id:
            try:
                owner_user = await bot.fetch_user(int(self.owner_id))
                owner_text = f"\n**Owner:** {owner_user.mention}"
            except:
                owner_text = f"\n**Owner ID:** {self.owner_id}"
        embed = create_embed(
            f"VPS Management - VPS {index + 1}",
            f"Managing container: `{container_name}` on node {node_name}{owner_text}",
            status_color
        )
        resource_info = f"**Configuration:** {vps.get('config', 'Custom')}\n"
        resource_info += f"**Status:** `{status_text}`\n"
        resource_info += f"**RAM:** {vps['ram']}\n"
        resource_info += f"**CPU:** {vps['cpu']} Cores\n"
        resource_info += f"**Storage:** {vps['storage']}\n"
        resource_info += f"**OS:** {vps.get('os_version', 'ubuntu:22.04')}\n"
        resource_info += f"**Uptime:** {stats['uptime']}"
        add_field(embed, "📊 Allocated Resources", resource_info, False)
        
        # Add expiration info
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                expiration_status = "🔴 EXPIRED"
                expiration_color = 0xff3366
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_status = "🟡 EXPIRING SOON"
                expiration_color = 0xffaa00
            else:
                expiration_status = "🟢 ACTIVE"
                expiration_color = 0x00ff88
            
            expiration_info = f"**Status:** {expiration_status}\n"
            expiration_info += f"**Expires:** {expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}\n"
            expiration_info += f"**Days Left:** {max(0, days_remaining)} days"
            add_field(embed, "⏰ Expiration", expiration_info, False)
        else:
            add_field(embed, "⏰ Expiration", "No expiration date set", False)
        
        if suspended:
            add_field(embed, "⚠️ Suspended", "This VPS is suspended. Contact an admin to unsuspend.", False)
        if whitelisted:
            add_field(embed, "✅ Whitelisted", "This VPS is exempt from auto-suspension.", False)
        
        # Safely build live stats (handle unknown values)
        cpu_usage = f"{stats.get('cpu', 0):.1f}%" if stats.get('cpu') is not None else "Unknown"
        ram_data = stats.get('ram', {})
        ram_used = ram_data.get('used', 0) if isinstance(ram_data, dict) else 0
        ram_total = ram_data.get('total', 0) if isinstance(ram_data, dict) else 0
        ram_pct = ram_data.get('pct', 0.0) if isinstance(ram_data, dict) else 0.0
        ram_str = f"{ram_used}/{ram_total} MB ({ram_pct:.1f}%)" if ram_total > 0 else "Unknown"
        disk_usage = stats.get('disk', 'Unknown')
        
        live_stats = f"**CPU Usage:** {cpu_usage}\n**Memory:** {ram_str}\n**Disk:** {disk_usage}"
        add_field(embed, "📈 Live Usage", live_stats, False)
        add_field(embed, "🎮 Controls", "Use the buttons below to manage your VPS", False)
        return embed

    def add_action_buttons(self):
        if not self.is_shared and not self.is_admin:
            reinstall_button = discord.ui.Button(label="🔄 Reinstall", style=discord.ButtonStyle.danger)
            reinstall_button.callback = lambda inter: self.action_callback(inter, 'reinstall')
            self.add_item(reinstall_button)
        
        # Add SSH button
        ssh_button = discord.ui.Button(label="🖥️ Web SSH", style=discord.ButtonStyle.primary)
        ssh_button.callback = lambda inter: self.action_callback(inter, 'webssh')
        
        start_button = discord.ui.Button(label="▶ Start", style=discord.ButtonStyle.success)
        start_button.callback = lambda inter: self.action_callback(inter, 'start')
        stop_button = discord.ui.Button(label="⏸ Stop", style=discord.ButtonStyle.secondary)
        stop_button.callback = lambda inter: self.action_callback(inter, 'stop')
        password_button = discord.ui.Button(label="🔐 Regen Password", style=discord.ButtonStyle.primary)
        password_button.callback = lambda inter: self.action_callback(inter, 'regen_password')
        stats_button = discord.ui.Button(label="📊 Stats", style=discord.ButtonStyle.secondary)
        stats_button.callback = lambda inter: self.action_callback(inter, 'stats')
        
        self.add_item(ssh_button)
        self.add_item(start_button)
        self.add_item(stop_button)
        self.add_item(password_button)
        self.add_item(stats_button)

    async def select_vps(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.response.send_message(embed=create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
            return
        self.selected_index = int(self.select.values[0])
        await interaction.response.defer()
        new_embed = await self.create_vps_embed(self.selected_index)
        self.clear_items()
        self.add_action_buttons()
        await interaction.edit_original_response(embed=new_embed, view=self)

    async def action_callback(self, interaction: discord.Interaction, action: str):
        # Defer immediately to prevent interaction timeout (3-second window)
        try:
            await interaction.response.defer(ephemeral=True)
        except:
            # Already responded or interaction expired
            return
        
        if str(interaction.user.id) != self.user_id and not self.is_admin:
            await interaction.followup.send(embed=create_error_embed("Access Denied", "This is not your VPS!"), ephemeral=True)
            return
        if self.selected_index is None:
            await interaction.followup.send(embed=create_error_embed("No VPS Selected", "Please select a VPS first."), ephemeral=True)
            return
        actual_idx = self.actual_index if self.is_shared else self.indices[self.selected_index]
        target_vps = vps_data[self.owner_id][actual_idx]
        suspended = target_vps.get('suspended', False)
        if suspended and not self.is_admin and action != 'stats':
            await interaction.followup.send(embed=create_error_embed("Access Denied", "This VPS is suspended. Contact an admin to unsuspend."), ephemeral=True)
            return
        container_name = target_vps["container_name"]
        node_id = target_vps['node_id']
        if action == 'stats':
            try:
                stats = await get_container_stats(container_name, node_id)
                stats_embed = create_info_embed("📈 Live Statistics", f"Real-time stats for `{container_name}`")
                add_field(stats_embed, "Status", f"`{stats['status'].upper()}`", True)
                add_field(stats_embed, "CPU", f"{stats['cpu']:.1f}%", True)
                add_field(stats_embed, "Memory", f"{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)", True)
                add_field(stats_embed, "Disk", stats['disk'], True)
                add_field(stats_embed, "Uptime", stats['uptime'], True)
                await interaction.followup.send(embed=stats_embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Stats Failed", str(e)), ephemeral=True)
            return
        
        if action == 'webssh':
            try:
                # Get webssh URL from VPS data or generate it
                webssh_url = target_vps.get('webssh_url')
                webssh_port = target_vps.get('webssh_port')
                
                # If not found in VPS data, try to fetch from database
                if not webssh_port:
                    conn = get_db()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT host_port FROM port_forwards 
                        WHERE vps_container = ? AND vps_port = 5000
                        LIMIT 1
                    """, (container_name,))
                    result = cursor.fetchone()
                    conn.close()
                    
                    if result:
                        webssh_port = result[0]
                        webssh_url = WEBSSH_URL_FORMAT.format(SERVER_IP=YOUR_SERVER_IP, PORT=webssh_port)
                
                # If still not found, show generic message with server info
                if not webssh_port:
                    webssh_embed = create_info_embed(
                        "[OK] Web SSH Terminal - Manual Connection",
                        "Use the connection details below to connect to your VPS via Web SSH"
                    )
                    add_field(webssh_embed, "SSH Connection Details", 
                        f"**Server IP:** {YOUR_SERVER_IP}\n"
                        f"**SSH Port:** 22 (or your forwarded port)\n"
                        f"**Username:** root\n"
                        f"**Password:** From your VPS creation DM", False)
                    add_field(webssh_embed, "How to Connect",
                        f"1. Use Web SSH at: {WEBSSH_URL_FORMAT.format(SERVER_IP=YOUR_SERVER_IP, PORT='YOUR_FORWARDED_PORT')}\n"
                        f"2. Or use SSH command:\n"
                        f"   `ssh root@{YOUR_SERVER_IP} -p PORT`\n"
                        f"3. Enter your password when prompted", False)
                    
                    await interaction.followup.send(embed=webssh_embed, ephemeral=True)
                    return
                
                webssh_embed = create_info_embed(
                    "[OK] Web SSH Terminal",
                    f"Click link to access: {webssh_url}"
                )
                add_field(webssh_embed, "SSH Connection Details", 
                    f"**Server IP:** {YOUR_SERVER_IP}\n"
                    f"**Port:** {webssh_port}\n"
                    f"**Username:** root\n"
                    f"**Password:** From DM", False)
                add_field(webssh_embed, "How to Connect",
                    f"1. Click link above OR\n"
                    f"2. Enter in Web SSH:\n"
                    f"   - Host: {YOUR_SERVER_IP}\n"
                    f"   - Port: {webssh_port}\n"
                    f"   - Username: root\n"
                    f"   - Password: (from DM)\n"
                    f"3. Type commands in terminal", False)
                
                await interaction.followup.send(embed=webssh_embed, ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("WebSSH Error", str(e)), ephemeral=True)
            return
        if action == 'reinstall':
            if self.is_shared or self.is_admin:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Only the VPS owner can reinstall!"), ephemeral=True)
                return
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Cannot Reinstall", "Unsuspend the VPS first."), ephemeral=True)
                return
            ram_gb = int(target_vps['ram'].replace('GB', ''))
            cpu = int(target_vps['cpu'])
            storage_gb = int(target_vps['storage'].replace('GB', ''))
            confirm_embed = create_warning_embed("Reinstall Warning",
                f"⚠️ **WARNING:** This will erase all data on VPS `{container_name}` and reinstall a fresh OS.\n\n"
                f"This action cannot be undone. Continue?")
            class ConfirmView(discord.ui.View):
                def __init__(self, parent_view, container_name, owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id):
                    super().__init__(timeout=60)
                    self.parent_view = parent_view
                    self.container_name = container_name
                    self.owner_id = owner_id
                    self.actual_idx = actual_idx
                    self.ram_gb = ram_gb
                    self.cpu = cpu
                    self.storage_gb = storage_gb
                    self.node_id = node_id

                @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
                async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                    await inter.response.defer(ephemeral=True)
                    try:
                        await inter.followup.send(embed=create_info_embed("Deleting Container", f"Forcefully removing container `{self.container_name}`..."), ephemeral=True)
                        await execute_lxc(self.container_name, f"delete {self.container_name} --force", node_id=self.node_id)
                        os_view = ReinstallOSSelectView(self.parent_view, self.container_name, self.owner_id, self.actual_idx, self.ram_gb, self.cpu, self.storage_gb, self.node_id)
                        await inter.followup.send(embed=create_info_embed("Select OS", "Choose the new OS for reinstallation."), view=os_view, ephemeral=True)
                    except Exception as e:
                        await inter.followup.send(embed=create_error_embed("Delete Failed", f"Error: {str(e)}"), ephemeral=True)

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                    new_embed = await self.parent_view.create_vps_embed(self.parent_view.selected_index)
                    await inter.response.edit_message(embed=new_embed, view=self.parent_view)

            await interaction.followup.send(embed=confirm_embed, view=ConfirmView(self, container_name, self.owner_id, actual_idx, ram_gb, cpu, storage_gb, node_id), ephemeral=True)
            return
        
        suspended = target_vps.get('suspended', False)
        if suspended:
            target_vps['suspended'] = False
            save_vps_data_immediate()
        if action == 'start':
            try:
                # Check current status to avoid "already running" error
                current_status = target_vps.get('status', 'stopped')
                if current_status == 'running':
                    await interaction.followup.send(embed=create_info_embed("Already Running", f"VPS `{container_name}` is already running."), ephemeral=True)
                    return
                
                await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
                target_vps["status"] = "running"
                save_vps_data_immediate()
                await apply_internal_permissions(container_name, node_id)
                readded = await recreate_port_forwards(container_name)
                await interaction.followup.send(embed=create_success_embed("VPS Started", f"VPS `{container_name}` is now running! Re-added {readded} port forwards."), ephemeral=True)
            except Exception as e:
                # If error is "already running", update status
                error_str = str(e).lower()
                if "already running" in error_str:
                    target_vps["status"] = "running"
                    save_vps_data_immediate()
                    await interaction.followup.send(embed=create_success_embed("VPS Started", f"VPS `{container_name}` is running!"), ephemeral=True)
                else:
                    await interaction.followup.send(embed=create_error_embed("Start Failed", str(e)), ephemeral=True)
        elif action == 'stop':
            try:
                # Check current status to avoid "not running" error
                current_status = target_vps.get('status', 'stopped')
                if current_status == 'stopped':
                    await interaction.followup.send(embed=create_info_embed("Already Stopped", f"VPS `{container_name}` is already stopped."), ephemeral=True)
                    return
                
                await execute_lxc(container_name, f"stop {container_name}", timeout=120, node_id=node_id)
                target_vps["status"] = "stopped"
                save_vps_data_immediate()
                await interaction.followup.send(embed=create_success_embed("VPS Stopped", f"VPS `{container_name}` has been stopped!"), ephemeral=True)
            except Exception as e:
                # If error is "not running", update status
                error_str = str(e).lower()
                if "not running" in error_str or "is not running" in error_str:
                    target_vps["status"] = "stopped"
                    save_vps_data_immediate()
                    await interaction.followup.send(embed=create_success_embed("VPS Stopped", f"VPS `{container_name}` is stopped!"), ephemeral=True)
                else:
                    await interaction.followup.send(embed=create_error_embed("Stop Failed", str(e)), ephemeral=True)
        elif action == 'sshx':
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Cannot access suspended VPS."), ephemeral=True)
                return
            await interaction.followup.send(embed=create_info_embed("SSH Access", "Generating SSH connection..."), ephemeral=True)
            try:
                # Check if VPS is running first
                current_status = target_vps.get('status', 'stopped')
                if current_status != 'running':
                    await interaction.followup.send(embed=create_error_embed("VPS Not Running", "Start the VPS before accessing SSH."), ephemeral=True)
                    return
                
                # Check if SSH port forward already exists for this VPS
                with DB_LOCK:
                    conn = get_db()
                    existing_forward = conn.execute(
                        "SELECT host_port FROM port_forwards WHERE vps_container = ? AND vps_port = 22",
                        (container_name,)
                    ).fetchone()
                    conn.close()
                
                host_port = None
                if existing_forward:
                    # Reuse existing port forward
                    host_port = existing_forward[0]
                    logger.info(f"Reusing existing SSH port forward for {container_name}: {host_port}")
                else:
                    # Create new SSH port forward
                    logger.info(f"Creating new SSH port forward for {container_name}")
                    host_port = await create_port_forward(self.owner_id, container_name, 22, node_id)
                    
                    if not host_port:
                        await interaction.followup.send(embed=create_error_embed("Port Forward Failed", "Could not allocate port for SSH access."), ephemeral=True)
                        return
                
                # Send SSH command via DM
                ssh_command = f"ssh root@{YOUR_SERVER_IP} -p {host_port}"
                
                try:
                    user = await bot.fetch_user(int(self.owner_id))
                    embed = discord.Embed(
                        title="🔐 SSH Access - Port Forward Ready",
                        description="Use this command to access your VPS:",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="SSH Command",
                        value=f"```bash\n{ssh_command}\n```",
                        inline=False
                    )
                    embed.add_field(
                        name="Server",
                        value=YOUR_SERVER_IP,
                        inline=True
                    )
                    embed.add_field(
                        name="Port",
                        value=str(host_port),
                        inline=True
                    )
                    embed.add_field(
                        name="Container",
                        value=container_name,
                        inline=False
                    )
                    embed.add_field(
                        name="Username",
                        value="root",
                        inline=True
                    )
                    embed.add_field(
                        name="Password",
                        value=target_vps.get('root_password', 'Check VPS details'),
                        inline=True
                    )
                    embed.set_footer(text="⚠️ Keep this private - do not share your SSH details!")
                    
                    await user.send(embed=embed)
                    await interaction.followup.send(
                        embed=create_success_embed(
                            "✅ SSH Access Ready",
                            f"Port forward created! SSH command sent to DM.\n\n**Port**: {host_port}"
                        ),
                        ephemeral=True
                    )
                    logger.info(f"SSH port forward {host_port} sent to user {self.owner_id} for {container_name}")
                except discord.Forbidden:
                    # If DM fails, show in channel
                    await interaction.followup.send(
                        embed=create_success_embed(
                            "✅ SSH Access Ready",
                            f"```bash\n{ssh_command}\n```\n**Port**: {host_port}"
                        ),
                        ephemeral=True
                    )
            except Exception as e:
                logger.error(f"SSH port forward error: {e}", exc_info=True)
                await interaction.followup.send(embed=create_error_embed("SSH Error", str(e)[:500]), ephemeral=True)
        elif action == 'regen_password':
            if suspended:
                await interaction.followup.send(embed=create_error_embed("Access Denied", "Cannot regenerate password for suspended VPS."), ephemeral=True)
                return
            try:
                # Generate new strong password
                new_password = generate_strong_password()
                
                # Configure SSH and set new password
                success, result = await configure_ssh(container_name, node_id, new_password)
                if success:
                    password_embed = create_success_embed("Password Regenerated", f"New root password generated for `{container_name}`")
                    add_field(password_embed, "🔐 New Password", f"`{new_password}`\n*Save this password securely!*", False)
                    add_field(password_embed, "ℹ️ Note", "You can now SSH into your VPS with the new password.", False)
                    await interaction.followup.send(embed=password_embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=create_error_embed("Regen Failed", str(result)), ephemeral=True)
            except Exception as e:
                await interaction.followup.send(embed=create_error_embed("Error", f"Failed to regenerate password: {str(e)}"), ephemeral=True)
        new_embed = await self.create_vps_embed(self.selected_index)
        await interaction.edit_original_response(embed=new_embed, view=self)

@bot.command(name='manage')
async def manage_vps(ctx, user: discord.Member = None):
    if user:
        if str(ctx.author.id) != str(MAIN_ADMIN_ID) and str(ctx.author.id) not in admin_data.get("admins", []):
            await ctx.send(embed=create_error_embed("Access Denied", "Only admins can manage other users' VPS."))
            return
        user_id = str(user.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            await ctx.send(embed=create_error_embed("No VPS Found", f"{user.mention} doesn't have any {BOT_NAME} VPS."))
            return
        view = ManageView(str(ctx.author.id), vps_list, is_admin=True, owner_id=user_id)
        await ctx.send(embed=create_info_embed(f"Managing {user.name}'s VPS", f"Managing VPS for {user.mention}"), view=view)
    else:
        user_id = str(ctx.author.id)
        vps_list = vps_data.get(user_id, [])
        if not vps_list:
            embed = create_error_embed("No VPS Found", f"You don't have any {BOT_NAME} VPS. Contact an admin to create one.")
            add_field(embed, "Quick Actions", f"• `{PREFIX}manage` - Manage VPS\n• Contact admin for VPS creation", False)
            await ctx.send(embed=embed)
            return
        view = ManageView(user_id, vps_list)
        embed = await view.get_initial_embed()
        await ctx.send(embed=embed, view=view)

async def get_node_status(node_id: int) -> str:
    node = get_node(node_id)
    if not node:
        return "❓ Unknown"
    if node['is_local']:
        return "🟢 Online (Local)"
    # Remote nodes - check connectivity but don't spam errors
    try:
        response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
        if response.status_code == 200:
            return "🟢 Online"
        else:
            return "🔴 Offline (Network unreachable)"
    except requests.exceptions.ConnectionError:
        return "🔴 Unreachable (Network issue)"
    except requests.exceptions.Timeout:
        return "🔴 No response"
    except Exception:
        return "🔴 Offline"


def get_host_disk_usage():
    """Get host disk usage - cross-platform compatible"""
    try:
        import platform
        system = platform.system()
        
        if system == "Windows":
            # Windows: Use wmic or psutil
            try:
                import psutil
                disk = psutil.disk_usage('/')
                return f"{disk.used // (1024**3)} GB / {disk.total // (1024**3)} GB ({disk.percent}%)"
            except ImportError:
                # Fallback for Windows without psutil
                try:
                    result = subprocess.run(['wmic', 'LogicalDisk', 'get', 'Size,FreeSpace'], 
                                          capture_output=True, text=True, timeout=5)
                    lines = result.stdout.strip().split('\n')
                    if len(lines) > 1:
                        values = lines[1].split()
                        if len(values) >= 2:
                            size = int(values[0]) // (1024**3)
                            free = int(values[1]) // (1024**3)
                            used = size - free
                            percent = (used / size * 100) if size > 0 else 0
                            return f"{used} GB / {size} GB ({percent:.0f}%)"
                except:
                    pass
                return "Unknown"
        else:
            # Linux/Unix: Use df command
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=10)
            lines = result.stdout.splitlines()
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 5:
                    used = parts[2]
                    size = parts[1]
                    perc = parts[4]
                    return f"{used}/{size} ({perc})"
            return "Unknown"
    except Exception as e:
        logger.debug(f"Error getting disk usage: {e}")
        return "Unknown"


async def get_host_stats(node_id: int) -> Dict:
    node = get_node(node_id)
    if node['is_local']:
        return {
            "cpu": get_host_cpu_usage(),
            "ram": get_host_ram_usage(),
            "disk": get_host_disk_usage()
        }
    else:
        url = f"{node['url']}/api/get_host_stats"
        params = {"api_key": node["api_key"]}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            stats = response.json()
            # Fallbacks if remote API doesn't provide
            stats['disk'] = stats.get('disk', 'Unknown')
            return stats
        except Exception as e:
            # Remote node unreachable - don't spam error logs
            logger.debug(f"Remote node {node['name']} stats unavailable: {type(e).__name__}")
            return {"cpu": 0.0, "ram": 0.0, "disk": "Unknown"}


@bot.command(name='vps-list')
@is_admin()
async def vps_list(ctx, node_id: int = 1):
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed("Node Not Found", f"Node ID {node_id} not found."))
        return

    # Get node status
    status = await get_node_status(node_id)
    is_online = status.startswith("🟢")

    # Get node resource stats (will use defaults if offline)
    stats = await get_host_stats(node_id)
    cpu_usage = stats.get('cpu', 0.0)
    ram_usage = stats.get('ram', 0.0)
    disk_usage = stats.get('disk', 'Unknown')

    # Resources field text (modern: compact inline stats with progress-like emojis)
    if is_online:
        resources_text = (
            f"**CPU** {cpu_usage:.0f}% {'█' * int(cpu_usage / 5) + '░' * (20 - int(cpu_usage / 5))} "
            f"\n**RAM** {ram_usage:.0f}% {'█' * int(ram_usage / 5) + '░' * (20 - int(ram_usage / 5))} "
            f"\n**Disk** {disk_usage}"
        )
    else:
        resources_text = "⚠️ Resources unavailable (Offline)"

    # Get VPS capacity
    current_vps = get_current_vps_count(node_id)
    total_capacity = node['total_vps']
    capacity_percent = (current_vps / total_capacity * 100) if total_capacity > 0 else 0
    capacity_text = f"{current_vps}/{total_capacity} ({capacity_percent:.0f}%)"

    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT * FROM vps WHERE node_id = ?', (node_id,))
    rows = cur.fetchall()
    conn.close()

    total_vps = len(rows)

    # Modern counters: use more intuitive emojis and clean layout
    running = 0
    stopped = 0
    suspended = 0
    other = 0
    vps_info = []
    for i, row in enumerate(rows, 1):
        vps = dict(row)
        user_id = vps['user_id']
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = f"Unknown ({user_id})"

        status = vps.get('status', 'unknown')
        suspended_flag = vps.get('suspended', False)

        # Count logic: suspended first, then status if not suspended
        if suspended_flag:
            suspended += 1
        elif status == 'running':
            running += 1
        elif status == 'stopped':
            stopped += 1
        else:
            other += 1

        # Modern emoji: vibrant and status-specific
        status_emoji = "🟢" if status == 'running' and not suspended_flag else "🟡" if suspended_flag else "🔴"
        vps_status = status.upper()
        if suspended_flag:
            vps_status += " (SUSPENDED)"
        if vps.get('whitelisted', False):
            vps_status += " (WHITELISTED)"
        config = vps.get('config', 'Custom')
        
        # Add expiration info
        expiration_info = ""
        if vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            if days_remaining < 0:
                expiration_info = " | 🔴 EXPIRED"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                expiration_info = f" | 🟡 EXPIRES({days_remaining}d)"
            else:
                expiration_info = f" | 🟢 ({days_remaining}d)"
        else:
            expiration_info = " | ⏰ No exp"
        
        vps_info.append(f"{status_emoji} **{i}.** {username} • `{vps['container_name']}`\n _{vps_status} | {config}{expiration_info}_")

    # Create main embed (modern: gradient-inspired colors, clean typography)
    color = 0x10b981 if is_online else 0xef4444  # Teal green / Soft red for modern feel
    embed = create_embed(
        title=f"🖥️ VPS Dashboard - {node['name']}",
        description=f"**ID:** `{node_id}` | **Region:** {node['location']}\n*Updated: <t:{int(datetime.now().timestamp())}:R>*",
        color=color
    )
    embed.set_thumbnail(url=node.get('thumbnail_url', None))

    # Inline status and capacity for compact top row
    add_field(embed, "📡 **Status**", status, True)
    add_field(embed, "🗄️ **Capacity**", capacity_text, True)

    # Resources field with modern bar visualization
    add_field(embed, "📊 **Resources**", resources_text, False)

    # Summary field (modern: compact bullet-like with inline emojis)
    summary_text = (
        f"**Total:** {total_vps} 📊\n"
        f"**Running:** {running} 🟢\n"
        f"**Stopped:** {stopped} ⏸️\n"
        f"**Suspended:** {suspended} 🟡"
    )
    if other > 0:
        summary_text += f"\n**Other:** {other} ⚠️"
    add_field(embed, "📈 **Summary**", summary_text, True)

    # VPS List - chunked embeds with modern pagination
    if vps_info:
        chunk_size = 6  # Smaller chunks for cleaner mobile-friendly embeds
        chunks = [vps_info[i:i + chunk_size] for i in range(0, len(vps_info), chunk_size)]
        first_chunk_text = "\n".join(chunks[0])
        add_field(embed, "📋 **Active VPS (1/{len(chunks)})**", f"```{first_chunk_text}```", False)

        # Paginated follow-ups with consistent styling
        for idx, chunk in enumerate(chunks[1:], 2):
            page_embed = create_embed(
                title=f"🖥️ VPS Dashboard - {node['name']} (Page {idx}/{len(chunks)})",
                description=f"**ID:** `{node_id}` | **Region:** {node['location']}\n*Updated: <t:{int(datetime.now().timestamp())}:R>*",
                color=color
            )
            chunk_text = "\n".join(chunk)
            add_field(page_embed, "📋 **VPS List**", f"```{chunk_text}```", False)
            page_embed.set_footer(text=f"Made by AnkitCoder • {len(vps_info)} VPS shown")
            await ctx.send(embed=page_embed)
    else:
        add_field(embed, "📋 **VPS List**", "No deployments yet. Launch one! 🚀", False)

    embed.set_footer(text=f"Made by AnkitCoder • Total: {len(vps_info)} VPS")
    await ctx.send(embed=embed)

@bot.command(name='list-all')
@is_admin()
async def list_all_vps(ctx):
    total_vps = 0
    total_users = len(vps_data)
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    whitelisted_vps = 0
    vps_info = []
    user_summary = []
    for user_id, vps_list in vps_data.items():
        try:
            user = await bot.fetch_user(int(user_id))
            user_vps_count = len(vps_list)
            user_running = sum(1 for vps in vps_list if vps.get('status') == 'running' and not vps.get('suspended', False))
            user_stopped = sum(1 for vps in vps_list if vps.get('status') == 'stopped')
            user_suspended = sum(1 for vps in vps_list if vps.get('suspended', False))
            user_whitelisted = sum(1 for vps in vps_list if vps.get('whitelisted', False))
            total_vps += user_vps_count
            running_vps += user_running
            stopped_vps += user_stopped
            suspended_vps += user_suspended
            whitelisted_vps += user_whitelisted
            user_summary.append(f"**{user.name}** ({user.mention}) - {user_vps_count} VPS ({user_running} running, {user_suspended} suspended, {user_whitelisted} whitelisted)")
            for i, vps in enumerate(vps_list):
                node = get_node(vps['node_id'])
                node_name = node['name'] if node else "Unknown"
                status_emoji = "🟢" if vps.get('status') == 'running' and not vps.get('suspended', False) else "🟡" if vps.get('suspended', False) else "🔴"
                status_text = vps.get('status', 'unknown').upper()
                if vps.get('suspended', False):
                    status_text += " (SUSPENDED)"
                if vps.get('whitelisted', False):
                    status_text += " (WHITELISTED)"
                
                # Add expiration info
                expiration_text = ""
                if vps.get('expiration_date'):
                    expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    days_remaining = (expiration_dt - datetime.now()).days
                    if days_remaining < 0:
                        expiration_text = " • 🔴 EXPIRED"
                    elif days_remaining <= EXPIRATION_WARNING_DAYS:
                        expiration_text = f" • 🟡 EXPIRING({days_remaining}d)"
                    else:
                        expiration_text = f" • 🟢 ({days_remaining}d)"
                else:
                    expiration_text = " • ⏰ No exp"
                
                vps_info.append(f"{status_emoji} **{user.name}** - VPS {i+1}: `{vps['container_name']}` - {vps.get('config', 'Custom')} - {status_text} (Node: {node_name}){expiration_text}")
        except discord.NotFound:
            vps_info.append(f"❓ Unknown User ({user_id}) - {len(vps_list)} VPS")
    embed = create_embed("All VPS Information", "Complete overview of all VPS deployments and user statistics", 0x1a1a1a)
    add_field(embed, "System Overview", f"**Total Users:** {total_users}\n**Total VPS:** {total_vps}\n**Running:** {running_vps}\n**Stopped:** {stopped_vps}\n**Suspended:** {suspended_vps}\n**Whitelisted:** {whitelisted_vps}", False)
    await ctx.send(embed=embed)
    if user_summary:
        embed = create_embed("User Summary", f"Summary of all users and their VPS", 0x1a1a1a)
        summary_text = "\n".join(user_summary)
        chunks = [summary_text[i:i+1024] for i in range(0, len(summary_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            add_field(embed, f"Users (Part {idx})", chunk, False)
        await ctx.send(embed=embed)
    if vps_info:
        vps_text = "\n".join(vps_info)
        chunks = [vps_text[i:i+1024] for i in range(0, len(vps_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"VPS Details (Part {idx})", "List of all VPS deployments", 0x1a1a1a)
            add_field(embed, "VPS List", chunk, False)
            await ctx.send(embed=embed)

@bot.command(name='manage-shared')
async def manage_shared_vps(ctx, owner: discord.Member, vps_number: int):
    owner_id = str(owner.id)
    user_id = str(ctx.author.id)
    if owner_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[owner_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or owner doesn't have a VPS."))
        return
    vps = vps_data[owner_id][vps_number - 1]
    if user_id not in vps.get("shared_with", []):
        await ctx.send(embed=create_error_embed("Access Denied", "You do not have access to this VPS."))
        return
    view = ManageView(user_id, [vps], is_shared=True, owner_id=owner_id, actual_index=vps_number - 1)
    embed = await view.get_initial_embed()
    await ctx.send(embed=embed, view=view)

@bot.command(name='share-user')
async def share_user(ctx, shared_user: discord.Member, vps_number: int):
    user_id = str(ctx.author.id)
    shared_user_id = str(shared_user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or you don't have a VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]
    if "shared_with" not in vps:
        vps["shared_with"] = []
    if shared_user_id in vps["shared_with"]:
        await ctx.send(embed=create_error_embed("Already Shared", f"{shared_user.mention} already has access to this VPS!"))
        return
    vps["shared_with"].append(shared_user_id)
    save_vps_data_immediate()
    await ctx.send(embed=create_success_embed("VPS Shared", f"VPS #{vps_number} shared with {shared_user.mention}!"))
    try:
        await shared_user.send(embed=create_embed("VPS Access Granted", f"You have access to VPS #{vps_number} from {ctx.author.mention}. Use `{PREFIX}manage-shared {ctx.author.mention} {vps_number}`", 0x00ff88))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {shared_user.mention}"))

@bot.command(name='share-ruser')
async def revoke_share(ctx, shared_user: discord.Member, vps_number: int):
    user_id = str(ctx.author.id)
    shared_user_id = str(shared_user.id)
    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed("Invalid VPS", "Invalid VPS number or you don't have a VPS."))
        return
    vps = vps_data[user_id][vps_number - 1]
    if "shared_with" not in vps:
        vps["shared_with"] = []
    if shared_user_id not in vps["shared_with"]:
        await ctx.send(embed=create_error_embed("Not Shared", f"{shared_user.mention} doesn't have access to this VPS!"))
        return
    vps["shared_with"].remove(shared_user_id)
    save_vps_data_immediate()
    await ctx.send(embed=create_success_embed("Access Revoked", f"Access to VPS #{vps_number} revoked from {shared_user.mention}!"))
    try:
        await shared_user.send(embed=create_embed("VPS Access Revoked", f"Your access to VPS #{vps_number} by {ctx.author.mention} has been revoked.", 0xff3366))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {shared_user.mention}"))

@bot.command(name='ports-add-user')
@is_admin()
async def ports_add_user(ctx, amount: int, user: discord.Member):
    if amount <= 0:
        await ctx.send(embed=create_error_embed("Invalid Amount", "Amount must be a positive integer."))
        return
    user_id = str(user.id)
    allocate_ports(user_id, amount)
    embed = create_success_embed("Ports Allocated", f"Allocated {amount} port slots to {user.mention}.")
    add_field(embed, "Quota", f"Total: {get_user_allocation(user_id)} slots", False)
    await ctx.send(embed=embed)
    try:
        dm_embed = create_info_embed("Port Slots Allocated", f"You have been granted {amount} additional port forwarding slots by an admin.\nUse `{PREFIX}ports list` to view your quota and active forwards.")
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("DM Failed", f"Could not notify {user.mention} via DM."))

@bot.command(name='ports-remove-user')
@is_admin()
async def ports_remove_user(ctx, amount: int, user: discord.Member):
    if amount <= 0:
        await ctx.send(embed=create_error_embed("Invalid Amount", "Amount must be a positive integer."))
        return
    user_id = str(user.id)
    current = get_user_allocation(user_id)
    if amount > current:
        amount = current
    deallocate_ports(user_id, amount)
    remaining = get_user_allocation(user_id)
    embed = create_success_embed("Ports Deallocated", f"Removed {amount} port slots from {user.mention}.")
    add_field(embed, "Remaining Quota", f"{remaining} slots", False)
    await ctx.send(embed=embed)
    try:
        dm_embed = create_warning_embed("Port Slots Reduced", f"Your port forwarding quota has been reduced by {amount} slots by an admin.\nRemaining: {remaining} slots.")
        await user.send(embed=dm_embed)
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("DM Failed", f"Could not notify {user.mention} via DM."))

@bot.command(name='ports-revoke')
@is_admin()
async def ports_revoke(ctx, forward_id: int):
    success, user_id = await remove_port_forward(forward_id, is_admin=True)
    if success and user_id:
        try:
            user = await bot.fetch_user(int(user_id))
            dm_embed = create_warning_embed("Port Forward Revoked", f"One of your port forwards (ID: {forward_id}) has been revoked by an admin.")
            await user.send(embed=dm_embed)
        except:
            pass
        await ctx.send(embed=create_success_embed("Revoked", f"Port forward ID {forward_id} revoked."))
    else:
        await ctx.send(embed=create_error_embed("Failed", "Port forward ID not found or removal failed."))

@bot.command(name='ports')
async def ports_command(ctx, subcmd: str = None, *args):
    user_id = str(ctx.author.id)
    allocated = get_user_allocation(user_id)
    used = get_user_used_ports(user_id)
    available = allocated - used
    if subcmd is None:
        embed = create_info_embed("Port Forwarding Help", f"**Your Quota:** Allocated: {allocated}, Used: {used}, Available: {available}")
        add_field(embed, "Commands", f"{PREFIX}ports add <vps_num> <port>\n{PREFIX}ports list\n{PREFIX}ports remove <id>", False)
        await ctx.send(embed=embed)
        return
    if subcmd == 'add':
        if len(args) < 2:
            await ctx.send(embed=create_error_embed("Usage", f"Usage: {PREFIX}ports add <vps_number> <vps_port>"))
            return
        try:
            vps_num = int(args[0])
            vps_port = int(args[1])
            if vps_port < 1 or vps_port > 65535:
                raise ValueError
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid Input", "VPS number and port must be positive integers (port: 1-65535)."))
            return
        vps_list = vps_data.get(user_id, [])
        if vps_num < 1 or vps_num > len(vps_list):
            await ctx.send(embed=create_error_embed("Invalid VPS", f"Invalid VPS number (1-{len(vps_list)}). Use {PREFIX}myvps to list."))
            return
        vps = vps_list[vps_num - 1]
        container = vps['container_name']
        node_id = vps['node_id']
        if used >= allocated:
            await ctx.send(embed=create_error_embed("Quota Exceeded", f"No available slots. Allocated: {allocated}, Used: {used}. Contact admin for more."))
            return
        host_port = await create_port_forward(user_id, container, vps_port, node_id)
        if host_port:
            embed = create_success_embed("Port Forward Created", f"VPS #{vps_num} port {vps_port} (TCP/UDP) forwarded to host port {host_port}.")
            add_field(embed, "Access", f"External: {YOUR_SERVER_IP}:{host_port} → VPS:{vps_port} (TCP & UDP)", False)
            add_field(embed, "Quota Update", f"Used: {used + 1}/{allocated}", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Failed", "Could not assign host port. Try again later."))
    elif subcmd == 'list':
        forwards = get_user_forwards(user_id)
        embed = create_info_embed("Your Port Forwards", f"**Quota:** Allocated: {allocated}, Used: {used}, Available: {available}")
        if not forwards:
            add_field(embed, "Forwards", "No active port forwards.", False)
        else:
            text = []
            for f in forwards:
                vps_num = next((i+1 for i, v in enumerate(vps_data.get(user_id, [])) if v['container_name'] == f['vps_container']), 'Unknown')
                created = datetime.fromisoformat(f['created_at']).strftime('%Y-%m-%d %H:%M')
                text.append(f"**ID {f['id']}** - VPS #{vps_num}: {f['vps_port']} (TCP/UDP) → {f['host_port']} (Created: {created})")
            add_field(embed, "Active Forwards", "\n".join(text[:10]), False)
            if len(forwards) > 10:
                add_field(embed, "Note", f"Showing 10 of {len(forwards)}. Remove unused with {PREFIX}ports remove <id>.")
        await ctx.send(embed=embed)
    elif subcmd == 'remove':
        if len(args) < 1:
            await ctx.send(embed=create_error_embed("Usage", f"Usage: {PREFIX}ports remove <forward_id>"))
            return
        try:
            fid = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Forward ID must be an integer."))
            return
        success, _ = await remove_port_forward(fid)
        if success:
            embed = create_success_embed("Removed", f"Port forward {fid} removed (TCP & UDP).")
            add_field(embed, "Quota Update", f"Used: {used - 1}/{allocated}", False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=create_error_embed("Not Found", "Forward ID not found. Use !ports list."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Subcommand", f"Use: add <vps_num> <port>, list, remove <id>"))

class ConfirmDeleteView(discord.ui.View):
    """Confirmation dialog for VPS deletion"""
    def __init__(self, admin_id: str, vps_id: int, container_name: str, vps_number: int):
        super().__init__(timeout=60)  # 60 seconds to confirm
        self.admin_id = admin_id  # Admin who initiated the delete command
        self.vps_id = vps_id
        self.container_name = container_name
        self.vps_number = vps_number
        self.confirmed = False
    
    @discord.ui.button(label="✅ Confirm Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow only the admin who initiated the delete command to confirm
        if str(interaction.user.id) != self.admin_id:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only the admin who initiated the deletion can confirm!"),
                ephemeral=True
            )
            return
        
        self.confirmed = True
        await interaction.response.defer()
        self.stop()
    
    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Allow only the admin who initiated the delete command to cancel
        if str(interaction.user.id) != self.admin_id:
            await interaction.response.send_message(
                embed=create_error_embed("Access Denied", "Only the admin who initiated the deletion can cancel!"),
                ephemeral=True
            )
            return
        
        await interaction.response.send_message(
            embed=create_info_embed("Deletion Cancelled", f"VPS deletion for {self.container_name} has been cancelled."),
            ephemeral=True
        )
        self.stop()

async def handle_public_vps_renewal(ctx):
    """Handle VPS renewal for public users"""
    if not PUBLIC_VPS_RENEWAL_ENABLED:
        await ctx.send(embed=create_error_embed("Disabled", "VPS renewal is currently disabled."))
        return
    
    user_id = str(ctx.author.id)
    vps_list = vps_data.get(user_id, [])
    
    if not vps_list:
        await ctx.send(embed=create_error_embed("No VPS", f"You don't have any VPS to renew! Use `{PREFIX}vps create` to create one."), ephemeral=True)
        return
    
    # Filter VPS that are eligible for renewal (1 day or less remaining)
    renewable_vps = []
    non_renewable_vps = []
    
    for i, vps in enumerate(vps_list):
        if vps.get('expiration_date'):
            try:
                exp_dt = datetime.fromisoformat(vps['expiration_date'])
                current_dt = datetime.now(exp_dt.tzinfo) if exp_dt.tzinfo else datetime.now()
                days_remaining = (exp_dt - current_dt).days
                
                if days_remaining <= 1:  # Can renew if 1 day or less remaining
                    renewable_vps.append({
                        'index': i,
                        'vps': vps,
                        'days_remaining': days_remaining
                    })
                else:
                    non_renewable_vps.append({
                        'vps': vps,
                        'days_remaining': days_remaining
                    })
            except:
                renewable_vps.append({
                    'index': i,
                    'vps': vps,
                    'days_remaining': 0
                })
        else:
            renewable_vps.append({
                'index': i,
                'vps': vps,
                'days_remaining': 0
            })
    
    # If no VPS are renewable, show which ones need to wait
    if not renewable_vps:
        embed = discord.Embed(
            title="⏳ VPS Not Ready for Renewal",
            description="Your VPS can only be renewed when it has 1 day or less remaining.",
            color=discord.Color.orange()
        )
        
        for item in non_renewable_vps:
            vps = item['vps']
            days = item['days_remaining']
            embed.add_field(
                name=f"📅 {vps['container_name']}",
                value=(
                    f"**Days Remaining:** {days} days\n"
                    f"**Expires:** {vps['expiration_date'][:10]}\n"
                    f"**Can Renew In:** {days - 1} day(s)"
                ),
                inline=False
            )
        
        embed.set_footer(text="⏰ You can only renew when expiration is within 1 day")
        await ctx.send(embed=embed, ephemeral=True)
        return
    
    if len(renewable_vps) == 1:
        # Only one VPS eligible for renewal, renew it directly
        vps_item = renewable_vps[0]
        await execute_renewal(ctx, user_id, vps_item['vps'], vps_item['index'])
    else:
        # Multiple VPS eligible for renewal, let user choose
        embed = discord.Embed(
            title="🔄 Renew Your VPS",
            description="Which VPS would you like to renew?",
            color=discord.Color.blue()
        )
        
        options = []
        for item in renewable_vps:
            vps = item['vps']
            container_name = vps['container_name']
            days_left = item['days_remaining']
            
            label = f"{container_name} ({days_left} day(s) left)"
            options.append(discord.SelectOption(label=label, value=str(item['index'])))
        
        select = discord.ui.Select(
            placeholder="Select a VPS to renew",
            options=options
        )
        
        async def select_callback(interaction: discord.Interaction):
            if str(interaction.user.id) != user_id:
                await interaction.response.send_message("This is not for you!", ephemeral=True)
                return
            
            selected_idx = int(select.values[0])
            selected_vps = vps_list[selected_idx]
            await interaction.response.defer(ephemeral=True)
            await execute_renewal(interaction, user_id, selected_vps, selected_idx)
        
        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        
        await ctx.send(embed=embed, view=view, ephemeral=True)

async def execute_renewal(ctx_or_interaction, user_id: str, vps: dict, vps_idx: int):
    """Execute the actual VPS renewal"""
    container_name = vps['container_name']
    
    # Calculate new expiration date
    current_exp = vps.get('expiration_date')
    if current_exp:
        current_exp_dt = datetime.fromisoformat(current_exp)
        # If expired, renew from today; otherwise extend from current expiration
        if current_exp_dt < datetime.now():
            new_exp_dt = datetime.now() + timedelta(days=PUBLIC_VPS_RENEWAL_DAYS)
        else:
            new_exp_dt = current_exp_dt + timedelta(days=PUBLIC_VPS_RENEWAL_DAYS)
    else:
        new_exp_dt = datetime.now() + timedelta(days=PUBLIC_VPS_RENEWAL_DAYS)
    
    # Update VPS data
    vps['expiration_date'] = new_exp_dt.isoformat()
    
    # Save to database
    try:
        save_vps_data_immediate()
        
        # Send confirmation
        embed = discord.Embed(
            title="✅ VPS Renewed Successfully!",
            description=f"Your VPS `{container_name}` has been renewed.",
            color=discord.Color.green()
        )
        embed.add_field(
            name="📊 Renewal Details",
            value=(
                f"**VPS:** `{container_name}`\n"
                f"**New Expiry:** `{new_exp_dt.strftime('%Y-%m-%d')}`\n"
                f"**Days Added:** {PUBLIC_VPS_RENEWAL_DAYS}\n"
                f"**Duration:** {(new_exp_dt - datetime.now()).days} days from now"
            ),
            inline=False
        )
        embed.set_footer(text="✨ Your VPS is now protected for longer!")
        
        if hasattr(ctx_or_interaction, 'followup'):
            # It's an interaction
            await ctx_or_interaction.followup.send(embed=embed, ephemeral=True)
        else:
            # It's a context
            await ctx_or_interaction.send(embed=embed, ephemeral=True)
        
        logger.info(f"[OK] VPS renewed for user {user_id}: {container_name} -> {new_exp_dt.strftime('%Y-%m-%d')}")
        
    except Exception as e:
        error_embed = create_error_embed("Renewal Failed", f"Could not renew VPS: {str(e)}")
        if hasattr(ctx_or_interaction, 'followup'):
            await ctx_or_interaction.followup.send(embed=error_embed, ephemeral=True)
        else:
            await ctx_or_interaction.send(embed=error_embed, ephemeral=True)
        logger.error(f"VPS renewal failed for {user_id}: {e}", exc_info=True)

@bot.command(name='delete-vps')
@is_admin()
async def delete_vps(ctx, user: discord.Member, vps_number: int, *, reason: str = "No reason"):
    user_id = str(user.id)

    if user_id not in vps_data or vps_number < 1 or vps_number > len(vps_data[user_id]):
        await ctx.send(embed=create_error_embed(
            "Invalid VPS",
            "Invalid VPS number or user doesn't have that VPS."
        ))
        return

    vps = vps_data[user_id][vps_number - 1]
    container_name = vps["container_name"]
    vps_id = vps.get("id", vps_number)
    node_id = vps.get("node_id", 1)

    # Create confirmation embed with clearer info
    confirm_embed = create_embed("⚠️ Confirm VPS Deletion", f"Are you sure you want to delete this VPS?", 0xff3366)
    add_field(confirm_embed, "VPS Details", 
        f"**VPS ID:** #{vps_id}\n"
        f"**Container:** `{container_name}`\n"
        f"**Owner:** {user.mention}\n"
        f"**Config:** {vps.get('config', 'Custom')}\n"
        f"**Status:** {vps.get('status', 'unknown').upper()}", 
        False)
    add_field(confirm_embed, "Action", "Click **✅ Confirm Delete** to permanently delete this VPS, or **❌ Cancel** to abort.", False)
    add_field(confirm_embed, "Reason", reason, False)
    
    confirmation_view = ConfirmDeleteView(str(ctx.author.id), vps_id, container_name, vps_number)
    confirmation_msg = await ctx.send(embed=confirm_embed, view=confirmation_view)
    
    # Wait for confirmation
    await confirmation_view.wait()
    
    if not confirmation_view.confirmed:
        return  # User cancelled or timeout
    
    # Proceed with deletion
    await ctx.send(embed=create_info_embed(
        "🗑️ Deleting VPS",
        f"Removing VPS #{vps_id} for {user.mention}..."
    ))

    node_result = "Not checked"

    # 1️⃣ Try deleting container
    try:
        await execute_lxc(container_name, f"delete {container_name} --force", node_id=node_id)
        node_result = "Container deleted successfully."
    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["not found", "does not exist", "no such container"]):
            node_result = "Container not found (force DB cleanup)."
        else:
            node_result = f"Container delete failed: {e}"

    # 2️⃣ DELETE FROM DATABASE
    conn = get_db()
    cur = conn.cursor()

    cur.execute("DELETE FROM vps WHERE container_name = ?", (container_name,))
    cur.execute("DELETE FROM port_forwards WHERE vps_container = ?", (container_name,))

    conn.commit()
    conn.close()

    # 3️⃣ Remove from memory
    del vps_data[user_id][vps_number - 1]
    if not vps_data[user_id]:
        del vps_data[user_id]

        # Remove VPS role if needed
        if ctx.guild:
            role = await get_or_create_vps_role(ctx.guild)
            if role and role in user.roles:
                try:
                    await user.remove_roles(role, reason="No VPS ownership")
                except discord.Forbidden:
                    logger.warning(f"Failed to remove VPS role from {user.name}")

    save_vps_data_immediate()

    # 4️⃣ Success embed
    embed = create_success_embed("✅ VPS Deleted Successfully")
    add_field(embed, "VPS ID", f"#{vps_id}", True)
    add_field(embed, "Owner", user.mention, True)
    add_field(embed, "Container", container_name, False)
    add_field(embed, "Node Result", node_result, False)
    add_field(embed, "Reason", reason, False)

    await ctx.send(embed=embed)

@bot.command(name='add-resources')
@is_admin()
async def add_resources(ctx, vps_id: str, ram: int = None, cpu: int = None, disk: int = None):
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", "Please specify at least one resource to add (ram, cpu, or disk)"))
        return
    found_vps = None
    user_id = None
    vps_index = None
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == vps_id:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with ID: `{vps_id}`"))
        return
    node_id = found_vps['node_id']
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    disk_changed = disk is not None
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping VPS `{vps_id}` to apply resource changes..."))
        try:
            await execute_lxc(vps_id, "stop {vps_id}", node_id=node_id)
            found_vps['status'] = 'stopped'
            save_vps_data_immediate()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", f"Error stopping VPS: {str(e)}"))
            return
    changes = []
    try:
        current_ram_gb = int(found_vps['ram'].replace('GB', ''))
        current_cpu = int(found_vps['cpu'])
        current_disk_gb = int(found_vps['storage'].replace('GB', ''))
        new_ram_gb = current_ram_gb
        new_cpu = current_cpu
        new_disk_gb = current_disk_gb
        if ram is not None and ram > 0:
            new_ram_gb += ram
            ram_mb = new_ram_gb * 1024
            await execute_lxc(vps_id, f"config set {vps_id} limits.memory {ram_mb}MB", node_id=node_id)
            changes.append(f"RAM: +{ram}GB (New total: {new_ram_gb}GB)")
        if cpu is not None and cpu > 0:
            new_cpu += cpu
            await execute_lxc(vps_id, f"config set {vps_id} limits.cpu {new_cpu}", node_id=node_id)
            changes.append(f"CPU: +{cpu} cores (New total: {new_cpu} cores)")
        if disk is not None and disk > 0:
            new_disk_gb += disk
            await execute_lxc(vps_id, f"config device set {vps_id} root size={new_disk_gb}GB", node_id=node_id)
            changes.append(f"Disk: +{disk}GB (New total: {new_disk_gb}GB)")
        found_vps['ram'] = f"{new_ram_gb}GB"
        found_vps['cpu'] = str(new_cpu)
        found_vps['storage'] = f"{new_disk_gb}GB"
        found_vps['config'] = f"{new_ram_gb}GB RAM / {new_cpu} CPU / {new_disk_gb}GB Disk"
        vps_data[user_id][vps_index] = found_vps
        save_vps_data_immediate()
        if was_running:
            await execute_lxc(vps_id, f"start {vps_id}", node_id=node_id)
            found_vps['status'] = 'running'
            save_vps_data_immediate()
            await apply_internal_permissions(vps_id, node_id)
            await recreate_port_forwards(vps_id)
        embed = create_success_embed("Resources Added", f"Successfully added resources to VPS `{vps_id}`")
        add_field(embed, "Changes Applied", "\n".join(changes), False)
        if disk_changed:
            add_field(embed, "Disk Note", "Run `sudo resize2fs /` inside the VPS to expand the filesystem.", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Resource Addition Failed", f"Error: {str(e)}"))


@bot.command(name='status')
@is_admin()
async def system_status(ctx):
    """
    Show complete system status including:
    - Bot uptime
    - Total nodes & their status
    - Running/stopped nodes count
    - Total RAM/CPU/DISK allocated vs free
    - Total VPS & users
    - Running/stopped/suspended VPS counts
    - Total admin users
    - Whitelisted VPS
    """
    
    # Start timing for response time
    start_time = time.time()
    
    # Get bot uptime
    bot_start_time = datetime.now() - datetime.fromtimestamp(start_time - bot.latency)
    bot_uptime = str(bot_start_time).split('.')[0]  # Remove microseconds
    
    # Get total nodes
    nodes = get_nodes()
    total_nodes = len(nodes)
    
    # Node status counters
    running_nodes = 0
    stopped_nodes = 0
    local_nodes = 0
    remote_nodes = 0
    
    # Node resource tracking
    total_node_cpu_allocated = 0
    total_node_ram_allocated = 0
    total_node_disk_allocated = 0
    total_node_cpu_free = 0
    total_node_ram_free = 0
    total_node_disk_free = 0
    
    # VPS counters
    total_vps = 0
    total_users = len(vps_data)
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    whitelisted_vps = 0
    
    # Admin counters
    total_admins = len(admin_data.get("admins", []))
    
    # Port statistics
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT SUM(allocated_ports) FROM port_allocations")
    total_ports_allocated = cur.fetchone()[0] or 0
    cur.execute("SELECT COUNT(*) FROM port_forwards")
    total_ports_used = cur.fetchone()[0] or 0
    conn.close()
    
    # Resource counters for all VPS
    total_ram_allocated = 0
    total_cpu_allocated = 0
    total_disk_allocated = 0
    
    # Process all VPS data
    for user_id, vps_list in vps_data.items():
        total_vps += len(vps_list)
        
        for vps in vps_list:
            # Count status
            if vps.get('suspended', False):
                suspended_vps += 1
            elif vps.get('status') == 'running':
                running_vps += 1
            else:
                stopped_vps += 1
            
            # Count whitelisted
            if vps.get('whitelisted', False):
                whitelisted_vps += 1
            
            # Calculate allocated resources
            try:
                ram_gb = int(vps['ram'].replace('GB', ''))
                total_ram_allocated += ram_gb
            except:
                pass
            
            try:
                cpu_cores = int(vps['cpu'])
                total_cpu_allocated += cpu_cores
            except:
                pass
            
            try:
                disk_gb = int(vps['storage'].replace('GB', ''))
                total_disk_allocated += disk_gb
            except:
                pass
    
    # Check node status and calculate free resources
    node_statuses = []
    
    for node in nodes:
        # Determine node type
        if node['is_local']:
            local_nodes += 1
            node_type = "🖥️ Local"
        else:
            remote_nodes += 1
            node_type = "🌐 Remote"
        
        # Check node status
        if node['is_local']:
            status = "🟢 Online"
            running_nodes += 1
            
            # Get local resources (approximate) - cross-platform
            try:
                import platform
                system = platform.system()
                
                if system == "Windows":
                    # Windows: Use psutil
                    try:
                        import psutil
                        mem = psutil.virtual_memory()
                        total_ram_gb = mem.total / (1024**3)
                        free_ram_gb = mem.available / (1024**3)
                        
                        cpu_count = psutil.cpu_count()
                        total_cpu = cpu_count if cpu_count else 0
                        
                        disk = psutil.disk_usage('C:\\' if 'C:\\' else '/')
                        total_disk = disk.total / (1024**3)
                    except ImportError:
                        # Fallback for Windows without psutil
                        try:
                            result = subprocess.run(['wmic', 'OS', 'get', 'TotalVisibleMemorySize,FreePhysicalMemory'], 
                                                  capture_output=True, text=True, timeout=5)
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:
                                values = lines[1].split()
                                total_ram_gb = int(values[0]) / (1024**2)
                                free_ram_gb = int(values[1]) / (1024**2)
                            else:
                                total_ram_gb = 0
                                free_ram_gb = 0
                            
                            result = subprocess.run(['wmic', 'os', 'get', 'numberofprocessors'], 
                                                  capture_output=True, text=True, timeout=5)
                            total_cpu = int(result.stdout.strip().split('\n')[-1]) if result.stdout else 0
                            
                            total_disk = 0  # Approximate
                        except:
                            total_ram_gb = 0
                            free_ram_gb = 0
                            total_cpu = 0
                            total_disk = 0
                else:
                    # Linux/Unix: Use traditional commands
                    # Get system memory
                    mem_result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=10)
                    mem_lines = mem_result.stdout.splitlines()
                    if len(mem_lines) > 1:
                        mem = mem_lines[1].split()
                        total_ram_mb = int(mem[1])
                        used_ram_mb = int(mem[2])
                        free_ram_mb = total_ram_mb - used_ram_mb
                        total_ram_gb = total_ram_mb / 1024
                        free_ram_gb = free_ram_mb / 1024
                    else:
                        total_ram_gb = 0
                        free_ram_gb = 0
                    
                    # Get CPU cores
                    cpu_result = subprocess.run(['nproc'], capture_output=True, text=True, timeout=10)
                    total_cpu = int(cpu_result.stdout.strip()) if cpu_result.stdout.strip() else 0
                    
                    # Get disk space
                    disk_result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=10)
                    disk_lines = disk_result.stdout.splitlines()
                    if len(disk_lines) > 1:
                        disk_parts = disk_lines[1].split()
                        total_disk_str = disk_parts[1]
                        # Convert to GB
                        if 'T' in total_disk_str:
                            total_disk = float(total_disk_str.replace('T', '')) * 1024
                        elif 'G' in total_disk_str:
                            total_disk = float(total_disk_str.replace('G', ''))
                        elif 'M' in total_disk_str:
                            total_disk = float(total_disk_str.replace('M', '')) / 1024
                        else:
                            total_disk = 0
                    else:
                        total_disk = 0
                
                # Calculate free resources (simplified - actual would need more complex logic)
                free_cpu = max(0, total_cpu - (total_cpu_allocated // total_nodes)) if total_nodes > 0 else 0
                free_disk = max(0, total_disk - (total_disk_allocated // total_nodes)) if total_nodes > 0 else 0
                
                # Update totals
                if total_ram_gb > 0:
                    total_node_ram_allocated += total_ram_gb - free_ram_gb
                    total_node_ram_free += free_ram_gb
                if total_cpu > 0:
                    total_node_cpu_allocated += total_cpu - free_cpu
                    total_node_cpu_free += free_cpu
                if total_disk > 0:
                    total_node_disk_allocated += total_disk - free_disk
                    total_node_disk_free += free_disk
                
            except Exception as e:
                logger.debug(f"Error getting local node resources: {e}")
                status = "⚠️ Unknown"
                # Don't reset to 0, just skip this node's resources
        else:
            # Check remote node status
            try:
                response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                if response.status_code == 200:
                    status = "🟢 Online"
                    running_nodes += 1
                else:
                    status = "🔴 Offline"
                    stopped_nodes += 1
            except:
                status = "🔴 Offline"
                stopped_nodes += 1
        
        # Get current VPS count on this node
        node_vps_count = get_current_vps_count(node['id'])
        capacity = node['total_vps']
        usage_percentage = (node_vps_count / capacity * 100) if capacity > 0 else 0
        
        node_statuses.append(
            f"**{node['name']}** ({node_type})\n"
            f"📍 {node['location']} • 📊 {node_vps_count}/{capacity} VPS ({usage_percentage:.0f}%)\n"
            f"Status: {status}"
        )
    
    # Calculate response time
    response_time = (time.time() - start_time) * 1000
    
    # Create main embed
    embed = create_embed(
        title="📊 System Status Dashboard",
        description=f"**{BOT_NAME}** - Complete System Overview\n*Generated in {response_time:.0f}ms*",
        color=0x1a1a1a
    )
    
    # Bot & Uptime Section
    add_field(embed, "🤖 Bot Status", 
        f"**Uptime:** {bot_uptime}\n"
        f"**Latency:** {round(bot.latency * 1000)}ms\n"
        f"**Version:** {BOT_VERSION}\n"
        f"**Developer:** {BOT_DEVELOPER}", 
        True)
    
    # Nodes Section
    add_field(embed, "🌐 Nodes Overview",
        f"**Total Nodes:** {total_nodes}\n"
        f"**Running:** {running_nodes} 🟢\n"
        f"**Stopped:** {stopped_nodes} 🔴\n"
        f"**Local/Remote:** {local_nodes}/{remote_nodes}",
        True)
    
    # VPS & Users Section
    add_field(embed, "👥 Users & VPS",
        f"**Total Users:** {total_users}\n"
        f"**Total VPS:** {total_vps}\n"
        f"**Running:** {running_vps} 🟢\n"
        f"**Stopped:** {stopped_vps} 🔴\n"
        f"**Suspended:** {suspended_vps} 🟡\n"
        f"**Whitelisted:** {whitelisted_vps} ✅",
        True)
    
    # Resources Section - Allocated vs Free
    add_field(embed, "💾 Resource Allocation",
        f"**RAM Allocated:** {total_ram_allocated} GB\n"
        f"**RAM Free:** {total_node_ram_free:.1f} GB\n"
        f"**CPU Allocated:** {total_cpu_allocated} Cores\n"
        f"**CPU Free:** {total_node_cpu_free:.1f} Cores\n"
        f"**Disk Allocated:** {total_disk_allocated} GB\n"
        f"**Disk Free:** {total_node_disk_free:.1f} GB",
        True)
    
    # System & Admin Section
    add_field(embed, "⚙️ System Information",
        f"**Total Admins:** {total_admins}\n"
        f"**Main Admin:** <@{MAIN_ADMIN_ID}>\n"
        f"**Ports Allocated:** {total_ports_allocated}\n"
        f"**Ports In Use:** {total_ports_used}\n"
        f"**Ports Available:** {total_ports_allocated - total_ports_used}",
        True)
    
    # Node Details Section (if any nodes exist)
    if node_statuses:
        # Split node statuses into chunks if too long
        node_text = "\n\n".join(node_statuses)
        chunks = [node_text[i:i+1024] for i in range(0, len(node_text), 1024)]
        
        for idx, chunk in enumerate(chunks, 1):
            title = "📡 Node Details" if idx == 1 else f"📡 Node Details (Part {idx})"
            add_field(embed, title, chunk, False)
    
    # Expiration Status Section
    expiring_soon_count = 0
    expired_count = 0
    active_exp_count = 0
    no_exp_count = 0
    
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps.get('expiration_date'):
                expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                days_remaining = (expiration_dt - datetime.now()).days
                if days_remaining < 0:
                    expired_count += 1
                elif days_remaining <= EXPIRATION_WARNING_DAYS:
                    expiring_soon_count += 1
                else:
                    active_exp_count += 1
            else:
                no_exp_count += 1
    
    add_field(embed, "⏰ VPS Expiration Status",
        f"**🟢 Active:** {active_exp_count} VPS\n"
        f"**🟡 Expiring Soon:** {expiring_soon_count} VPS\n"
        f"**🔴 Expired:** {expired_count} VPS\n"
        f"**🔵 No Expiration:** {no_exp_count} VPS",
        True)
    
    # System Health Indicator
    health_status = "✅ Excellent"
    health_color = 0x00ff88
    
    if running_nodes == 0:
        health_status = "🔴 Critical - No nodes running"
        health_color = 0xff3366
    elif stopped_nodes > 0:
        health_status = "🟡 Warning - Some nodes offline"
        health_color = 0xffaa00
    elif total_vps == 0:
        health_status = "ℹ️ No VPS deployed"
        health_color = 0x00ccff
    
    add_field(embed, "🏥 System Health", health_status, False)
    
    # Footer with current time
    embed.set_footer(text=f"Made by AnkitCoder • System Status • Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                    icon_url=BOT_ICON_URL)
    
    await ctx.send(embed=embed)


@bot.command(name='status-summary')
@is_admin()
async def status_summary(ctx):
    """
    Quick summary of system status
    """
    # Get quick stats
    nodes = get_nodes()
    total_nodes = len(nodes)
    running_nodes = 0
    
    for node in nodes:
        if node['is_local']:
            running_nodes += 1
        else:
            try:
                response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=3)
                if response.status_code == 200:
                    running_nodes += 1
            except:
                pass
    
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())
    total_users = len(vps_data)
    
    # Count VPS status
    running_vps = 0
    stopped_vps = 0
    suspended_vps = 0
    
    for vps_list in vps_data.values():
        for vps in vps_list:
            if vps.get('suspended', False):
                suspended_vps += 1
            elif vps.get('status') == 'running':
                running_vps += 1
            else:
                stopped_vps += 1
    
    embed = create_success_embed(
        "📈 Quick Status Summary",
        f"**Nodes:** {running_nodes}/{total_nodes} 🟢\n"
        f"**VPS:** {total_vps} total\n"
        f"• Running: {running_vps} 🟢\n"
        f"• Stopped: {stopped_vps} 🔴\n"
        f"• Suspended: {suspended_vps} 🟡\n"
        f"**Users:** {total_users} 👥\n"
        f"**Bot Latency:** {round(bot.latency * 1000)}ms"
    )
    
    embed.set_footer(text=f"Use '{PREFIX}status' for detailed information")
    await ctx.send(embed=embed)

@bot.command(name='admin-add')
@is_main_admin()
async def admin_add(ctx, user: discord.Member):
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Already Admin", "This user is already the main admin!"))
        return
    if user_id in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Already Admin", f"{user.mention} is already an admin!"))
        return
    admin_data["admins"].append(user_id)
    save_admin_data()
    await ctx.send(embed=create_success_embed("Admin Added", f"{user.mention} is now an admin!"))
    try:
        await user.send(embed=create_embed("🎉 Admin Role Granted", f"You are now an admin by {ctx.author.mention}", 0x00ff88))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {user.mention}"))

@bot.command(name='admin-remove')
@is_main_admin()
async def admin_remove(ctx, user: discord.Member):
    user_id = str(user.id)
    if user_id == str(MAIN_ADMIN_ID):
        await ctx.send(embed=create_error_embed("Cannot Remove", "You cannot remove the main admin!"))
        return
    if user_id not in admin_data.get("admins", []):
        await ctx.send(embed=create_error_embed("Not Admin", f"{user.mention} is not an admin!"))
        return
    admin_data["admins"].remove(user_id)
    save_admin_data()
    await ctx.send(embed=create_success_embed("Admin Removed", f"{user.mention} is no longer an admin!"))
    try:
        await user.send(embed=create_embed("⚠️ Admin Role Revoked", f"Your admin role was removed by {ctx.author.mention}", 0xff3366))
    except discord.Forbidden:
        await ctx.send(embed=create_info_embed("Notification Failed", f"Could not DM {user.mention}"))

@bot.command(name='admin-list')
@is_main_admin()
async def admin_list(ctx):
    admins = admin_data.get("admins", [])
    main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
    embed = create_embed("👑 Admin Team", "Current administrators:", 0x1a1a1a)
    add_field(embed, "🔰 Main Admin", f"{main_admin.mention} (ID: {MAIN_ADMIN_ID})", False)
    if admins:
        admin_list = []
        for admin_id in admins:
            try:
                admin_user = await bot.fetch_user(int(admin_id))
                admin_list.append(f"• {admin_user.mention} (ID: {admin_id})")
            except:
                admin_list.append(f"• Unknown User (ID: {admin_id})")
        admin_text = "\n".join(admin_list)
        add_field(embed, "🛡️ Admins", admin_text, False)
    else:
        add_field(embed, "🛡️ Admins", "No additional admins", False)
    await ctx.send(embed=embed)

@bot.command(name="userinfo")
@is_admin()
async def user_info(ctx, user: discord.Member):
    user_id = str(user.id)
    vps_list = vps_data.get(user_id, [])

    # ─── Embed ─────────────────────────────────────────────────
    embed = create_embed(
        title="👤 User Dashboard",
        description=f"Statistics & resources for {user.mention}",
        color=0x1A1A1A
    )

    # ─── Row 1 : User Info ─────────────────────────────────────
    embed.add_field(
        name="👤 User",
        value=(
            f"**Name:** `{user.name}`\n"
            f"**ID:** `{user.id}`\n"
            f"**Joined:** `{user.joined_at.strftime('%Y-%m-%d') if user.joined_at else 'Unknown'}`"
        ),
        inline=True
    )

    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    embed.add_field(
        name="🛡️ Admin",
        value="✅ Yes" if is_admin_user else "❌ No",
        inline=True
    )

    embed.add_field(
        name="🖥️ VPS Count",
        value=f"`{len(vps_list)}` VPS",
        inline=True
    )

    # ─── If VPS Exists ─────────────────────────────────────────
    if vps_list:
        total_ram = total_cpu = total_storage = 0
        running = suspended = whitelisted = 0

        vps_lines = []

        for i, vps in enumerate(vps_list, start=1):
            node = get_node(vps.get("node_id"))
            node_name = node["name"] if node else "Unknown"

            ram = int(vps.get("ram", "0GB").replace("GB", ""))
            storage = int(vps.get("storage", "0GB").replace("GB", ""))
            cpu = int(vps.get("cpu", 0))

            total_ram += ram
            total_storage += storage
            total_cpu += cpu

            if vps.get("suspended"):
                status = "⛔ SUSPENDED"
                suspended += 1
            elif vps.get("status") == "running":
                status = "🟢 RUNNING"
                running += 1
            else:
                status = "🔴 STOPPED"

            if vps.get("whitelisted"):
                whitelisted += 1

            vps_lines.append(
                f"**{i}.** `{vps['container_name']}`\n"
                f"{status} | `{ram}GB` RAM • `{cpu}` CPU • `{storage}GB` Disk\n"
                f"📍 Node: `{node_name}`" + 
                (f"\n⏰ {('🔴 EXPIRED' if (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days < 0 else '🟡 EXPIRING' if (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days <= EXPIRATION_WARNING_DAYS else '🟢 ACTIVE')} • {(datetime.fromisoformat(vps['expiration_date']).strftime('%Y-%m-%d'))} ({max(0, (datetime.fromisoformat(vps['expiration_date']) - datetime.now()).days)}d)" if vps.get('expiration_date') else "\n⏰ No expiration set")
            )

        # ─── Row 2 : VPS Summary ────────────────────────────────
        embed.add_field(
            name="📊 VPS Summary",
            value=(
                f"🖥️ `{len(vps_list)}` Total\n"
                f"🟢 `{running}` Running\n"
                f"⛔ `{suspended}` Suspended\n"
                f"✅ `{whitelisted}` Whitelisted"
            ),
            inline=True
        )

        embed.add_field(
            name="📈 Resources",
            value=(
                f"**RAM:** `{total_ram} GB`\n"
                f"**CPU:** `{total_cpu} Cores`\n"
                f"**Disk:** `{total_storage} GB`"
            ),
            inline=True
        )

        port_quota = get_user_allocation(user_id)
        port_used = get_user_used_ports(user_id)

        embed.add_field(
            name="🌐 Ports",
            value=f"`{port_used}/{port_quota}` Used",
            inline=True
        )

        # ─── VPS List (Split if needed) ────────────────────────
        vps_text = "\n\n".join(vps_lines)
        for i in range(0, len(vps_text), 1024):
            embed.add_field(
                name="📋 VPS List",
                value=vps_text[i:i + 1024],
                inline=False
            )

    else:
        embed.add_field(
            name="🖥️ VPS",
            value="❌ No VPS assigned",
            inline=False
        )

    embed.set_footer(text="Made by AnkitCoder • User Resource Dashboard")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name="serverstats")
@is_admin()
async def server_stats(ctx):
    # ─── Counts ────────────────────────────────────────────────
    total_users = len(vps_data)
    total_admins = len(admin_data.get("admins", [])) + 1
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())

    total_ram = total_cpu = total_storage = 0
    running_vps = suspended_vps = stopped_vps = 0
    whitelisted_vps = 0

    # ─── VPS Data ──────────────────────────────────────────────
    for vps_list in vps_data.values():
        for vps in vps_list:
            total_ram += int(vps.get("ram", "0GB").replace("GB", ""))
            total_storage += int(vps.get("storage", "0GB").replace("GB", ""))
            total_cpu += int(vps.get("cpu", 0))

            if vps.get("status") == "running":
                if vps.get("suspended", False):
                    suspended_vps += 1
                else:
                    running_vps += 1
            else:
                stopped_vps += 1

            if vps.get("whitelisted", False):
                whitelisted_vps += 1

    # ─── Ports ─────────────────────────────────────────────────
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT SUM(allocated_ports) FROM port_allocations")
    total_ports_allocated = cur.fetchone()[0] or 0

    cur.execute("SELECT COUNT(*) FROM port_forwards")
    total_ports_used = cur.fetchone()[0] or 0
    conn.close()

    # ─── Embed ─────────────────────────────────────────────────
    embed = create_embed(
        title="📊 Server Statistics",
        description="**Live Infrastructure Dashboard**",
        color=0x1A1A1A
    )

    # ── Row 1 ──────────────────────────────────────────────────
    embed.add_field(
        name="👥 Users",
        value=f"`{total_users}` Users\n`{total_admins}` Admins",
        inline=True
    )

    embed.add_field(
        name="🖥️ VPS",
        value=(
            f"Total: `{total_vps}`\n"
            f"🟢 `{running_vps}` Running\n"
            f"⛔ `{suspended_vps}` Suspended"
        ),
        inline=True
    )

    embed.add_field(
        name="📌 Status",
        value=(
            f"🔴 `{stopped_vps}` Stopped\n"
            f"✅ `{whitelisted_vps}` Whitelisted"
        ),
        inline=True
    )

    # ── Row 2 ──────────────────────────────────────────────────
    embed.add_field(
        name="📈 RAM",
        value=f"`{total_ram} GB`",
        inline=True
    )

    embed.add_field(
        name="⚙️ CPU",
        value=f"`{total_cpu} Cores`",
        inline=True
    )

    embed.add_field(
        name="💾 Storage",
        value=f"`{total_storage} GB`",
        inline=True
    )

    # ─── Expiration Counts ─────────────────────────────────────
    expiring_soon_count = 0
    expired_count = 0
    active_exp_count = 0
    no_exp_count = 0
    
    for vps_list in vps_data.values():
        for vps in vps_list:
            if vps.get('expiration_date'):
                expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                days_remaining = (expiration_dt - datetime.now()).days
                if days_remaining < 0:
                    expired_count += 1
                elif days_remaining <= EXPIRATION_WARNING_DAYS:
                    expiring_soon_count += 1
                else:
                    active_exp_count += 1
            else:
                no_exp_count += 1

    # ── Row 3 ──────────────────────────────────────────────────
    embed.add_field(
        name="⏰ Expiration",
        value=(
            f"🟢 `{active_exp_count}` Active\n"
            f"🟡 `{expiring_soon_count}` Expiring Soon\n"
            f"🔴 `{expired_count}` Expired\n"
            f"🔵 `{no_exp_count}` No Exp"
        ),
        inline=True
    )

    embed.add_field(
        name="🌐 Ports Allocated",
        value=f"`{total_ports_allocated}`",
        inline=True
    )

    embed.add_field(
        name="🔌 Ports In Use",
        value=f"`{total_ports_used}`",
        inline=True
    )

    # ── Row 4 ──────────────────────────────────────────────────

    # ── Row 4 ──────────────────────────────────────────────────
    embed.add_field(
        name="📊 Port Utilization",
        value=(
            f"`{total_ports_used}/{total_ports_allocated}`"
            if total_ports_allocated else "`N/A`"
        ),
        inline=True
    )

    embed.set_footer(text="Made by AnkitCoder • Real-Time Monitoring")
    embed.timestamp = ctx.message.created_at

    await ctx.send(embed=embed)

@bot.command(name='vpsinfo')
@is_admin()
async def vps_info(ctx, container_name: str = None):
    if not container_name:
        all_vps = []
        for user_id, vps_list in vps_data.items():
            try:
                user = await bot.fetch_user(int(user_id))
                for i, vps in enumerate(vps_list):
                    node = get_node(vps['node_id'])
                    node_name = node['name'] if node else "Unknown"
                    status_text = vps.get('status', 'unknown').upper()
                    if vps.get('suspended', False):
                        status_text += " (SUSPENDED)"
                    if vps.get('whitelisted', False):
                        status_text += " (WHITELISTED)"
                    
                    # Add expiration info
                    expiration_text = ""
                    if vps.get('expiration_date'):
                        expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                        days_remaining = (expiration_dt - datetime.now()).days
                        if days_remaining < 0:
                            expiration_text = " • 🔴 EXPIRED"
                        elif days_remaining <= EXPIRATION_WARNING_DAYS:
                            expiration_text = f" • 🟡 EXPIRING ({days_remaining}d)"
                        else:
                            expiration_text = f" • 🟢 ({days_remaining}d)"
                    
                    all_vps.append(f"**{user.name}** - VPS {i+1}: `{vps['container_name']}` - {status_text} (Node: {node_name}){expiration_text}")
            except:
                pass
        vps_text = "\n".join(all_vps)
        chunks = [vps_text[i:i+1024] for i in range(0, len(vps_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"🖥️ All VPS (Part {idx}/{len(chunks)})", f"Complete list of all VPS deployments with expiration status", 0x2ecc71)
            add_field(embed, "VPS Inventory", chunk, False)
            embed.set_footer(text=f"Made by AnkitCoder • VPS Information System")
            await ctx.send(embed=embed)
    else:
        found_vps = None
        found_user = None
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    found_user = await bot.fetch_user(int(user_id))
                    break
            if found_vps:
                break
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        node = get_node(found_vps['node_id'])
        node_name = node['name'] if node else "Unknown"
        
        # Determine status color based on expiration and suspension
        status_color = 0x1a1a1a
        if found_vps.get('suspended', False):
            status_color = 0xffaa00
        elif found_vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(found_vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            if days_remaining < 0:
                status_color = 0xff3366
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                status_color = 0xffaa00
            else:
                status_color = 0x2ecc71
        
        suspended_text = " (SUSPENDED)" if found_vps.get('suspended', False) else ""
        whitelisted_text = " (WHITELISTED)" if found_vps.get('whitelisted', False) else ""
        embed = create_embed(f"🖥️ VPS Information - {container_name}", f"Detailed VPS profile owned by {found_user.mention}{suspended_text}{whitelisted_text}", status_color)
        
        add_field(embed, "👤 Owner", f"**Name:** {found_user.name}\n**ID:** `{found_user.id}`\n**Mention:** {found_user.mention}", False)
        
        add_field(embed, "🌐 Location & Node", f"**Node:** {node_name}\n**Node Type:** {'� Local' if node.get('is_local') else '🌐 Remote'}\n**Node ID:** `{found_vps.get('node_id', 1)}`", True)
        
        add_field(embed, "�📊 Specifications", f"**RAM:** `{found_vps['ram']}`\n**CPU:** `{found_vps['cpu']}` Cores\n**Storage:** `{found_vps['storage']}`\n**Config:** {found_vps.get('config', 'Custom')}", True)
        
        # Status information
        status_info = f"**Current Status:** `{found_vps.get('status', 'unknown').upper()}`\n"
        status_info += f"**Suspended:** {'🟡 Yes' if found_vps.get('suspended', False) else '🟢 No'}\n"
        status_info += f"**Whitelisted:** {'✅ Yes' if found_vps.get('whitelisted', False) else '❌ No'}\n"
        status_info += f"**Created:** `{found_vps.get('created_at', 'Unknown')}`"
        add_field(embed, "📈 Status", status_info, False)
        
        # Expiration information
        if found_vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(found_vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                exp_status = "🔴 EXPIRED"
                exp_color = "FF3366"
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                exp_status = "🟡 EXPIRING SOON"
                exp_color = "FFAA00"
            else:
                exp_status = "🟢 ACTIVE"
                exp_color = "2ECC71"
            
            exp_info = f"**Status:** {exp_status}\n"
            exp_info += f"**Expires On:** `{expiration_dt.strftime('%Y-%m-%d %H:%M:%S')}`\n"
            exp_info += f"**Days Remaining:** `{max(0, days_remaining)}` days\n"
            exp_info += f"**Time Left:** `{max(0, days_remaining)} days` from today"
            add_field(embed, "⏰ Expiration", exp_info, False)
        else:
            add_field(embed, "⏰ Expiration", f"**Status:** 🔵 No expiration date set\n**Action:** Use `{PREFIX}set-expiration` to configure", False)
        
        if found_vps.get('shared_with'):
            shared_users = []
            for shared_id in found_vps['shared_with']:
                try:
                    shared_user = await bot.fetch_user(int(shared_id))
                    shared_users.append(f"• {shared_user.mention} (`{shared_id}`)")
                except:
                    shared_users.append(f"• Unknown User (`{shared_id}`)")
            shared_text = "\n".join(shared_users)
            add_field(embed, "🔗 Shared Access", shared_text, False)
        
        # Port forwarding info
        conn = get_db()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM port_forwards WHERE vps_container = ?', (container_name,))
        port_count = cur.fetchone()[0]
        cur.execute('SELECT * FROM port_forwards WHERE vps_container = ? LIMIT 5', (container_name,))
        ports = cur.fetchall()
        conn.close()
        
        if port_count > 0:
            port_info = f"**Total:** `{port_count}` forwarded ports (TCP & UDP)\n"
            if ports:
                port_info += "**Active Forwards:**\n"
                for p in ports:
                    port_info += f"  • `{p['host_port']}` → VPS:`{p['vps_port']}`\n"
                if port_count > 5:
                    port_info += f"  • ... +{port_count - 5} more"
            add_field(embed, "🌐 Port Forwarding", port_info, False)
        else:
            add_field(embed, "🌐 Port Forwarding", "**Status:** No active port forwards", False)
        
        # OS information
        add_field(embed, "🐧 Operating System", f"`{found_vps.get('os_version', 'ubuntu:22.04')}`", True)
        
        embed.set_footer(text=f"Made by AnkitCoder • VPS Information System • Container: {container_name}")
        await ctx.send(embed=embed)

@bot.command(name='restart-vps')
@is_admin()
async def restart_vps(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Restarting VPS", f"Restarting VPS `{container_name}`..."))
    try:
        await execute_lxc(container_name, f"restart {container_name}", node_id=node_id)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['status'] = 'running'
                    save_vps_data_immediate()
                    break
        await apply_internal_permissions(container_name, node_id)
        await recreate_port_forwards(container_name)
        await ctx.send(embed=create_success_embed("VPS Restarted", f"VPS `{container_name}` has been restarted successfully!"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Restart Failed", f"Error: {str(e)}"))

@bot.command(name='exec')
@is_admin()
async def execute_command(ctx, container_name: str, *, command: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Executing Command", f"Running command in VPS `{container_name}`..."))
    try:
        output = await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{command}\"", node_id=node_id)
        embed = create_embed(f"Command Output - {container_name}", f"Command: `{command}`", 0x1a1a1a)
        if output.strip():
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            add_field(embed, "📤 Output", f"```\n{output}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Execution Failed", f"Error: {str(e)}"))

@bot.command(name='stop-vps-all')
@is_admin()
async def stop_all_vps(ctx):
    embed = create_warning_embed("Stopping All VPS", "⚠️ **WARNING:** This will stop ALL running VPS on all nodes.\n\nThis action cannot be undone. Continue?")
    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="Stop All VPS", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, item: discord.ui.Button):
            await interaction.response.defer()
            try:
                stopped_count = 0
                nodes = get_nodes()
                for node in nodes:
                    if node['is_local']:
                        proc = await asyncio.create_subprocess_exec(
                            "lxc", "stop", "--all", "--force",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        stdout, stderr = await proc.communicate()
                        if proc.returncode != 0:
                            logger.error(f"Failed to stop all on local node: {stderr.decode()}")
                            continue
                    else:
                        url = f"{node['url']}/api/execute"
                        data = {"command": "lxc stop --all --force"}
                        params = {"api_key": node["api_key"]}
                        response = requests.post(url, json=data, params=params)
                        if response.status_code != 200:
                            logger.error(f"Failed to stop all on node {node['name']}")
                            continue
                    for user_id, vps_list in vps_data.items():
                        for vps in vps_list:
                            if vps.get('node_id') == node['id'] and vps.get('status') == 'running':
                                vps['status'] = 'stopped'
                                vps['suspended'] = False
                                stopped_count += 1
                save_vps_data_immediate()
                embed = create_success_embed("All VPS Stopped", f"Successfully stopped {stopped_count} VPS across all nodes.")
                await interaction.followup.send(embed=embed)
            except Exception as e:
                embed = create_error_embed("Error", f"Error stopping VPS: {str(e)}")
                await interaction.followup.send(embed=embed)

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, item: discord.ui.Button):
            await interaction.response.edit_message(embed=create_info_embed("Operation Cancelled", "The stop all VPS operation has been cancelled."))

    await ctx.send(embed=embed, view=ConfirmView())

@bot.command(name='cpu-monitor')
@is_admin()
async def resource_monitor_control(ctx, action: str = "status"):
    global resource_monitor_active
    if action.lower() == "status":
        status = "Active" if resource_monitor_active else "Inactive"
        embed = create_embed("Resource Monitor Status", f"Resource monitoring is currently **{status}** (logs only; no auto-stop)", 0x00ccff if resource_monitor_active else 0xffaa00)
        add_field(embed, "Thresholds", f"{CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM usage", True)
        add_field(embed, "Check Interval", f"60 seconds (all nodes)", True)
        await ctx.send(embed=embed)
    elif action.lower() == "enable":
        resource_monitor_active = True
        await ctx.send(embed=create_success_embed("Resource Monitor Enabled", "Resource monitoring has been enabled."))
    elif action.lower() == "disable":
        resource_monitor_active = False
        await ctx.send(embed=create_warning_embed("Resource Monitor Disabled", "Resource monitoring has been disabled."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Action", f"Use: `{PREFIX}cpu-monitor <status|enable|disable>`"))

@bot.command(name='resize-vps')
@is_admin()
async def resize_vps(ctx, container_name: str, ram: int = None, cpu: int = None, disk: int = None):
    if ram is None and cpu is None and disk is None:
        await ctx.send(embed=create_error_embed("Missing Parameters", "Please specify at least one resource to resize (ram, cpu, or disk)"))
        return
    found_vps = None
    user_id = None
    vps_index = None
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
        return
    node_id = found_vps['node_id']
    was_running = found_vps.get('status') == 'running' and not found_vps.get('suspended', False)
    disk_changed = disk is not None
    if was_running:
        await ctx.send(embed=create_info_embed("Stopping VPS", f"Stopping VPS `{container_name}` to apply resource changes..."))
        try:
            await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
            found_vps['status'] = 'stopped'
            save_vps_data_immediate()
        except Exception as e:
            await ctx.send(embed=create_error_embed("Stop Failed", f"Error stopping VPS: {str(e)}"))
            return
    changes = []
    try:
        new_ram = int(found_vps['ram'].replace('GB', ''))
        new_cpu = int(found_vps['cpu'])
        new_disk = int(found_vps['storage'].replace('GB', ''))
        if ram is not None and ram > 0:
            new_ram = ram
            ram_mb = ram * 1024
            await execute_lxc(container_name, f"config set {container_name} limits.memory {ram_mb}MB", node_id=node_id)
            changes.append(f"RAM: {ram}GB")
        if cpu is not None and cpu > 0:
            new_cpu = cpu
            await execute_lxc(container_name, f"config set {container_name} limits.cpu {cpu}", node_id=node_id)
            changes.append(f"CPU: {cpu} cores")
        if disk is not None and disk > 0:
            new_disk = disk
            await execute_lxc(container_name, f"config device set {container_name} root size={disk}GB", node_id=node_id)
            changes.append(f"Disk: {disk}GB")
        found_vps['ram'] = f"{new_ram}GB"
        found_vps['cpu'] = str(new_cpu)
        found_vps['storage'] = f"{new_disk}GB"
        found_vps['config'] = f"{new_ram}GB RAM / {new_cpu} CPU / {new_disk}GB Disk"
        vps_data[user_id][vps_index] = found_vps
        save_vps_data_immediate()
        if was_running:
            await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
            found_vps['status'] = 'running'
            save_vps_data_immediate()
            await apply_internal_permissions(container_name, node_id)
            await recreate_port_forwards(container_name)
        embed = create_success_embed("VPS Resized", f"Successfully resized resources for VPS `{container_name}`")
        add_field(embed, "Changes Applied", "\n".join(changes), False)
        if disk_changed:
            add_field(embed, "Disk Note", "Run `sudo resize2fs /` inside the VPS to expand the filesystem.", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Resize Failed", f"Error: {str(e)}"))

@bot.command(name='clone-vps')
@is_admin()
async def clone_vps(ctx, container_name: str, new_name: str = None):
    if not new_name:
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        new_name = f"{BOT_NAME.lower()}-{container_name}-clone-{timestamp}"
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Cloning VPS", f"Cloning VPS `{container_name}` to `{new_name}`..."))
    try:
        found_vps = None
        user_id = None
        for uid, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    user_id = uid
                    break
            if found_vps:
                break
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        await execute_lxc(container_name, f"copy {container_name} {new_name}", node_id=node_id)
        await apply_lxc_config(new_name, node_id)
        await execute_lxc(new_name, f"start {new_name}", node_id=node_id)
        await apply_internal_permissions(new_name, node_id)
        await recreate_port_forwards(new_name)
        if user_id not in vps_data:
            vps_data[user_id] = []
        new_vps = found_vps.copy()
        new_vps['container_name'] = new_name
        new_vps['status'] = 'running'
        new_vps['suspended'] = False
        new_vps['whitelisted'] = False
        new_vps['suspension_history'] = []
        new_vps['created_at'] = datetime.now().isoformat()
        new_vps['shared_with'] = []
        new_vps['id'] = None
        vps_data[user_id].append(new_vps)
        save_vps_data_immediate()
        embed = create_success_embed("VPS Cloned", f"Successfully cloned VPS `{container_name}` to `{new_name}`")
        add_field(embed, "New VPS Details", f"**RAM:** {new_vps['ram']}\n**CPU:** {new_vps['cpu']} Cores\n**Storage:** {new_vps['storage']}", False)
        add_field(embed, "Features", "Nesting, Privileged, FUSE, Kernel Modules (Docker Ready), Unprivileged Ports from 0", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Clone Failed", f"Error: {str(e)}"))

@bot.command(name='migrate-vps')
@is_admin()
async def migrate_vps(ctx, container_name: str, target_node_id: int):
    node_id = find_node_id_for_container(container_name)
    target_node = get_node(target_node_id)
    if not target_node:
        await ctx.send(embed=create_error_embed("Invalid Node", "Target node not found."))
        return
    await ctx.send(embed=create_info_embed("Migrating VPS", f"Migrating VPS `{container_name}` to node {target_node['name']}..."))
    try:
        await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
        temp_name = f"{BOT_NAME.lower()}-{container_name}-temp-{int(time.time())}"
        await execute_lxc(container_name, f"copy {container_name} {temp_name} -s {DEFAULT_STORAGE_POOL}", node_id=target_node_id)
        await execute_lxc(container_name, f"delete {container_name} --force", node_id=node_id)
        await execute_lxc(temp_name, f"rename {temp_name} {container_name}", node_id=target_node_id)
        await apply_lxc_config(container_name, target_node_id)
        await execute_lxc(container_name, f"start {container_name}", node_id=target_node_id)
        await apply_internal_permissions(container_name, target_node_id)
        await recreate_port_forwards(container_name)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['node_id'] = target_node_id
                    vps['status'] = 'running'
                    vps['suspended'] = False
                    save_vps_data_immediate()
                    break
        await ctx.send(embed=create_success_embed("VPS Migrated", f"Successfully migrated VPS `{container_name}` to node {target_node['name']}"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Migration Failed", f"Error: {str(e)}"))

@bot.command(name='vps-stats')
@is_admin()
async def vps_stats(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Gathering Statistics", f"Collecting statistics for VPS `{container_name}`..."))
    try:
        stats = await get_container_stats(container_name, node_id)
        embed = create_embed(f"📊 VPS Statistics - {container_name}", f"Resource usage statistics", 0x1a1a1a)
        add_field(embed, "📈 Status", f"**{stats['status'].upper()}**", False)
        add_field(embed, "💻 CPU Usage", f"**{stats['cpu']:.1f}%**", True)
        add_field(embed, "🧠 Memory Usage", f"**{stats['ram']['used']}/{stats['ram']['total']} MB ({stats['ram']['pct']:.1f}%)**", True)
        add_field(embed, "💾 Disk Usage", f"**{stats['disk']}**", True)
        add_field(embed, "⏱️ Uptime", f"**{stats['uptime']}**", True)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Statistics Failed", f"Error: {str(e)}"))


@bot.command(name='node-check')
@is_admin()
async def node_check(ctx, node_id: int):
    """Check node status and available storage pools"""
    node = get_node(node_id)
    if not node:
        await ctx.send(embed=create_error_embed("Node Not Found", f"Node ID {node_id} not found."))
        return
    
    embed = create_info_embed(f"Node Check - {node['name']}", 
                             f"Checking status and configuration of node {node['name']}...")
    
    # Check if node is reachable
    status = await get_node_status(node_id)
    add_field(embed, "📡 Connection Status", status, False)
    
    if status.startswith("🟢"):
        # Try to get storage pools
        try:
            pools_output = await execute_lxc("", "storage list", node_id=node_id, timeout=30)
            add_field(embed, "💾 Available Storage Pools", f"```{pools_output}```", False)
            
            # Try to get default profile
            try:
                profile_output = await execute_lxc("", "profile list", node_id=node_id, timeout=30)
                add_field(embed, "📋 Available Profiles", f"```{profile_output[:500]}...```", False)
            except Exception as e:
                add_field(embed, "📋 Profiles", f"Error: {str(e)[:200]}", False)
                
        except Exception as e:
            add_field(embed, "💾 Storage Pools", f"Error: {str(e)[:200]}", False)
        
        # Check remote API endpoint
        try:
            test_response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
            add_field(embed, "🔌 API Endpoint", f"✅ Reachable\nURL: {node['url']}", False)
        except Exception as e:
            add_field(embed, "🔌 API Endpoint", f"❌ Unreachable\nError: {str(e)[:200]}", False)
    else:
        add_field(embed, "⚠️ Status", "Node is offline or unreachable", False)
    
    await ctx.send(embed=embed)

@bot.command(name='vps-network')
@is_admin()
async def vps_network(ctx, container_name: str, action: str, value: str = None):
    node_id = find_node_id_for_container(container_name)
    if action.lower() not in ["list", "add", "remove", "limit"]:
        await ctx.send(embed=create_error_embed("Invalid Action", f"Use: `{PREFIX}vps-network <container> <list|add|remove|limit> [value]`"))
        return
    try:
        if action.lower() == "list":
            output = await execute_lxc(container_name, f"exec {container_name} -- ip addr", node_id=node_id)
            if len(output) > 1000:
                output = output[:1000] + "\n... (truncated)"
            embed = create_embed(f"🌐 Network Interfaces - {container_name}", "Network configuration", 0x1a1a1a)
            add_field(embed, "Interfaces", f"```\n{output}\n```", False)
            await ctx.send(embed=embed)
        elif action.lower() == "limit" and value:
            await execute_lxc(container_name, f"config device set {container_name} eth0 limits.egress {value}", node_id=node_id)
            await execute_lxc(container_name, f"config device set {container_name} eth0 limits.ingress {value}", node_id=node_id)
            await ctx.send(embed=create_success_embed("Network Limited", f"Set network limit to {value} for `{container_name}`"))
        elif action.lower() == "add" and value:
            await execute_lxc(container_name, f"config device add {container_name} eth1 nic nictype=bridged parent={value}", node_id=node_id)
            await ctx.send(embed=create_success_embed("Network Added", f"Added network interface to VPS `{container_name}` with bridge `{value}`"))
        elif action.lower() == "remove" and value:
            await execute_lxc(container_name, f"config device remove {container_name} {value}", node_id=node_id)
            await ctx.send(embed=create_success_embed("Network Removed", f"Removed network interface `{value}` from VPS `{container_name}`"))
        else:
            await ctx.send(embed=create_error_embed("Invalid Parameters", "Please provide valid parameters for the action"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Network Management Failed", f"Error: {str(e)}"))

@bot.command(name='vps-processes')
@is_admin()
async def vps_processes(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Gathering Processes", f"Listing processes in VPS `{container_name}`..."))
    try:
        output = await execute_lxc(container_name, f"exec {container_name} -- ps aux", node_id=node_id)
        if len(output) > 1000:
            output = output[:1000] + "\n... (truncated)"
        embed = create_embed(f"⚙️ Processes - {container_name}", "Running processes", 0x1a1a1a)
        add_field(embed, "Process List", f"```\n{output}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Process Listing Failed", f"Error: {str(e)}"))

@bot.command(name='vps-logs')
@is_admin()
async def vps_logs(ctx, container_name: str, lines: int = 50):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Gathering Logs", f"Fetching last {lines} lines from VPS `{container_name}`..."))
    try:
        output = await execute_lxc(container_name, f"exec {container_name} -- journalctl -n {lines}", node_id=node_id)
        if len(output) > 1000:
            output = output[:1000] + "\n... (truncated)"
        embed = create_embed(f"📋 Logs - {container_name}", f"Last {lines} log lines", 0x1a1a1a)
        add_field(embed, "System Logs", f"```\n{output}\n```", False)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("Log Retrieval Failed", f"Error: {str(e)}"))

@bot.command(name='vps-uptime')
@is_admin()
async def vps_uptime(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    uptime = await get_container_uptime(container_name, node_id)
    embed = create_info_embed("VPS Uptime", f"Uptime for `{container_name}`: {uptime}")
    await ctx.send(embed=embed)

@bot.command(name='vps-password')
@is_admin()
async def vps_password(ctx, container_name: str = None):
    """View or manage VPS root passwords"""
    if not container_name:
        # Show all passwords for all VPS
        password_list = []
        for user_id, vps_list in vps_data.items():
            try:
                user = await bot.fetch_user(int(user_id))
                for vps in vps_list:
                    password = vps.get('root_password', 'Not Set')
                    if password == 'Not Set':
                        password_display = "❌ Not Set"
                    else:
                        password_display = f"🔐 `{password}`"
                    password_list.append(f"**{user.name}** - `{vps['container_name']}`: {password_display}")
            except:
                pass
        
        if not password_list:
            await ctx.send(embed=create_info_embed("No Passwords", "No VPS passwords found in database."))
            return
        
        password_text = "\n".join(password_list)
        chunks = [password_text[i:i+1024] for i in range(0, len(password_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"🔐 VPS Root Passwords (Part {idx}/{len(chunks)})", "Root passwords for all VPS", 0xff6b6b)
            add_field(embed, "Passwords", chunk, False)
            add_field(embed, "⚠️ Security Notice", "These passwords are sensitive. Do not share them publicly.", False)
            embed.set_footer(text=f"Made by AnkitCoder • Password Management")
            await ctx.send(embed=embed)
    else:
        # Show password for specific VPS
        found_vps = None
        found_user = None
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    found_user = await bot.fetch_user(int(user_id))
                    break
            if found_vps:
                break
        
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        
        password = found_vps.get('root_password', 'Not Set')
        if password == 'Not Set':
            embed = create_info_embed("Password Not Set", f"VPS `{container_name}` does not have a stored password.")
        else:
            embed = create_success_embed("VPS Password", f"Root password for VPS `{container_name}`")
            add_field(embed, "Owner", f"{found_user.mention}", True)
            add_field(embed, "Container", f"`{container_name}`", True)
            add_field(embed, "🔐 Password", f"`{password}`", False)
            add_field(embed, "Usage", f"SSH as `root` with this password", False)
        
        embed.set_footer(text=f"Made by AnkitCoder • Password Information")
        await ctx.send(embed=embed)

@bot.command(name='suspend-vps')
@is_admin()
async def suspend_vps(ctx, container_name: str, *, reason: str = "Admin action"):
    node_id = find_node_id_for_container(container_name)
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if vps.get('status') != 'running':
                    await ctx.send(embed=create_error_embed("Cannot Suspend", "VPS must be running to suspend."))
                    return
                try:
                    await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
                    vps['status'] = 'stopped'
                    vps['suspended'] = True
                    if 'suspension_history' not in vps:
                        vps['suspension_history'] = []
                    vps['suspension_history'].append({
                        'time': datetime.now().isoformat(),
                        'reason': reason,
                        'by': f"{ctx.author.name} ({ctx.author.id})"
                    })
                    save_vps_data_immediate()
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Suspend Failed", str(e)))
                    return
                try:
                    owner = await bot.fetch_user(int(uid))
                    embed = create_warning_embed("🚨 VPS Suspended", f"Your VPS `{container_name}` has been suspended by an admin.\n\n**Reason:** {reason}\n\nContact an admin to unsuspend.")
                    await owner.send(embed=embed)
                except Exception as dm_e:
                    logger.error(f"Failed to DM owner {uid}: {dm_e}")
                await ctx.send(embed=create_success_embed("VPS Suspended", f"VPS `{container_name}` suspended. Reason: {reason}"))
                found = True
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='unsuspend-vps')
@is_admin()
async def unsuspend_vps(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    found = False
    for uid, lst in vps_data.items():
        for vps in lst:
            if vps['container_name'] == container_name:
                if not vps.get('suspended', False):
                    await ctx.send(embed=create_error_embed("Not Suspended", "VPS is not suspended."))
                    return
                try:
                    vps['suspended'] = False
                    vps['status'] = 'running'
                    await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
                    await apply_internal_permissions(container_name, node_id)
                    await recreate_port_forwards(container_name)
                    save_vps_data_immediate()
                    await ctx.send(embed=create_success_embed("VPS Unsuspended", f"VPS `{container_name}` unsuspended and started."))
                    found = True
                except Exception as e:
                    await ctx.send(embed=create_error_embed("Start Failed", str(e)))
                try:
                    owner = await bot.fetch_user(int(uid))
                    embed = create_success_embed("🟢 VPS Unsuspended", f"Your VPS `{container_name}` has been unsuspended by an admin.\nYou can now manage it again.")
                    await owner.send(embed=embed)
                except Exception as dm_e:
                    logger.error(f"Failed to DM owner {uid} about unsuspension: {dm_e}")
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='suspension-logs')
@is_admin()
async def suspension_logs(ctx, container_name: str = None):
    if container_name:
        found = None
        for lst in vps_data.values():
            for vps in lst:
                if vps['container_name'] == container_name:
                    found = vps
                    break
            if found:
                break
        if not found:
            await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))
            return
        history = found.get('suspension_history', [])
        if not history:
            await ctx.send(embed=create_info_embed("No Suspensions", f"No suspension history for `{container_name}`."))
            return
        embed = create_embed("Suspension History", f"For `{container_name}`")
        text = []
        for h in sorted(history, key=lambda x: x['time'], reverse=True)[:10]:
            t = datetime.fromisoformat(h['time']).strftime('%Y-%m-%d %H:%M:%S')
            text.append(f"**{t}** - {h['reason']} (by {h['by']})")
        add_field(embed, "History", "\n".join(text), False)
        if len(history) > 10:
            add_field(embed, "Note", "Showing last 10 entries.")
        await ctx.send(embed=embed)
    else:
        all_logs = []
        for uid, lst in vps_data.items():
            for vps in lst:
                h = vps.get('suspension_history', [])
                for event in sorted(h, key=lambda x: x['time'], reverse=True):
                    t = datetime.fromisoformat(event['time']).strftime('%Y-%m-%d %H:%M')
                    all_logs.append(f"**{t}** - VPS `{vps['container_name']}` (Owner: <@{uid}>) - {event['reason']} (by {event['by']})")
        if not all_logs:
            await ctx.send(embed=create_info_embed("No Suspensions", "No suspension events recorded."))
            return
        logs_text = "\n".join(all_logs)
        chunks = [logs_text[i:i+1024] for i in range(0, len(logs_text), 1024)]
        for idx, chunk in enumerate(chunks, 1):
            embed = create_embed(f"Suspension Logs (Part {idx})", f"Global suspension events (newest first)")
            add_field(embed, "Events", chunk, False)
            await ctx.send(embed=embed)

@bot.command(name='apply-permissions')
@is_admin()
async def apply_permissions(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Applying Permissions", f"Applying advanced permissions to `{container_name}`..."))
    try:
        status = await get_container_status(container_name, node_id)
        was_running = status == 'running'
        if was_running:
            await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
        await apply_lxc_config(container_name, node_id)
        await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
        await apply_internal_permissions(container_name, node_id)
        await recreate_port_forwards(container_name)
        for user_id, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    vps['status'] = 'running'
                    vps['suspended'] = False
                    save_vps_data_immediate()
                    break
        await ctx.send(embed=create_success_embed("Permissions Applied", f"Advanced permissions applied to VPS `{container_name}`. Docker-ready with unprivileged ports!"))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Apply Failed", f"Error: {str(e)}"))

@bot.command(name='resource-check')
@is_admin()
async def resource_check(ctx):
    suspended_count = 0
    embed = create_info_embed("Resource Check", "Checking all running VPS for high resource usage...")
    msg = await ctx.send(embed=embed)
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps.get('status') == 'running' and not vps.get('suspended', False) and not vps.get('whitelisted', False):
                container = vps['container_name']
                node_id = vps['node_id']
                stats = await get_container_stats(container, node_id)
                cpu = stats['cpu']
                ram = stats['ram']['pct']
                if cpu > CPU_THRESHOLD or ram > RAM_THRESHOLD:
                    reason = f"High resource usage: CPU {cpu:.1f}%, RAM {ram:.1f}% (threshold: {CPU_THRESHOLD}% CPU / {RAM_THRESHOLD}% RAM)"
                    logger.warning(f"Suspending {container}: {reason}")
                    try:
                        await execute_lxc(container, f"stop {container}", node_id=node_id)
                        vps['status'] = 'stopped'
                        vps['suspended'] = True
                        if 'suspension_history' not in vps:
                            vps['suspension_history'] = []
                        vps['suspension_history'].append({
                            'time': datetime.now().isoformat(),
                            'reason': reason,
                            'by': 'Manual Resource Check'
                        })
                        save_vps_data_immediate()
                        try:
                            owner = await bot.fetch_user(int(user_id))
                            warn_embed = create_warning_embed("🚨 VPS Auto-Suspended", f"Your VPS `{container}` has been suspended due to high resource usage.\n\n**Reason:** {reason}\n\nContact admin to unsuspend and address the issue.")
                            await owner.send(embed=warn_embed)
                        except Exception as dm_e:
                            logger.error(f"Failed to DM owner {user_id}: {dm_e}")
                        suspended_count += 1
                    except Exception as e:
                        logger.error(f"Failed to suspend {container}: {e}")
    final_embed = create_info_embed("Resource Check Complete", f"Checked all VPS. Suspended {suspended_count} high-usage VPS.")
    await msg.edit(embed=final_embed)

@bot.command(name='whitelist-vps')
@is_admin()
async def whitelist_vps(ctx, container_name: str, action: str):
    if action.lower() not in ['add', 'remove']:
        await ctx.send(embed=create_error_embed("Invalid Action", f"Use: `{PREFIX}whitelist-vps <container> <add|remove>`"))
        return
    found = False
    for user_id, vps_list in vps_data.items():
        for vps in vps_list:
            if vps['container_name'] == container_name:
                if action.lower() == 'add':
                    vps['whitelisted'] = True
                    msg = "added to whitelist (exempt from auto-suspension)"
                else:
                    vps['whitelisted'] = False
                    msg = "removed from whitelist"
                save_vps_data_immediate()
                await ctx.send(embed=create_success_embed("Whitelist Updated", f"VPS `{container_name}` {msg}."))
                found = True
                break
        if found:
            break
    if not found:
        await ctx.send(embed=create_error_embed("Not Found", f"VPS `{container_name}` not found."))

@bot.command(name='backup-db')
@is_admin()
async def backup_db(ctx):
    try:
        backup_database()
        backup_files = sorted(DB_BACKUP_DIR.glob("vps_backup_*.db"))
        latest = backup_files[-1].name if backup_files else "backup"
        await ctx.send(
            embed=create_success_embed(
                "DB Backup Created",
                f"Consistent SQLite backup created: `{latest}`"
            )
        )
    except Exception as e:
        await ctx.send(embed=create_error_embed("Backup Failed", f"Error: {str(e)}"))

@bot.command(name='repair-ports')
@is_admin()
async def repair_ports(ctx, container_name: str):
    await ctx.send(embed=create_info_embed("Repairing Ports", f"Re-adding port forward devices for `{container_name}`..."))
    try:
        readded = await recreate_port_forwards(container_name)
        await ctx.send(embed=create_success_embed("Ports Repaired", f"Re-added {readded} port forwards for `{container_name}`."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Repair Failed", f"Error: {str(e)}"))

@bot.command(name='set-expiration')
@is_admin()
async def set_expiration(ctx, container_name: str, days: int):
    """Set VPS expiration date (admin only)"""
    if days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Days", "Days must be a positive number."))
        return
    
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
        return
    
    # Calculate expiration date
    expiration_date = (datetime.now() + timedelta(days=days)).isoformat()
    found_vps['expiration_date'] = expiration_date
    vps_data[user_id][vps_index] = found_vps
    save_vps_data_immediate()
    
    # Get owner info
    try:
        owner = await bot.fetch_user(int(user_id))
        owner_mention = owner.mention
    except:
        owner_mention = f"User {user_id}"
    
    embed = create_success_embed("Expiration Date Set", 
        f"VPS `{container_name}` expiration date set for {days} days from now")
    add_field(embed, "Owner", owner_mention, True)
    add_field(embed, "Expires On", datetime.fromisoformat(expiration_date).strftime('%Y-%m-%d %H:%M:%S'), True)
    add_field(embed, "Days Remaining", str(days), True)
    
    await ctx.send(embed=embed)
    
    # Notify owner
    try:
        owner = await bot.fetch_user(int(user_id))
        dm_embed = create_info_embed("⏰ VPS Expiration Date Set",
            f"Your VPS `{container_name}` will expire in {days} days.\n\n"
            f"**Expires:** {datetime.fromisoformat(expiration_date).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Contact admin to renew your VPS before it expires.")
        await owner.send(embed=dm_embed)
    except:
        pass

@bot.command(name='renew-vps')
@is_admin()
async def renew_vps(ctx, container_name: str, additional_days: int = None):
    """Renew VPS expiration date (admin only)"""
    if additional_days is None:
        additional_days = DEFAULT_VPS_EXPIRATION_DAYS
    
    if additional_days <= 0:
        await ctx.send(embed=create_error_embed("Invalid Days", "Days must be a positive number."))
        return
    
    found_vps = None
    user_id = None
    vps_index = None
    
    for uid, vps_list in vps_data.items():
        for i, vps in enumerate(vps_list):
            if vps['container_name'] == container_name:
                found_vps = vps
                user_id = uid
                vps_index = i
                break
        if found_vps:
            break
    
    if not found_vps:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
        return
    
    # Get current expiration or use today
    if found_vps.get('expiration_date'):
        current_expiration = datetime.fromisoformat(found_vps['expiration_date'])
    else:
        current_expiration = datetime.now()
    
    # Calculate new expiration date
    new_expiration_date = (current_expiration + timedelta(days=additional_days)).isoformat()
    found_vps['expiration_date'] = new_expiration_date
    
    # Unsuspend if it was suspended due to expiration
    if found_vps.get('suspended', False):
        found_vps['suspended'] = False
    
    vps_data[user_id][vps_index] = found_vps
    save_vps_data_immediate()
    
    # Get owner info
    try:
        owner = await bot.fetch_user(int(user_id))
        owner_mention = owner.mention
    except:
        owner_mention = f"User {user_id}"
    
    embed = create_success_embed("VPS Renewed", 
        f"VPS `{container_name}` has been renewed")
    add_field(embed, "Owner", owner_mention, True)
    add_field(embed, "Added Days", str(additional_days), True)
    add_field(embed, "Previous Expiration", current_expiration.strftime('%Y-%m-%d %H:%M:%S'), True)
    add_field(embed, "New Expiration", datetime.fromisoformat(new_expiration_date).strftime('%Y-%m-%d %H:%M:%S'), True)
    
    await ctx.send(embed=embed)
    
    # Notify owner
    try:
        owner = await bot.fetch_user(int(user_id))
        dm_embed = create_success_embed("✅ VPS Renewed",
            f"Your VPS `{container_name}` has been renewed!\n\n"
            f"**New Expiration:** {datetime.fromisoformat(new_expiration_date).strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Thank you for using {BOT_NAME}!")
        await owner.send(embed=dm_embed)
    except:
        pass

@bot.command(name='vps-expiration')
@is_admin()
async def check_expiration(ctx, container_name: str = None):
    """Check VPS expiration status (admin only)"""
    if container_name:
        # Check specific VPS
        found_vps = None
        user_id = None
        
        for uid, vps_list in vps_data.items():
            for vps in vps_list:
                if vps['container_name'] == container_name:
                    found_vps = vps
                    user_id = uid
                    break
            if found_vps:
                break
        
        if not found_vps:
            await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS found with container name: `{container_name}`"))
            return
        
        # Get owner info
        try:
            owner = await bot.fetch_user(int(user_id))
            owner_mention = owner.mention
        except:
            owner_mention = f"User {user_id}"
        
        embed = create_info_embed("VPS Expiration Status", f"Details for `{container_name}`")
        add_field(embed, "Owner", owner_mention, True)
        add_field(embed, "Container", f"`{container_name}`", True)
        
        if found_vps.get('expiration_date'):
            expiration_dt = datetime.fromisoformat(found_vps['expiration_date'])
            days_remaining = (expiration_dt - datetime.now()).days
            
            if days_remaining < 0:
                status = "🔴 EXPIRED"
                color = 0xff3366
            elif days_remaining <= EXPIRATION_WARNING_DAYS:
                status = "🟡 EXPIRING SOON"
                color = 0xffaa00
            else:
                status = "🟢 ACTIVE"
                color = 0x00ff88
            
            embed.color = color
            add_field(embed, "Status", status, True)
            add_field(embed, "Expiration Date", expiration_dt.strftime('%Y-%m-%d %H:%M:%S'), True)
            add_field(embed, "Days Remaining", str(max(0, days_remaining)), True)
        else:
            add_field(embed, "Status", "🔵 NO EXPIRATION SET", False)
        
        await ctx.send(embed=embed)
    else:
        # List all VPS with expiration status
        embed = create_info_embed("📋 All VPS Expiration Status", "Global expiration overview")
        
        expiring_soon = []
        expired = []
        active = []
        no_expiration = []
        
        for user_id, vps_list in vps_data.items():
            try:
                owner = await bot.fetch_user(int(user_id))
                owner_name = owner.name
            except:
                owner_name = f"Unknown ({user_id})"
            
            for vps in vps_list:
                if vps.get('expiration_date'):
                    expiration_dt = datetime.fromisoformat(vps['expiration_date'])
                    days_remaining = (expiration_dt - datetime.now()).days
                    
                    status_line = f"**{owner_name}** - `{vps['container_name']}`\n" \
                                 f"Expires: {expiration_dt.strftime('%Y-%m-%d')} ({days_remaining} days)"
                    
                    if days_remaining < 0:
                        expired.append(status_line)
                    elif days_remaining <= EXPIRATION_WARNING_DAYS:
                        expiring_soon.append(status_line)
                    else:
                        active.append(status_line)
                else:
                    no_expiration.append(f"**{owner_name}** - `{vps['container_name']}`")
        
        if expiring_soon:
            add_field(embed, "🟡 Expiring Soon", "\n\n".join(expiring_soon), False)
        if expired:
            add_field(embed, "🔴 Expired", "\n\n".join(expired), False)
        if active:
            add_field(embed, "🟢 Active", "\n\n".join(active[:10]), False)
            if len(active) > 10:
                add_field(embed, "Note", f"Showing 10 of {len(active)} active VPS", False)
        if no_expiration:
            add_field(embed, "🔵 No Expiration Set", "\n".join(no_expiration[:5]), False)
            if len(no_expiration) > 5:
                add_field(embed, "Note", f"Total {len(no_expiration)} VPS without expiration date", False)
        
        await ctx.send(embed=embed)

@bot.command(name='about')
async def about(ctx):
    total_users = len(vps_data)
    total_vps = sum(len(vps_list) for vps_list in vps_data.values())
    latency = round(bot.latency * 1000)
    main_admin = await bot.fetch_user(MAIN_ADMIN_ID)
    embed = create_info_embed(f"About {BOT_NAME}", f"Bot information and statistics")
    add_field(embed, "Bot Name", BOT_NAME, True)
    add_field(embed, "Main Owner", main_admin.mention, True)
    add_field(embed, "Developer", BOT_DEVELOPER, True)
    add_field(embed, "Ping", f"{latency}ms", True)
    add_field(embed, "Version", BOT_VERSION, True)
    add_field(embed, "Total VPS", str(total_vps), True)
    add_field(embed, "Total Users", str(total_users), True)
    await ctx.send(embed=embed)


@bot.command(name='quickhelp')
async def quick_help(ctx):
    """Show quick reference for common tasks"""
    user_id = str(ctx.author.id)
    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    
    embed = create_info_embed("🚀 Quick Help Reference", 
        f"Quick reference for common tasks. Use `{PREFIX}help` for complete command list.")
    
    # Common user tasks
    add_field(embed, "👤 For Users", 
        f"• `{PREFIX}myvps` - List your VPS\n"
        f"• `{PREFIX}manage` - Start/stop/manage VPS\n"
        f"• `{PREFIX}ports` - Manage port forwarding\n"
        f"• `{PREFIX}share-user @user 1` - Share VPS #1\n"
        f"• `{PREFIX}about` - Bot information", False)
    
    # VPS management
    add_field(embed, "🖥️ VPS Control", 
        f"• In `{PREFIX}manage`: Click ▶ to start VPS\n"
        f"• In `{PREFIX}manage`: Click ⏸ to stop VPS\n"
        f"• In `{PREFIX}manage`: Click 🔑 for SSH access\n"
        f"• In `{PREFIX}manage`: Click 📊 for live stats\n"
        f"• In `{PREFIX}manage`: Click 🔄 to reinstall OS", False)
    
    # Troubleshooting
    add_field(embed, "🔧 Common Issues", 
        f"• Ports not working? Use `{PREFIX}repair-ports <container>` (admin)\n"
        "• VPS suspended? Contact admin to unsuspend\n"
        "• Need more resources? Contact admin for upgrade\n"
        "• SSH not working? Try reinstall with different OS", False)
    
    if is_admin_user:
        add_field(embed, "🛡️ Admin Quick Actions", 
            f"• `{PREFIX}create 2 2 20 @user` - Create 2GB/2CPU/20GB VPS\n"
            f"• `{PREFIX}userinfo @user` - Check user details\n"
            f"• `{PREFIX}node list` - List all nodes\n"
            f"• `{PREFIX}serverstats` - System overview\n"
            f"• `{PREFIX}suspend-vps <container> <reason>` - Suspend VPS", False)
    
    embed.set_footer(text=f"Made by AnkitCoder • Use {PREFIX}help for complete command list")
    await ctx.send(embed=embed)

@bot.command(name='help-search')
async def help_search(ctx, *, search_term: str = None):
    """Search for commands"""
    if not search_term:
        await show_help(ctx)
        return
    
    search_term = search_term.lower()
    user_id = str(ctx.author.id)
    is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
    is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
    
    # Build complete command list based on permissions
    all_commands = []
    
    # User commands (always available)
    user_categories = ["user", "vps", "ports", "system", "bot"]
    for cat in user_categories:
        all_commands.extend(HelpView(ctx).command_categories[cat]["commands"])
    
    # Admin commands
    if is_admin_user:
        all_commands.extend(HelpView(ctx).command_categories["admin"]["commands"])
        all_commands.extend(HelpView(ctx).command_categories["nodes"]["commands"])
    
    # Main admin commands
    if is_main_admin_user:
        all_commands.extend(HelpView(ctx).command_categories["main_admin"]["commands"])
    
    # Search through commands
    matches = []
    for cmd, desc in all_commands:
        if (search_term in cmd.lower() or search_term in desc.lower()):
            matches.append((cmd, desc))
    
    if not matches:
        embed = create_info_embed("🔍 No Results Found",
            f"No commands found matching '{search_term}'. Try a different search term.")
        await ctx.send(embed=embed)
        return
    
    # Show results
    embed = create_info_embed(f"🔍 Search Results for '{search_term}'",
        f"Found {len(matches)} command(s) matching your search.")
    
    # Group matches by category
    results_text = "\n".join([f"**{cmd}** - {desc}" for cmd, desc in matches[:15]])
    add_field(embed, "Matching Commands", results_text, False)
    
    if len(matches) > 15:
        add_field(embed, "Note", f"Showing 15 of {len(matches)} matches. Try a more specific search.", False)
    
    embed.set_footer(text=f"Made by AnkitCoder • Use {PREFIX}help for complete list")
    await ctx.send(embed=embed)    

@bot.command(name='node')
@is_admin()
async def node_cmd(ctx, sub: str, *args):
    if sub == 'create':
        await ctx.send("Enter node name:")
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        name = (await bot.wait_for('message', check=check)).content.strip()
        await ctx.send("Enter location:")
        location = (await bot.wait_for('message', check=check)).content.strip()
        await ctx.send("Enter total VPS capacity:")
        total_vps_str = (await bot.wait_for('message', check=check)).content.strip()
        try:
            total_vps = int(total_vps_str)
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid Input", "Total VPS must be an integer."))
            return
        await ctx.send("Enter tags (comma separated):")
        tags_str = (await bot.wait_for('message', check=check)).content.strip()
        tags = [t.strip() for t in tags_str.split(',') if t.strip()]
        tags_json = json.dumps(tags)
        await ctx.send("Enter node URL (e.g., http://ip:port or https://ip:port) or leave blank for local:")
        url_str = (await bot.wait_for('message', check=check)).content.strip()
        
        # Normalize URL if provided
        if url_str:
            if not url_str.startswith('http://') and not url_str.startswith('https://'):
                url_str = f'http://{url_str}'
            url = url_str
        else:
            url = None
        
        is_local = 1 if not url else 0
        api_key = None if is_local else ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute('INSERT INTO nodes (name, location, total_vps, tags, api_key, url, is_local) VALUES (?, ?, ?, ?, ?, ?, ?)',
                        (name, location, total_vps, tags_json, api_key, url, is_local))
            conn.commit()
            node_id = cur.lastrowid
            embed = create_success_embed("Node Created", f"ID: {node_id}\nName: {name}\nLocation: {location}\nCapacity: {total_vps}\nTags: {', '.join(tags)}")
            if not is_local:
                add_field(embed, "API Key", api_key, False)
                add_field(embed, "URL", url, False)
                add_field(embed, "Setup", f"Run `python node-agent.py --api_key={api_key} --port=PORT` on the node server.")
            await ctx.send(embed=embed)
        except sqlite3.IntegrityError:
            await ctx.send(embed=create_error_embed("Error", "Node name already exists."))
        conn.close()
    elif sub == 'list':
        nodes = get_nodes()
        embed = create_info_embed("Nodes List", "")
        for n in nodes:
            status = "Local" if n['is_local'] else "Down"
            if not n['is_local']:
                try:
                    response = requests.get(f"{n['url']}/api/ping", params={'api_key': n['api_key']}, timeout=5)
                    status = "Up" if response.status_code == 200 else "Down"
                except:
                    pass
            field = f"ID: {n['id']}\nName: {n['name']}\nLocation: {n['location']}\nCapacity: {n['total_vps']}\nTags: {', '.join(n['tags'])}\nStatus: {status}"
            if not n['is_local']:
                field += f"\nURL: {n['url']}"
            add_field(embed, f"Node {n['id']}", field, False)
        await ctx.send(embed=embed)
    elif sub == 'edit':
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node edit <id>"))
            return
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        await ctx.send(f"Editing node {node['name']}. Enter new name ( . to skip):")
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        new_name = (await bot.wait_for('message', check=check)).content.strip()
        if new_name != '.':
            node['name'] = new_name
        await ctx.send("New location ( . to skip):")
        new_loc = (await bot.wait_for('message', check=check)).content.strip()
        if new_loc != '.':
            node['location'] = new_loc
        await ctx.send("New total VPS capacity ( . to skip):")
        new_total = (await bot.wait_for('message', check=check)).content.strip()
        if new_total != '.':
            node['total_vps'] = int(new_total)
        await ctx.send("New tags (comma separated, . to skip):")
        new_tags = (await bot.wait_for('message', check=check)).content.strip()
        if new_tags != '.':
            node['tags'] = [t.strip() for t in new_tags.split(',') if t.strip()]
        
        # NEW: Add conversion option between Local and Dynamic
        if node['is_local']:
            await ctx.send("Convert Local Node to Dynamic URL-based Node? (y/n):")
            convert = (await bot.wait_for('message', check=check)).content.strip().lower()
            if convert == 'y':
                await ctx.send("Enter node URL (e.g., http://ip:port or https://ip:port):")
                url_str = (await bot.wait_for('message', check=check)).content.strip()
                if not url_str:
                    await ctx.send(embed=create_error_embed("Error", "URL cannot be empty for dynamic node."))
                    return
                
                # Normalize URL - add http:// if not present
                if not url_str.startswith('http://') and not url_str.startswith('https://'):
                    url_str = f'http://{url_str}'
                
                node['url'] = url_str
                node['is_local'] = 0
                node['api_key'] = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
                await ctx.send(f"✅ Node converted to Dynamic!\n\n**URL:** `{url_str}`\n**Generated API Key:** `{node['api_key']}`\n\n**Setup Command:**\n```\npython node-agent.py --api_key={node['api_key']} --port=PORT\n```")
        else:
            await ctx.send("Convert Dynamic Node to Local? (y/n):")
            convert = (await bot.wait_for('message', check=check)).content.strip().lower()
            if convert == 'y':
                node['url'] = None
                node['api_key'] = None
                node['is_local'] = 1
                await ctx.send("✅ Node converted to Local!")
            else:
                await ctx.send("New URL ( . to skip):")
                new_url = (await bot.wait_for('message', check=check)).content.strip()
                if new_url != '.':
                    # Normalize URL - add http:// if not present
                    if not new_url.startswith('http://') and not new_url.startswith('https://'):
                        new_url = f'http://{new_url}'
                    node['url'] = new_url
                await ctx.send("Regenerate API key? (y/n):")
                regen = (await bot.wait_for('message', check=check)).content.strip().lower()
                if regen == 'y':
                    node['api_key'] = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute('UPDATE nodes SET name=?, location=?, total_vps=?, tags=?, api_key=?, url=?, is_local=? WHERE id=?',
                    (node['name'], node['location'], node['total_vps'], json.dumps(node['tags']), node.get('api_key'), node.get('url'), node['is_local'], node_id))
        conn.commit()
        conn.close()
        embed = create_success_embed("Node Updated", f"ID: {node_id}\nName: {node['name']}\nLocation: {node['location']}\nCapacity: {node['total_vps']}\nTags: {', '.join(node['tags'])}\nType: {'Local' if node['is_local'] else 'Dynamic'}")
        if not node['is_local']:
            add_field(embed, "API Key", node['api_key'], False)
            add_field(embed, "URL", node['url'], False)
        await ctx.send(embed=embed)
    
    # NEW: Add delete subcommand
    elif sub == 'delete':
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node delete <id> [force]"))
            return
        
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        
        force = False
        if len(args) > 1 and args[1].lower() == 'force':
            force = True
        elif len(args) > 1:
            await ctx.send(embed=create_error_embed("Invalid Argument", "Optional argument must be 'force'."))
            return
        
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        
        # Check if this is the local node
        if node['is_local']:
            await ctx.send(embed=create_error_embed("Cannot Delete", "Cannot delete the local node."))
            return
        
        # Check if node has any VPS assigned
        vps_count = get_current_vps_count(node_id)
        if not force and vps_count > 0:
            await ctx.send(embed=create_error_embed("Cannot Delete", 
                f"Node has {vps_count} VPS assigned. Migrate or delete them first, or use 'force' to delete all VPS and the node."))
            return
        
        # Prepare warning message
        warning_msg = f"Are you sure you want to delete node **{node['name']}** (ID: {node_id})?\n\n"
        warning_msg += f"**Location:** {node['location']}\n"
        warning_msg += f"**Tags:** {', '.join(node['tags'])}\n\n"
        if force and vps_count > 0:
            warning_msg += f"**WARNING: Force mode will delete all {vps_count} VPS on this node first!**\n\n"
        warning_msg += "This action cannot be undone!"
        
        embed = create_warning_embed("⚠️ Delete Node", warning_msg)
        
        class ConfirmDelete(discord.ui.View):
            def __init__(self, node_id, node_name, force, vps_count):
                super().__init__(timeout=60)
                self.node_id = node_id
                self.node_name = node_name
                self.force = force
                self.vps_count = vps_count
            
            @discord.ui.button(label="Delete Node", style=discord.ButtonStyle.danger)
            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can confirm."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.defer()
                
                conn = get_db()
                cur = conn.cursor()
                
                if self.force and self.vps_count > 0:
                    # Force delete all VPS on this node
                    cur.execute('DELETE FROM vps WHERE node_id = ?', (self.node_id,))
                
                # Delete the node from database
                cur.execute('DELETE FROM nodes WHERE id = ?', (self.node_id,))
                
                conn.commit()
                conn.close()
                
                msg = f"Node **{self.node_name}** (ID: {self.node_id}) has been deleted."
                if self.force and self.vps_count > 0:
                    msg += f" All {self.vps_count} VPS on the node were also deleted."
                
                success_embed = create_success_embed("Node Deleted", msg)
                await inter.followup.send(embed=success_embed)
                self.stop()
            
            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can cancel."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.edit_message(
                    embed=create_info_embed("Deletion Cancelled", "Node deletion was cancelled."),
                    view=None
                )
                self.stop()
        
        await ctx.send(embed=embed, view=ConfirmDelete(node_id, node['name'], force, vps_count))
    
    elif sub == 'status':
        # New: Check node status
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node status <id>"))
            return
        
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        
        embed = create_info_embed(f"Node Status - {node['name']}")
        
        if node['is_local']:
            status = "🟢 Local Node"
            cpu_usage = get_host_cpu_usage()
            ram_usage = get_host_ram_usage()
            add_field(embed, "Status", status, True)
            add_field(embed, "CPU Usage", f"{cpu_usage:.1f}%", True)
            add_field(embed, "RAM Usage", f"{ram_usage:.1f}%", True)
        else:
            try:
                response = requests.get(f"{node['url']}/api/ping", params={'api_key': node['api_key']}, timeout=5)
                if response.status_code == 200:
                    status = "🟢 Online"
                    try:
                        stats_response = requests.get(f"{node['url']}/api/get_host_stats", 
                                                    params={'api_key': node['api_key']}, 
                                                    timeout=5)
                        if stats_response.status_code == 200:
                            stats = stats_response.json()
                            cpu_usage = stats.get('cpu', 0.0)
                            ram_usage = stats.get('ram', 0.0)
                            add_field(embed, "CPU Usage", f"{cpu_usage:.1f}%", True)
                            add_field(embed, "RAM Usage", f"{ram_usage:.1f}%", True)
                    except:
                        cpu_usage = "Unknown"
                        ram_usage = "Unknown"
                else:
                    status = "🔴 Offline"
            except:
                status = "🔴 Offline"
            
            add_field(embed, "Status", status, True)
        
        vps_count = get_current_vps_count(node_id)
        capacity = node['total_vps']
        usage_percentage = (vps_count / capacity * 100) if capacity > 0 else 0
        
        add_field(embed, "VPS Capacity", f"{vps_count}/{capacity} ({usage_percentage:.1f}%)", True)
        add_field(embed, "Location", node['location'], True)
        add_field(embed, "Tags", ", ".join(node['tags']), True)
        
        if not node['is_local']:
            add_field(embed, "URL", node['url'], False)
        
        await ctx.send(embed=embed)
    
    elif sub == 'regen-key':
        # NEW: Regenerate API key for dynamic node
        if not args:
            await ctx.send(embed=create_error_embed("Usage", f"{PREFIX}node regen-key <id>"))
            return
        
        try:
            node_id = int(args[0])
        except ValueError:
            await ctx.send(embed=create_error_embed("Invalid ID", "Node ID must be an integer."))
            return
        
        node = get_node(node_id)
        if not node:
            await ctx.send(embed=create_error_embed("Not Found", "Node not found."))
            return
        
        # Check if node is local
        if node['is_local']:
            await ctx.send(embed=create_error_embed("Error", "Cannot regenerate API key for Local nodes. Only Dynamic nodes have API keys."))
            return
        
        # Confirm regeneration
        warning_embed = create_warning_embed("⚠️ Regenerate API Key", 
            f"You are about to regenerate the API key for node **{node['name']}**.\n\n"
            f"**Current API Key:** `{node['api_key']}`\n\n"
            f"**This action will:**\n"
            f"• Generate a new 32-character API key\n"
            f"• Invalidate the old API key\n"
            f"• Require updating the remote node agent\n\n"
            f"Are you sure you want to continue?")
        
        class ConfirmRegenKey(discord.ui.View):
            def __init__(self, node_id, node):
                super().__init__(timeout=60)
                self.node_id = node_id
                self.node = node
            
            @discord.ui.button(label="Regenerate Key", style=discord.ButtonStyle.danger)
            async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can confirm."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.defer()
                
                # Generate new API key
                new_api_key = ''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=32))
                
                # Update database
                conn = get_db()
                cur = conn.cursor()
                cur.execute('UPDATE nodes SET api_key=? WHERE id=?', (new_api_key, self.node_id))
                conn.commit()
                conn.close()
                
                # Create success embed with new key
                success_embed = create_success_embed("✅ API Key Regenerated", 
                    f"Node **{self.node['name']}** (ID: {self.node_id})")
                
                add_field(success_embed, "Old API Key", f"`{self.node['api_key']}`", False)
                add_field(success_embed, "New API Key", f"`{new_api_key}`", False)
                add_field(success_embed, "Node URL", self.node['url'], True)
                
                setup_command = f"python node-agent.py --api_key={new_api_key} --port=PORT"
                add_field(success_embed, "Update Remote Agent", 
                    f"SSH to the remote server and restart with:\n```\n{setup_command}\n```", False)
                
                add_field(success_embed, "⚠️ Important", 
                    "The old API key is now invalid. Update your remote node agent immediately.", False)
                
                await inter.followup.send(embed=success_embed)
                self.stop()
            
            @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
            async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
                if str(inter.user.id) != str(ctx.author.id):
                    await inter.response.send_message(
                        embed=create_error_embed("Access Denied", "Only the command author can cancel."),
                        ephemeral=True
                    )
                    return
                
                await inter.response.edit_message(
                    embed=create_info_embed("Cancelled", "API key regeneration was cancelled."),
                    view=None
                )
                self.stop()
        
        await ctx.send(embed=warning_embed, view=ConfirmRegenKey(node_id, node))
    
    else:
        # Show help for node command
        embed = create_info_embed("Node Management", 
            f"Manage multi-node infrastructure for {BOT_NAME}")

class HelpView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.current_category = "user"
        # Command categories
        self.command_categories = {
            "user": {
                "name": "👤 User Commands",
                "commands": [
                    (f"{PREFIX}ping", "Check bot latency"),
                    (f"{PREFIX}uptime", "Show host uptime"),
                    (f"{PREFIX}myvps", "List your VPS"),
                    (f"{PREFIX}manage [@user]", "Manage your VPS or another user's VPS (Admin only)"),
                    (f"{PREFIX}share-user @user <vps_number>", "Share VPS access"),
                    (f"{PREFIX}share-ruser @user <vps_number>", "Revoke VPS access"),
                    (f"{PREFIX}manage-shared @owner <vps_number>", "Manage shared VPS")
                ]
            },
            "vps": {
                "name": "🖥️ VPS Management",
                "commands": [
                    (f"{PREFIX}myvps", "List your VPS"),
                    (f"{PREFIX}vpsinfo [vps-id]", "Get VPS information by ID"),
                    (f"{PREFIX}vps-stats <vps-id>", "Get VPS resource stats"),
                    (f"{PREFIX}vps-uptime <vps-id>", "Get VPS uptime"),
                    (f"{PREFIX}vps-processes <vps-id>", "List running processes in VPS"),
                    (f"{PREFIX}vps-logs <vps-id> [lines]", "View VPS logs"),
                    (f"{PREFIX}restart-vps <vps-id>", "Restart VPS"),
                    (f"{PREFIX}clone-vps <vps-id> [new_name]", "Clone VPS by ID"),
                    (f"{PREFIX}vps-password <vps-id>", "Get/reset VPS root password"),
                    (f"{PREFIX}vps-network <vps-id>", "Show VPS network configuration"),
                    (f"{PREFIX}status <vps-id>", "Get VPS status (running/stopped)")
                ]
            },
            "ports": {
                "name": "🔌 Port Forwarding",
                "commands": [
                    (f"{PREFIX}ports [add <vps_num> <port> | list | remove <id>]", "Manage port forwards (TCP/UDP)"),
                    (f"{PREFIX}ports-add-user <amount> @user", "Allocate port slots to user (Admin only)"),
                    (f"{PREFIX}ports-remove-user <amount> @user", "Deallocate port slots from user (Admin only)"),
                    (f"{PREFIX}ports-revoke <id>", "Revoke specific port forward (Admin only)")
                ]
            },
            "system": {
                "name": "⚙️ System Commands",
                "commands": [
                    (f"{PREFIX}serverstats", "Server statistics"),
                    (f"{PREFIX}resource-check", "Check and suspend high-usage VPS (Admin only)"),
                    (f"{PREFIX}cpu-monitor <status|enable|disable>", "Resource monitor control (logging only)"),
                    (f"{PREFIX}thresholds", "View resource thresholds"),
                    (f"{PREFIX}set-threshold <cpu> <ram>", "Set resource thresholds (Admin only)"),
                    (f"{PREFIX}set-status <type> <name>", "Set bot status (Admin only)")
                ]
            },
            "nodes": {
                "name": "🌐 Node Management",
                "commands": [
                    (f"{PREFIX}node create", "Create a new node (Admin only)"),
                    (f"{PREFIX}node list", "List all nodes (Admin only)"),
                    (f"{PREFIX}node status <id>", "Check node status (Admin only)"),
                    (f"{PREFIX}node edit <id>", "Edit node details or convert Local↔Dynamic (Admin only)"),
                    (f"{PREFIX}node regen-key <id>", "Regenerate API key for Dynamic node (Admin only)"),
                    (f"{PREFIX}node delete <id>", "Delete a node (Admin only)"),
                    (f"{PREFIX}node migrate <from> <to>", "Migrate VPS between nodes (Admin only)"),
                    (f"{PREFIX}lxc-list [node_id]", "List LXC containers on node (Admin only)")
                ],
                "admin_only": True
            },
            "bot": {
                "name": "🤖 Bot Control",
                "commands": [
                    (f"{PREFIX}ping", "Check bot latency"),
                    (f"{PREFIX}uptime", "Show host uptime"),
                    (f"{PREFIX}help", "Show this help menu"),
                    (f"{PREFIX}set-status <type> <name>", "Set bot status (Admin only)")
                ]
            },
            "admin": {
                "name": "🛡️ Admin Commands",
                "commands": [
                    (f"{PREFIX}lxc-list", "List all LXC containers"),
                    (f"{PREFIX}create <ram_gb> <cpu_cores> <disk_gb> @user [expiry_days]", "Create VPS with OS selection (optional expiry in days)"),
                    (f"{PREFIX}delete-vps @user <vps-id> [reason]", "Delete user's VPS by ID"),
                    (f"{PREFIX}add-resources <vps-id> [ram] [cpu] [disk]", "Add resources to VPS"),
                    (f"{PREFIX}resize-vps <vps-id> [ram] [cpu] [disk]", "Resize VPS resources"),
                    (f"{PREFIX}suspend-vps <vps-id> [reason]", "Suspend VPS by ID"),
                    (f"{PREFIX}unsuspend-vps <vps-id>", "Unsuspend VPS by ID"),
                    (f"{PREFIX}suspension-logs [vps-id]", "View suspension logs"),
                    (f"{PREFIX}whitelist-vps <vps-id> <add|remove>", "Whitelist VPS from auto-suspend"),
                    (f"{PREFIX}userinfo @user", "User information"),
                    (f"{PREFIX}list-all", "List all VPS"),
                    (f"{PREFIX}exec <vps-id> <command>", "Execute command in VPS"),
                    (f"{PREFIX}stop-vps-all", "Stop all VPS on system"),
                    (f"{PREFIX}migrate-vps <vps-id> <pool>", "Migrate VPS to different storage pool"),
                    (f"{PREFIX}vps-network <vps-id> <action> [value]", "Network management and configuration"),
                    (f"{PREFIX}apply-permissions <vps-id>", "Apply Docker-ready permissions to VPS"),
                    (f"{PREFIX}vps-password <vps-id>", "Get/reset VPS password by ID"),
                    (f"{PREFIX}node-check <node_id>", "Check node health and status"),
                    (f"{PREFIX}status <vps-id>", "Get VPS status"),
                    (f"{PREFIX}status-summary", "Get summary of all VPS status"),
                    (f"{PREFIX}repair-ports", "Repair port forwarding configuration"),
                    (f"{PREFIX}resource-check", "Check and suspend high-usage VPS")
                ],
                "admin_only": True
            },
            "expiration": {
                "name": "⏰ VPS Expiration",
                "commands": [
                    (f"{PREFIX}set-expiration <vps-id> <days>", "Set VPS expiration date (Admin only)"),
                    (f"{PREFIX}renew-vps <vps-id> [days]", "Renew VPS expiration (Admin only)"),
                    (f"{PREFIX}vps-expiration [vps-id]", "Check VPS expiration status (Admin only)")
                ],
                "admin_only": True
            },
            "maintenance": {
                "name": "🔧 Maintenance & Monitoring",
                "commands": [
                    (f"{PREFIX}cpu-monitor <status|enable|disable>", "Resource monitor control (logging only)"),
                    (f"{PREFIX}backup-db", "Backup VPS database (Admin only)"),
                    (f"{PREFIX}repair-ports", "Repair port forwarding configuration (Admin only)"),
                    (f"{PREFIX}node-check <node_id>", "Check node health and status (Admin only)"),
                    (f"{PREFIX}resource-check", "Check and suspend high-usage VPS (Admin only)")
                ],
                "admin_only": True
            },
            "main_admin": {
                "name": "👑 Main Admin Commands",
                "commands": [
                    (f"{PREFIX}admin-add @user", "Add admin"),
                    (f"{PREFIX}admin-remove @user", "Remove admin"),
                    (f"{PREFIX}admin-list", "List admins")
                ],
                "admin_only": True,
                "main_admin_only": True
            }
        }
        self.update_select()
        self.update_embed()
        self.add_item(self.select)

    def update_select(self):
        """Update the category selection dropdown based on user permissions"""
        self.select = discord.ui.Select(placeholder="Select Category", options=[])
        user_id = str(self.ctx.author.id)
        is_admin_user = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
        is_main_admin_user = user_id == str(MAIN_ADMIN_ID)
       
        # Add all categories that user has access to
        options = []
        # Always show basic categories
        basic_categories = ["user", "vps", "ports", "system", "bot"]
        for category in basic_categories:
            options.append(discord.SelectOption(
                label=self.command_categories[category]["name"],
                value=category,
                emoji=self.get_category_emoji(category)
            ))
       
        # Add nodes category if admin
        if is_admin_user:
            options.append(discord.SelectOption(
                label=self.command_categories["nodes"]["name"],
                value="nodes",
                emoji=self.get_category_emoji("nodes")
            ))
       
        # Add admin categories if user has permissions
        if is_admin_user:
            options.append(discord.SelectOption(
                label=self.command_categories["admin"]["name"],
                value="admin",
                emoji=self.get_category_emoji("admin")
            ))
            options.append(discord.SelectOption(
                label=self.command_categories["expiration"]["name"],
                value="expiration",
                emoji=self.get_category_emoji("expiration")
            ))
            options.append(discord.SelectOption(
                label=self.command_categories["maintenance"]["name"],
                value="maintenance",
                emoji=self.get_category_emoji("maintenance")
            ))
       
        if is_main_admin_user:
            options.append(discord.SelectOption(
                label=self.command_categories["main_admin"]["name"],
                value="main_admin",
                emoji=self.get_category_emoji("main_admin")
            ))
       
        self.select.options = options
        self.select.callback = self.select_callback
   
    async def select_callback(self, interaction: discord.Interaction):
        """Handle category selection"""
        if interaction.user != self.ctx.author:
            await interaction.response.send_message("This menu is not for you!", ephemeral=True)
            return
        
        self.current_category = interaction.data['values'][0]
        self.update_embed()
        await interaction.response.edit_message(embed=self.embed, view=self)

    def get_category_emoji(self, category):
        """Get emoji for each category"""
        emojis = {
            "user": "👤",
            "vps": "🖥️",
            "ports": "🔌",
            "system": "⚙️",
            "bot": "🤖",
            "nodes": "🌐",
            "admin": "🛡️",
            "expiration": "⏰",
            "maintenance": "🔧",
            "main_admin": "👑"
        }
        return emojis.get(category, "📁")
   
    def update_embed(self):
        """Update the embed based on current category and user permissions"""
        category_data = self.command_categories[self.current_category]
        # Create embed with category-specific styling
        colors = {
            "user": 0x3498db, # Blue
            "vps": 0x2ecc71, # Green
            "ports": 0xe74c3c, # Red
            "system": 0xf39c12, # Orange
            "bot": 0x9b59b6, # Purple
            "nodes": 0x1abc9c, # Teal
            "admin": 0xe67e22, # Carrot
            "expiration": 0xff6b6b, # Coral red for expiration
            "maintenance": 0x34495e, # Dark gray for maintenance
            "main_admin": 0xf1c40f # Yellow
        }
        color = colors.get(self.current_category, 0x1a1a1a)
       
        title = f"📚 {BOT_NAME} Command Help - {category_data['name']}"
        description = f"**{category_data['name']}**\nUse the dropdown below to switch categories."
       
        # Add helpful tips based on category
        tips = {
            "user": f"Tip: Use `{PREFIX}myvps` to see all your VPS and `{PREFIX}manage` to control them.",
            "vps": f"Tip: Use `{PREFIX}manage` to control your VPS from Discord.",
            "ports": "Tip: Port forwards work for both TCP and UDP protocols.",
            "system": "Tip: Set thresholds to monitor resource usage across nodes.",
            "nodes": f"Tip: Use `{PREFIX}node list` to see all available nodes and their status.",
            "admin": f"Tip: Always check `{PREFIX}userinfo @user` before modifying VPS.",
            "expiration": "Tip: VPS are automatically suspended when they expire. Renew them to unsuspend.",
            "maintenance": f"Tip: Use `{PREFIX}backup-db` regularly to backup your VPS database.",
            "main_admin": "Tip: Be careful when adding/removing admin privileges."
        }
       
        if self.current_category in tips:
            description += f"\n\n💡 {tips[self.current_category]}"
       
        self.embed = create_embed(title, description, color)
       
        # Add commands to embed
        commands_text = "\n".join([f"**{cmd}** - {desc}" for cmd, desc in category_data["commands"]])
        add_field(self.embed, "Commands", commands_text, False)
       
        # Add appropriate footer based on category
        footers = {
            "user": f"{BOT_NAME} VPS Manager • User Commands • Need help? Contact admin",
            "vps": f"{BOT_NAME} VPS Manager • VPS Management • Cloning",
            "ports": f"{BOT_NAME} VPS Manager • Port Forwarding • TCP/UDP Support",
            "system": f"{BOT_NAME} VPS Manager • System Monitoring • Resource Management",
            "nodes": f"{BOT_NAME} VPS Manager • Multi-Node Management • Distributed Infrastructure",
            "bot": f"{BOT_NAME} VPS Manager • Bot Control • Status Management",
            "admin": f"{BOT_NAME} VPS Manager • Admin Panel • Restricted Access",
            "expiration": f"{BOT_NAME} VPS Manager • VPS Expiration • Auto-Suspension",
            "maintenance": f"{BOT_NAME} VPS Manager • System Maintenance • Database Backup & Repair",
            "main_admin": f"{BOT_NAME} VPS Manager • Main Admin • Full System Control"
        }
       
        self.embed.set_footer(text=footers.get(self.current_category, f"{BOT_NAME} VPS Manager"))


@bot.command(name='help')
async def show_help(ctx):
    """Display the interactive help menu"""
    view = HelpView(ctx)
    await ctx.send(embed=view.embed, view=view)


# Command aliases for typos and convenience
@bot.command(name='mangage')
async def manage_typo(ctx):
    await ctx.send(embed=create_info_embed("Command Correction", f"Did you mean `{PREFIX}manage`? Use the correct command."))


@bot.command(name='commands')
async def commands_alias(ctx):
    """Alias for help command"""
    await show_help(ctx)


@bot.command(name='stats')
async def stats_alias(ctx):
    if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
        await server_stats(ctx)
    else:
        await ctx.send(embed=create_error_embed("Access Denied", "This command requires admin privileges."))


@bot.command(name='info')
async def info_alias(ctx, user: discord.Member = None):
    if str(ctx.author.id) == str(MAIN_ADMIN_ID) or str(ctx.author.id) in admin_data.get("admins", []):
        if user:
            await user_info(ctx, user)
        else:
            await ctx.send(embed=create_error_embed("Usage", f"Please specify a user: `{PREFIX}info @user`"))
    else:
        await ctx.send(embed=create_error_embed("Access Denied", "This command requires admin privileges."))

# === Svm-v11.2 BOT(4) COMPATIBILITY / UPGRADE LAYER ===
def get_public_ip() -> str:
    """Fetch the server's public IP via ifconfig.me, caching the result.
    Falls back to YOUR_SERVER_IP env var if the lookup fails."""
    global _cached_public_ip
    if _cached_public_ip:
        return _cached_public_ip
    try:
        resp = requests.get("https://ifconfig.me/ip", timeout=5)
        ip = resp.text.strip()
        if ip:
            _cached_public_ip = ip
            return ip
    except Exception as e:
        logger.warning(f"Failed to fetch public IP from ifconfig.me: {e}")
    return YOUR_SERVER_IP

def get_main_admins() -> List[str]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT user_id FROM main_admins')
    rows = cur.fetchall()
    conn.close()
    ids = [row['user_id'] for row in rows]
    return ids if ids else [str(MAIN_ADMIN_ID)]

def save_main_admins():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM main_admins')
    for uid in main_admin_ids:
        cur.execute('INSERT INTO main_admins (user_id) VALUES (?)', (uid,))
    conn.commit()
    conn.close()

async def safe_start_container(container_name: str, node_id: int):
    """Starts a container, treating 'already running' as a success instead of an error."""
    try:
        await execute_lxc(container_name, f"start {container_name}", node_id=node_id)
    except Exception as e:
        err_text = str(e).lower()
        if "already running" in err_text or "is running" in err_text:
            logger.info(f"{container_name} was already running; treating start as success.")
        else:
            raise

def generate_password(length: int = 16) -> str:
    """Generate a random alnum-only password (safe to embed in shell commands)."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

async def setup_ssh_access(container_name: str, node_id: int) -> str:
    """Installs openssh-server, sets a random root password, and enables
    password-based root SSH login inside the container. Returns the password."""
    password = generate_password()
    commands = [
        "DEBIAN_FRONTEND=noninteractive apt-get update -y",
        "DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server",
        f"echo 'root:{password}' | chpasswd",
        "printf 'PermitRootLogin yes\\nPasswordAuthentication yes\\n\\n' | cat - /etc/ssh/sshd_config > /tmp/sshd_config.new && mv /tmp/sshd_config.new /etc/ssh/sshd_config",
        "mkdir -p /run/sshd",
        "systemctl enable ssh 2>/dev/null || systemctl enable sshd 2>/dev/null || true",
        "systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null || service ssh restart 2>/dev/null || service sshd restart 2>/dev/null || true"
    ]
    for cmd in commands:
        try:
            await execute_lxc(container_name, f"exec {container_name} -- bash -c \"{cmd}\"", node_id=node_id, timeout=180)
        except Exception as cmd_error:
            logger.warning(f"SSH setup command failed in {container_name}: {cmd} - {cmd_error}")
    return password

def parse_pinggy_address(log_text: str) -> Optional[str]:
    """Extracts host:port from Pinggy's tcp:// forwarding line, stripping the tcp:// prefix."""
    if not log_text:
        return None
    match = re.search(r'tcp://([\w\.\-]+):(\d+)', log_text, re.IGNORECASE)
    if match:
        return f"{match.group(1)}:{match.group(2)}"
    return None

async def establish_pinggy_tunnel(container_name: str, node_id: int, retries: int = 4, wait_seconds: int = 5) -> Optional[str]:
    """
    Runs 'ssh -p 443 -R0:localhost:22 qr+tcp@free.pinggy.io' inside the container
    (equivalent to: lxc exec <container> -- bash, then running that ssh command and
    accepting the host-key prompt with 'yes' automatically), as a persistent background
    tunnel. Returns the assigned 'host:port' (with the tcp:// prefix stripped), or None
    if the address could not be determined.
    """
    try:
        # Make sure an SSH client exists inside the container
        await execute_lxc(
            container_name,
            f"exec {container_name} -- bash -c \"command -v ssh >/dev/null || (DEBIAN_FRONTEND=noninteractive apt-get update -y && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-client)\"",
            node_id=node_id, timeout=180
        )
    except Exception as e:
        logger.warning(f"Pinggy: couldn't verify/install ssh client in {container_name}: {e}")

    # Kill any previous tunnel and clear the old log
    try:
        await execute_lxc(
            container_name,
            f"exec {container_name} -- bash -c \"pkill -f 'free.pinggy.io' >/dev/null 2>&1; rm -f {PINGGY_LOG_PATH}\"",
            node_id=node_id
        )
    except Exception:
        pass

    # Start the tunnel in the background. -o StrictHostKeyChecking=no auto-accepts the
    # host key prompt (the 'always yes' behavior), so it never blocks waiting for input.
    tunnel_cmd = (
        "setsid nohup ssh -p 443 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        "-o ServerAliveInterval=30 -R0:localhost:22 qr+tcp@free.pinggy.io "
        f"> {PINGGY_LOG_PATH} 2>&1 < /dev/null & disown"
    )
    try:
        await execute_lxc(
            container_name,
            f"exec {container_name} -- bash -c \"{tunnel_cmd}\"",
            node_id=node_id
        )
    except Exception as e:
        logger.error(f"Pinggy: failed to start tunnel in {container_name}: {e}")
        return None

    # Poll the log until the tcp:// address shows up
    for attempt in range(retries):
        await asyncio.sleep(wait_seconds)
        try:
            log_output = await execute_lxc(
                container_name,
                f"exec {container_name} -- cat {PINGGY_LOG_PATH}",
                node_id=node_id
            )
        except Exception:
            log_output = ""
        address = parse_pinggy_address(log_output if isinstance(log_output, str) else "")
        if address:
            return address
    logger.warning(f"Pinggy: no tunnel address found for {container_name} after {retries} attempts")
    return None

async def add_admin_id(ctx, user_id: str):
    """Add a main admin by raw Discord user ID (works even if the user isn't in this server)."""
    if not user_id.isdigit():
        await ctx.send(embed=create_error_embed("Invalid ID", "Please provide a numeric Discord user ID."))
        return
    if user_id in main_admin_ids:
        await ctx.send(embed=create_error_embed("Already Admin", f"`{user_id}` is already a main admin!"))
        return
    main_admin_ids.add(user_id)
    save_main_admins()
    await ctx.send(embed=create_success_embed("Main Admin Added", f"`{user_id}` is now a main admin!"))
    try:
        user = await bot.fetch_user(int(user_id))
        await user.send(embed=create_embed("🎉 Main Admin Access Granted", f"You are now a main admin of {BOT_NAME}, granted by {ctx.author.mention}", 0x00ff88))
    except Exception:
        pass

async def rm_admin_id(ctx, user_id: str):
    """Remove a main admin by raw Discord user ID."""
    if user_id not in main_admin_ids:
        await ctx.send(embed=create_error_embed("Not Admin", f"`{user_id}` is not a main admin!"))
        return
    if len(main_admin_ids) <= 1:
        await ctx.send(embed=create_error_embed("Cannot Remove", "At least one main admin must remain."))
        return
    main_admin_ids.discard(user_id)
    save_main_admins()
    await ctx.send(embed=create_success_embed("Main Admin Removed", f"`{user_id}` is no longer a main admin!"))
    try:
        user = await bot.fetch_user(int(user_id))
        await user.send(embed=create_embed("⚠️ Main Admin Access Revoked", f"Your main admin role was removed by {ctx.author.mention}", 0xff3366))
    except Exception:
        pass

async def snapshot_vps(ctx, container_name: str, snap_name: str = "snap0"):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_info_embed("Creating Snapshot", f"Creating snapshot '{snap_name}' for `{container_name}`..."))
    try:
        await execute_lxc(container_name, f"snapshot {container_name} {snap_name}", node_id=node_id)
        await ctx.send(embed=create_success_embed("Snapshot Created", f"Snapshot '{snap_name}' created for VPS `{container_name}`."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Snapshot Failed", f"Error: {str(e)}"))

async def list_snapshots(ctx, container_name: str):
    node_id = find_node_id_for_container(container_name)
    try:
        result = await execute_lxc(container_name, f"snapshot list {container_name}", node_id=node_id)
        embed = create_info_embed(f"Snapshots for {container_name}", result)
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(embed=create_error_embed("List Failed", f"Error: {str(e)}"))

async def restore_snapshot(ctx, container_name: str, snap_name: str):
    node_id = find_node_id_for_container(container_name)
    await ctx.send(embed=create_warning_embed("Restore Snapshot", f"Restoring snapshot '{snap_name}' for `{container_name}` will overwrite current state. Continue?"))
    class RestoreConfirm(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="Confirm Restore", style=discord.ButtonStyle.danger)
        async def confirm(self, inter: discord.Interaction, item: discord.ui.Button):
            await inter.response.defer()
            try:
                await execute_lxc(container_name, f"stop {container_name}", node_id=node_id)
                await execute_lxc(container_name, f"restore {container_name} {snap_name}", node_id=node_id)
                await safe_start_container(container_name, node_id)
                await apply_internal_permissions(container_name, node_id)
                await recreate_port_forwards(container_name)
                for uid, lst in vps_data.items():
                    for vps in lst:
                        if vps['container_name'] == container_name:
                            vps['status'] = 'running'
                            vps['suspended'] = False
                            save_vps_data()
                            break
                await inter.followup.send(embed=create_success_embed("Snapshot Restored", f"Restored '{snap_name}' for VPS `{container_name}`."))
            except Exception as e:
                await inter.followup.send(embed=create_error_embed("Restore Failed", f"Error: {str(e)}"))

        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel(self, inter: discord.Interaction, item: discord.ui.Button):
            await inter.response.edit_message(embed=create_info_embed("Cancelled", "Snapshot restore cancelled."))

    await ctx.send(view=RestoreConfirm())

# Svm-v11.2 ADVANCED UPGRADE LAYER
# Made by AnkitCoder
# This layer extends the existing Svm-v9 bot without removing its commands.
# ============================================================================

import base64

HOST_MOTD = os.getenv('HOST_MOTD', 'bash <(curl -fsSL https://raw.githubusercontent.com/ankitcoder/linux/main/atyro-water-mark.sh)')
HOST_MOTD_ENABLED = os.getenv('HOST_MOTD_ENABLED', 'false').lower() in ('1','true','yes','on')
import hashlib
import hmac
import io
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SVM_V11_2V_NAME = os.getenv("SVM_V11_2V_NAME", "SVM V11.2")
SVM_V11_2V_DEVELOPER = os.getenv("SVM_V11_2V_DEVELOPER", "AnkitCoder")
SVM_PUBLIC_URL = os.getenv("SVM_PUBLIC_URL", "")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
# UPI display/payment configuration. UPI payments are NOT auto-authorized from screenshots.
UPI_ENABLED = os.getenv("UPI_ENABLED", "false").lower() in ("1", "true", "yes", "on")
UPI_ID = os.getenv("UPI_ID", "")
UPI_NAME = os.getenv("UPI_NAME", "AnkitCoder")
UPI_QR_URL = os.getenv("UPI_QR_URL", "")
PAYMENT_INSTRUCTIONS = os.getenv("PAYMENT_INSTRUCTIONS", "Complete the Razorpay order for automatic verification. UPI details are shown only when configured.")
PAYMENT_WEBHOOK_HOST = os.getenv("PAYMENT_WEBHOOK_HOST", "0.0.0.0")
PAYMENT_WEBHOOK_PORT = int(os.getenv("PAYMENT_WEBHOOK_PORT", "8787"))
PANEL_DOMAIN = os.getenv("PANEL_DOMAIN", "")
PANEL_INSTALL_REPO = os.getenv("SVM_PANEL_REPO", "https://github.com/AnkitKing7/Svm-v4.git")
PANEL_INSTALL_DIR = os.getenv("SVM_PANEL_DIR", "/opt/svm-panel")

# Configurable plans. Prices are intentionally environment-controlled.
DEFAULT_PLANS = {
    "starter": {"name":"Starter", "cpu":1, "ram":2, "disk":20, "price":int(os.getenv("PLAN_STARTER_PRICE","0"))},
    "basic": {"name":"Basic", "cpu":2, "ram":4, "disk":40, "price":int(os.getenv("PLAN_BASIC_PRICE","0"))},
    "standard": {"name":"Standard", "cpu":4, "ram":8, "disk":80, "price":int(os.getenv("PLAN_STANDARD_PRICE","0"))},
    "pro": {"name":"Pro", "cpu":8, "ram":16, "disk":160, "price":int(os.getenv("PLAN_PRO_PRICE","0"))},
}

# ----------------------------- V10 DB ---------------------------------------
def v112v_db():
    return get_db()

def v112v_migrate():
    conn=v112v_db(); c=conn.cursor()
    migrations = [
        ("v112v_version", "1"),
    ]
    c.execute("CREATE TABLE IF NOT EXISTS v112v_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for k,v in migrations:
        c.execute("INSERT OR IGNORE INTO v112v_settings(key,value) VALUES(?,?)",(k,v))
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_plans(
        slug TEXT PRIMARY KEY, name TEXT NOT NULL, cpu INTEGER NOT NULL,
        ram INTEGER NOT NULL, disk INTEGER NOT NULL, price_paise INTEGER NOT NULL,
        active INTEGER DEFAULT 1, created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_orders(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL,
        plan_slug TEXT NOT NULL, amount_paise INTEGER NOT NULL,
        currency TEXT DEFAULT 'INR', provider TEXT DEFAULT 'razorpay',
        provider_order_id TEXT UNIQUE, provider_payment_id TEXT UNIQUE,
        status TEXT DEFAULT 'created', screenshot_status TEXT DEFAULT 'none',
        created_at TEXT NOT NULL, verified_at TEXT, raw_event TEXT DEFAULT ''
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_provision_locks(
        order_id INTEGER PRIMARY KEY, acquired_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_vps_meta(
        vps_db_id INTEGER PRIMARY KEY, vmid INTEGER UNIQUE, ipv4 TEXT DEFAULT '',
        ipv6 TEXT DEFAULT '', ssh_port INTEGER DEFAULT 22, provider TEXT DEFAULT 'lxc',
        panel_status TEXT DEFAULT 'not_installed', panel_port INTEGER DEFAULT 8080,
        panel_username TEXT DEFAULT '', panel_password TEXT DEFAULT '',
        panel_email TEXT DEFAULT '', expiry_at TEXT DEFAULT '',
        install_job TEXT DEFAULT '', updated_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_jobs(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, user_id TEXT, vps_db_id INTEGER,
        status TEXT DEFAULT 'queued', progress INTEGER DEFAULT 0, message TEXT DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_audit(
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id TEXT, action TEXT,
        target TEXT, details TEXT, created_at TEXT NOT NULL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS v112v_payment_proofs(
        id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, user_id TEXT NOT NULL,
        sha256 TEXT NOT NULL, filename TEXT, ocr_text TEXT DEFAULT '', status TEXT DEFAULT 'received',
        created_at TEXT NOT NULL
    )""")
    for slug,p in DEFAULT_PLANS.items():
        c.execute("""INSERT OR IGNORE INTO v112v_plans
          (slug,name,cpu,ram,disk,price_paise,created_at) VALUES(?,?,?,?,?,?,?)""",
          (slug,p['name'],p['cpu'],p['ram'],p['disk'],p['price']*100,datetime.now().isoformat()))
    # Existing vps table receives non-breaking metadata columns.
    c.execute("PRAGMA table_info(vps)")
    cols={row[1] for row in c.fetchall()}
    for name,typ,default in [
        ('plan_slug','TEXT',"'custom'"),('ipv4','TEXT',"''"),('ipv6','TEXT',"''"),
        ('provider','TEXT',"'lxc'"),('vmid','INTEGER','NULL'),('expiry_at','TEXT',"''")]:
        if name not in cols:
            c.execute(f"ALTER TABLE vps ADD COLUMN {name} {typ} DEFAULT {default}")
    conn.commit(); conn.close()

v112v_migrate()

def v112v_audit(actor, action, target='', details=''):
    try:
        conn=v112v_db(); conn.execute("INSERT INTO v112v_audit(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
            (str(actor),action,target,str(details),datetime.now().isoformat())); conn.commit(); conn.close()
    except Exception as e: logger.warning("V10 audit failed: %s",e)

def v112v_next_vmid():
    conn=v112v_db(); c=conn.cursor(); c.execute("SELECT COALESCE(MAX(vmid),99) FROM v112v_vps_meta"); n=int(c.fetchone()[0])+1
    # Proxmox-style guest IDs start at 100; avoid reusing IDs that already exist.
    while True:
        c.execute("SELECT 1 FROM v112v_vps_meta WHERE vmid=?",(n,))
        if not c.fetchone(): break
        n+=1
    conn.close(); return max(100,n)

def v112v_find_vps(query):
    conn=v112v_db(); c=conn.cursor()
    if str(query).isdigit():
        c.execute("SELECT v.*,m.vmid,m.ipv4,m.ipv6,m.provider,m.panel_status,m.panel_port,m.panel_username,m.panel_password,m.panel_email FROM vps v LEFT JOIN v112v_vps_meta m ON m.vps_db_id=v.id WHERE v.id=? OR m.vmid=? OR v.container_name=?",(int(query),int(query),str(query)))
    else:
        c.execute("SELECT v.*,m.vmid,m.ipv4,m.ipv6,m.provider,m.panel_status,m.panel_port,m.panel_username,m.panel_password,m.panel_email FROM vps v LEFT JOIN v112v_vps_meta m ON m.vps_db_id=v.id WHERE v.container_name=?",(str(query),))
    row=c.fetchone(); conn.close(); return dict(row) if row else None

def v112v_get_plan(slug):
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_plans WHERE slug=? AND active=1",(slug.lower(),)).fetchone(); conn.close(); return dict(row) if row else None

# --------------------------- Payment verification ---------------------------
def razorpay_headers():
    token=base64.b64encode(f"{RAZORPAY_KEY_ID}:{RAZORPAY_KEY_SECRET}".encode()).decode()
    return {"Authorization":f"Basic {token}","Content-Type":"application/json"}

def razorpay_verify_payment(payment_id, expected_amount, expected_order_id=None):
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET: return False,"Razorpay credentials are not configured"
    try:
        r=requests.get(f"https://api.razorpay.com/v1/payments/{payment_id}",headers=razorpay_headers(),timeout=15)
        r.raise_for_status(); p=r.json()
        if int(p.get('amount',-1)) != int(expected_amount): return False,"Amount mismatch"
        if expected_order_id and p.get('order_id') != expected_order_id: return False,"Order mismatch"
        if p.get('status') not in ('captured','authorized'): return False,f"Payment status: {p.get('status')}"
        return True,p
    except Exception as e: return False,str(e)

def razorpay_create_order(user_id, plan):
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET: return None,"Razorpay is not configured"
    amount=int(plan['price_paise'])
    if amount<=0: return None,"Plan price is not configured"
    payload={"amount":amount,"currency":"INR","receipt":f"svm-{user_id}-{int(time.time())}","notes":{"user_id":str(user_id),"plan":plan['slug']}}
    try:
        r=requests.post("https://api.razorpay.com/v1/orders",headers=razorpay_headers(),json=payload,timeout=15)
        r.raise_for_status(); return r.json(),None
    except Exception as e: return None,str(e)

def v112v_webhook_signature(raw, signature):
    if not RAZORPAY_WEBHOOK_SECRET or not signature: return False
    expected=hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(),raw,hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected,signature)

def v112v_mark_payment(raw_event):
    event=raw_event.get('event','')
    entity=((raw_event.get('payload') or {}).get('payment') or {}).get('entity') or {}
    if event not in ('payment.captured','payment.authorized'): return
    pid=entity.get('id'); oid=entity.get('order_id'); amount=entity.get('amount')
    if not pid or not oid: return
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_orders WHERE provider_order_id=?",(oid,)).fetchone()
    if not row: conn.close(); return
    order=dict(row)
    if int(order['amount_paise'])!=int(amount or -1): conn.close(); logger.warning('Payment amount mismatch for %s',oid); return
    conn.execute("UPDATE v112v_orders SET status='paid',provider_payment_id=?,verified_at=?,raw_event=? WHERE id=? AND status!='paid'",
                 (pid,datetime.now().isoformat(),json.dumps(raw_event),order['id']))
    conn.commit(); conn.close()
    v112v_audit(order['user_id'],'payment_verified',str(order['id']),f'provider_payment_id={pid}')
    # Provisioning is scheduled only after authoritative provider verification.
    # The webhook thread never provisions directly; it hands the coroutine to Discord's event loop.
    try:
        loop = bot.loop
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(v112v_auto_provision_order(order['id']), loop)
        else:
            threading.Thread(target=lambda: v112v_provision_order(order['id']), daemon=True).start()
    except Exception:
        logger.exception("Could not schedule automatic provisioning for order %s", order['id'])
        v112v_provision_order(order['id'])

async def v112v_auto_provision_order(order_id):
    """Fully automatic LXC provisioning after a verified Razorpay event."""
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_orders WHERE id=?",(order_id,)).fetchone(); conn.close()
    if not row or row['status']!='paid': return
    # Idempotency/locking: exactly one provisioning coroutine may own this paid order.
    conn=v112v_db(); now=datetime.now().isoformat()
    try:
        conn.execute("INSERT INTO v112v_provision_locks(order_id,acquired_at) VALUES(?,?)", (order_id, now)); conn.commit()
    except sqlite3.IntegrityError:
        conn.close(); logger.info('Provisioning already running for order %s', order_id); return
    conn.close()
    plan=v112v_get_plan(row['plan_slug'])
    if not plan:
        conn=v112v_db(); conn.execute("DELETE FROM v112v_provision_locks WHERE order_id=?",(order_id,)); conn.commit(); conn.close(); return
    try:
        user=await bot.fetch_user(int(row['user_id']))
        nodes=get_nodes(); node=None
        for n in nodes:
            if get_current_vps_count(n['id']) < int(n['total_vps'] or 0):
                node=n; break
        if not node: raise RuntimeError('No node has available VPS capacity')
        user_id=str(user.id); vps_count=len(vps_data.get(user_id,[]))+1
        container_name=f"{BOT_NAME.lower()}-vps-{user_id}-{vps_count}"
        os_version=os.getenv('DEFAULT_V11_2V_OS','ubuntu:22.04')
        ram=int(plan['ram']); cpu=int(plan['cpu']); disk=int(plan['disk']); node_id=int(node['id'])
        job_id=secrets.token_hex(12); now=datetime.now().isoformat()
        conn=v112v_db(); conn.execute("INSERT OR REPLACE INTO v112v_jobs(id,kind,user_id,status,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(job_id,'payment_provision',user_id,'running',10,'Creating VPS',now,now)); conn.commit(); conn.close()
        steps=[
          (20, lambda: execute_lxc(container_name,f"init {os_version} {container_name} -s {DEFAULT_STORAGE_POOL}",node_id=node_id)),
          (30, lambda: execute_lxc(container_name,f"config set {container_name} limits.memory {ram*1024}MB",node_id=node_id)),
          (35, lambda: execute_lxc(container_name,f"config set {container_name} limits.cpu {cpu}",node_id=node_id)),
          (40, lambda: execute_lxc(container_name,f"config device set {container_name} root size={disk}GB",node_id=node_id)),
          (50, lambda: apply_lxc_config(container_name,node_id)),
          (60, lambda: safe_start_container(container_name,node_id)),
          (70, lambda: apply_internal_permissions(container_name,node_id)),
        ]
        for pct,fn in steps:
            await fn(); conn=v112v_db(); conn.execute("UPDATE v112v_jobs SET progress=?,message=?,updated_at=? WHERE id=?",(pct,'Provisioning VPS',datetime.now().isoformat(),job_id)); conn.commit(); conn.close()
        root_password=await setup_ssh_access(container_name,node_id)
        pinggy_address=await establish_pinggy_tunnel(container_name,node_id)
        config_str=f"{ram}GB RAM / {cpu} CPU / {disk}GB Disk"
        vps_info={"container_name":container_name,"node_id":node_id,"ram":f"{ram}GB","cpu":str(cpu),"storage":f"{disk}GB","config":config_str,"os_version":os_version,"status":"running","suspended":False,"whitelisted":False,"suspension_history":[],"created_at":datetime.now().isoformat(),"shared_with":[],"root_password":root_password,"pinggy_address":pinggy_address,"id":None,"plan_slug":plan['slug'],"provider":"lxc","ipv4":"","ipv6":""}
        vps_data.setdefault(user_id,[]).append(vps_info); save_vps_data()
        conn=v112v_db(); vrow=conn.execute("SELECT id FROM vps WHERE container_name=?",(container_name,)).fetchone(); dbid=int(vrow['id']) if vrow else None; vmid=v112v_next_vmid()
        if dbid:
            conn.execute("UPDATE vps SET vmid=?,plan_slug=?,provider=? WHERE id=?",(vmid,plan['slug'],'lxc',dbid))
            conn.execute("INSERT OR REPLACE INTO v112v_vps_meta(vps_db_id,vmid,provider,updated_at) VALUES(?,?,?,?)",(dbid,vmid,'lxc',datetime.now().isoformat()))
        conn.execute("UPDATE v112v_jobs SET status='completed',progress=100,message=?,updated_at=? WHERE id=?",(f'VPS {vmid} created',datetime.now().isoformat(),job_id)); conn.commit(); conn.close()
        v112v_audit(user_id,'vps_auto_provisioned',str(vmid),f'order={order_id};plan={plan["slug"]}')
        embed=create_success_embed('🎉 VPS Automatically Created',f"Your verified payment for **{plan['name']}** has been processed and your VPS is ready.")
        add_field(embed,'🖥️ VPS ID',f'`{vmid}`',True); add_field(embed,'⚙️ Resources',f'{ram}GB RAM • {cpu} vCPU • {disk}GB Disk',True); add_field(embed,'🌐 Node',node['name'],True)
        if pinggy_address:
            host,port=pinggy_address.split(':',1); add_field(embed,'🔑 SSH',f'Host: `{host}`\nPort: `{port}`\nUser: `root`\nPassword: `{root_password}`\n```ssh root@{host} -p {port}```',False)
        await user.send(embed=embed)
        conn=v112v_db(); conn.execute("DELETE FROM v112v_provision_locks WHERE order_id=?",(order_id,)); conn.commit(); conn.close()
    except Exception as e:
        logger.exception('Automatic provisioning failed for order %s',order_id)
        conn=v112v_db(); conn.execute("UPDATE v112v_orders SET status='paid' WHERE id=?",(order_id,)); conn.execute("UPDATE v112v_jobs SET status='failed',message=?,updated_at=? WHERE kind='payment_provision' AND user_id=? AND status='running'",(str(e)[:500],datetime.now().isoformat(),str(row['user_id']))); conn.commit(); conn.close()
        try: await user.send(embed=create_error_embed('⚠️ VPS Provisioning Delayed',f'Payment was verified, but VPS provisioning failed. The payment remains recorded and an admin can retry the job.\n`{str(e)[:700]}`'))
        except Exception: pass
        conn=v112v_db(); conn.execute("DELETE FROM v112v_provision_locks WHERE order_id=?",(order_id,)); conn.commit(); conn.close()

def v112v_provision_order(order_id):
    """Fallback worker entrypoint. Never trusts a screenshot as payment authority."""
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_orders WHERE id=?",(order_id,)).fetchone(); conn.close()
    if not row or row['status']!='paid': return
    job=secrets.token_hex(12); now=datetime.now().isoformat()
    conn=v112v_db(); conn.execute("INSERT INTO v112v_jobs(id,kind,user_id,status,progress,message,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (job,'payment_provision',row['user_id'],'queued',5,'Payment verified; waiting for Discord worker',now,now)); conn.commit(); conn.close()
    logger.info('V10 provisioning job %s queued for user %s',job,row['user_id'])

async def v112v_retry_failed_job(order_id):
    """Admin/manual retry entrypoint; rechecks authoritative payment state before provisioning."""
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_orders WHERE id=?",(order_id,)).fetchone(); conn.close()
    if not row: raise RuntimeError('Order not found')
    ok, detail = razorpay_verify_payment(row['provider_payment_id'], row['amount_paise'], row['provider_order_id']) if row['provider_payment_id'] else (False,'No payment ID')
    if not ok: raise RuntimeError(f'Gateway verification failed: {detail}')
    await v112v_auto_provision_order(order_id)

class V10WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if urlparse(self.path).path!='/razorpay/webhook': self.send_response(404); self.end_headers(); return
        length=int(self.headers.get('Content-Length','0')); raw=self.rfile.read(length)
        if not v112v_webhook_signature(raw,self.headers.get('X-Razorpay-Signature','')):
            self.send_response(401); self.end_headers(); self.wfile.write(b'bad signature'); return
        try:
            event=json.loads(raw.decode()); v112v_mark_payment(event)
            self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        except Exception as e:
            logger.exception('Webhook processing failed')
            self.send_response(500); self.end_headers(); self.wfile.write(str(e).encode()[:200])
    def log_message(self,*args): logger.info('Razorpay webhook: %s',args[0] if args else '')

def start_v112v_webhook_server():
    if not RAZORPAY_WEBHOOK_SECRET: logger.warning('V10 webhook server disabled: RAZORPAY_WEBHOOK_SECRET missing'); return
    try:
        srv=ThreadingHTTPServer((PAYMENT_WEBHOOK_HOST,PAYMENT_WEBHOOK_PORT),V10WebhookHandler)
        threading.Thread(target=srv.serve_forever,daemon=True,name='svm-v11-2v-webhook').start()
        logger.info('Svm-v11.2 Razorpay webhook listening on %s:%s',PAYMENT_WEBHOOK_HOST,PAYMENT_WEBHOOK_PORT)
    except Exception as e: logger.error('Could not start V10 webhook server: %s',e)

# ------------------------------ SVG/PNG stats --------------------------------
def v112v_bar(label,pct,width=360):
    pct=max(0,min(100,float(pct))); filled=int(width*pct/100)
    return f'<text x="20" y="0" font-size="16">{label}: {pct:.1f}%</text><rect x="20" y="12" width="{width}" height="18" rx="9" fill="#222"/><rect x="20" y="12" width="{filled}" height="18" rx="9" fill="#39d98a"/>'

def v112v_svg(vps,stats):
    vmid=vps.get('vmid') or vps.get('id'); cpu=float(stats.get('cpu',0) or 0); ram=stats.get('ram') or {}; rp=float(ram.get('pct',0) or 0)
    svg=f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="560" viewBox="0 0 900 560"><rect width="100%" height="100%" fill="#0b0d10"/><text x="40" y="55" fill="#fff" font-size="30" font-family="Arial">Svm-v11.2 • VPS {vmid}</text><text x="40" y="88" fill="#aaa" font-size="16">Made by AnkitCoder • {datetime.now().isoformat(timespec='seconds')}</text><g transform="translate(40 130)" fill="#fff" font-family="Arial">{v112v_bar('CPU',cpu)}<g transform="translate(0 80)">{v112v_bar('RAM',rp)}</g><g transform="translate(0 160)"><text x="20" y="0" font-size="16">Status: {str(stats.get('status','unknown')).upper()}</text><text x="20" y="42" font-size="16">Disk: {str(stats.get('disk','Unknown'))}</text><text x="20" y="82" font-size="16">Uptime: {str(stats.get('uptime','Unknown'))[:90]}</text></g><g transform="translate(500 0)"><text x="0" y="0" font-size="18">Network / Identity</text><text x="0" y="42" font-size="16">IPv4: {vps.get('ipv4') or 'Not assigned'}</text><text x="0" y="78" font-size="16">IPv6: {vps.get('ipv6') or 'Not assigned'}</text><text x="0" y="114" font-size="16">Provider: {vps.get('provider') or 'lxc'}</text><text x="0" y="150" font-size="16">Node: {vps.get('node_id','-')}</text><text x="0" y="186" font-size="16">SSH: {vps.get('ssh_port',22)}</text></g></g></svg>"""
    return svg

# --------------------------- Panel installers -------------------------------
def v112v_shell(s): return shlex.quote(str(s))

async def v112v_install_pufferpanel(vps, email=None):
    container=vps['container_name']; node_id=vps.get('node_id',1); username='svm-'+secrets.token_hex(4); password=generate_password(20); mail=email or f"{username}@svm.local"
    commands=[
      "apt-get update -y",
      "DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates tar",
      "curl -fsSL https://raw.githubusercontent.com/PufferPanel/PufferPanel/master/get.sh | bash",
      "systemctl enable pufferpanel 2>/dev/null || true",
      "systemctl restart pufferpanel 2>/dev/null || true",
    ]
    for cmd in commands:
        await execute_lxc(container,f"exec {container} -- bash -lc {v112v_shell(cmd)}",node_id=node_id,timeout=300)
    # PufferPanel CLI varies between releases; persist generated credentials for the job/UI
    # and expose the standard web port 8080. Account creation is attempted only when CLI exists.
    try:
        await execute_lxc(container,f"exec {container} -- bash -lc {v112v_shell('pufferpanel user add --email '+mail+' --name '+username+' --password '+password+' --admin 2>/dev/null || true')}",node_id=node_id,timeout=120)
    except Exception: pass
    host_port=8080
    try:
        existing=await execute_lxc(container,f"config device show {container}",node_id=node_id)
        if 'pufferpanel8080' not in str(existing):
            await execute_lxc(container,f"config device add {container} pufferpanel8080 proxy listen=tcp:0.0.0.0:{host_port} connect=tcp:127.0.0.1:8080",node_id=node_id)
    except Exception as e: logger.warning('PufferPanel port mapping: %s',e)
    conn=v112v_db(); conn.execute("INSERT OR REPLACE INTO v112v_vps_meta(vps_db_id,vmid,ipv4,ipv6,ssh_port,provider,panel_status,panel_port,panel_username,panel_password,panel_email,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
      (vps['id'],vps.get('vmid'),vps.get('ipv4',''),vps.get('ipv6',''),22,vps.get('provider','lxc'),'installed',8080,username,password,mail,datetime.now().isoformat())); conn.commit(); conn.close()
    return username,password,mail,8080

async def v112v_install_svm_panel(vps):
    container=vps['container_name']; node_id=vps.get('node_id',1)
    commands=[
      "DEBIAN_FRONTEND=noninteractive apt-get update -y",
      "DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 python3-pip python3-venv",
      f"rm -rf {v112v_shell(PANEL_INSTALL_DIR)}",
      f"git clone --depth 1 {v112v_shell(PANEL_INSTALL_REPO)} {v112v_shell(PANEL_INSTALL_DIR)}",
    ]
    for cmd in commands:
        await execute_lxc(container,f"exec {container} -- bash -lc {v112v_shell(cmd)}",node_id=node_id,timeout=300)
    # Use repo install.sh only when present; otherwise leave the source ready for its documented launcher.
    try:
        await execute_lxc(container,f"exec {container} -- bash -lc {v112v_shell(f'cd {PANEL_INSTALL_DIR} && if [ -f install.sh ]; then chmod +x install.sh && ./install.sh; fi')}",node_id=node_id,timeout=600)
    except Exception as e: logger.warning('SVM panel installer returned an error: %s',e)
    conn=v112v_db(); conn.execute("UPDATE v112v_vps_meta SET panel_status='svm-panel-source-ready',updated_at=? WHERE vps_db_id=?",(datetime.now().isoformat(),vps['id'])); conn.commit(); conn.close()

# ----------------------------- KVM health ------------------------------------
def v112v_kvm_health():
    checks={}
    checks['kvm_device']=os.path.exists('/dev/kvm')
    checks['qemu']=shutil.which('qemu-system-x86_64') is not None
    checks['libvirt']=shutil.which('virsh') is not None
    checks['qemu_img']=shutil.which('qemu-img') is not None
    return checks

async def v112v_kvm_install_host():
    """Admin-only host installer. Explicitly reports failures instead of pretending KVM is ready."""
    if os.geteuid()!=0: raise RuntimeError('KVM installation requires root')
    cmds=['apt-get update -y','DEBIAN_FRONTEND=noninteractive apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients qemu-utils bridge-utils','systemctl enable --now libvirtd 2>/dev/null || systemctl enable --now libvirt 2>/dev/null || true']
    for cmd in cmds: subprocess.run(['bash','-lc',cmd],check=False,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=300)
    return v112v_kvm_health()

# --------------------------- User-facing commands ---------------------------
@bot.command(name='plans')
async def v112v_plans(ctx):
    conn=v112v_db(); rows=conn.execute("SELECT * FROM v112v_plans WHERE active=1 ORDER BY price_paise").fetchall(); conn.close()
    embed=create_info_embed('🛒 Svm-v11.2 VPS Plans','Choose a plan with the configured payment flow.')
    for r in rows:
        p=dict(r); add_field(embed,f"🖥️ {p['name']}",f"⚙️ CPU: **{p['cpu']} vCPU**\n🧠 RAM: **{p['ram']} GB**\n💾 Disk: **{p['disk']} GB**\n💰 Price: **₹{p['price_paise']/100:.2f}**\nBuy: `{PREFIX}buy {p['slug']}`",True)
    add_field(embed,'🔐 Verification','Payment is confirmed from the gateway backend/webhook before provisioning. A screenshot can be attached for reference, but it is not payment authority.',False)
    if UPI_ENABLED and UPI_ID:
        upi_text=f'UPI ID: **{UPI_ID}**\nName: **{UPI_NAME}**'
        if UPI_QR_URL: upi_text += f'\nQR: {UPI_QR_URL}'
        add_field(embed,'📱 UPI Payment Details',upi_text,False)
    await ctx.send(embed=embed)

@bot.command(name='buy')
async def v112v_buy(ctx, plan_slug: str):
    plan=v112v_get_plan(plan_slug)
    if not plan: await ctx.send(embed=create_error_embed('Plan Not Found',f'Use `{PREFIX}plans` to see available plans.')); return
    order,err=razorpay_create_order(str(ctx.author.id),plan)
    if err: await ctx.send(embed=create_error_embed('Payment Setup Error',err)); return
    conn=v112v_db(); cur=conn.cursor(); cur.execute("INSERT INTO v112v_orders(user_id,plan_slug,amount_paise,provider_order_id,created_at) VALUES(?,?,?,?,?)",(str(ctx.author.id),plan['slug'],plan['price_paise'],order['id'],datetime.now().isoformat())); conn.commit(); conn.close()
    payment_text=f"Plan: **{plan['name']}**\nAmount: **₹{plan['price_paise']/100:.2f}**\nOrder ID: `{order['id']}`\n\n{PAYMENT_INSTRUCTIONS}\n\nComplete the Razorpay order to enable automatic verification and VPS provisioning."
    embed=create_warning_embed('💳 SVM V11.2 Payment Order',payment_text)
    if UPI_ENABLED and UPI_ID:
        upi_text=f'UPI ID: **{UPI_ID}**\nName: **{UPI_NAME}**'
        if UPI_QR_URL: upi_text += f'\nQR: {UPI_QR_URL}'
        add_field(embed,'📱 UPI Details',upi_text,False)
        add_field(embed,'⚠️ UPI Verification','UPI screenshot/proof is stored for reference only. It does not automatically mark an order paid.',False)
    add_field(embed,'🔐 Security','Never send API secrets or card/UPI credentials to Discord. Keep Razorpay secrets in environment variables.',False)
    await ctx.author.send(embed=embed)
    await ctx.send(embed=create_success_embed('📩 Payment Details Sent','Check your DMs for the order information.'),delete_after=20)
    v112v_audit(ctx.author.id,'order_created',str(order['id']),plan['slug'])

@bot.command(name='payment-proof')
async def v112v_payment_proof(ctx, order_id: int):
    """Store a payment screenshot for reconciliation; never treats OCR as payment authority."""
    if not ctx.message.attachments:
        await ctx.send(embed=create_error_embed('Attachment Required','Attach the payment screenshot to the same message.'))
        return
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_orders WHERE id=? AND user_id=?",(order_id,str(ctx.author.id))).fetchone(); conn.close()
    if not row:
        await ctx.send(embed=create_error_embed('Order Not Found','That order does not belong to you.')); return
    att=ctx.message.attachments[0]
    if not (att.content_type or '').startswith('image/'):
        await ctx.send(embed=create_error_embed('Invalid File','Please attach an image screenshot.')); return
    try:
        data=await att.read(); digest=hashlib.sha256(data).hexdigest(); ocr=''
        try:
            import pytesseract
            from PIL import Image
            ocr=pytesseract.image_to_string(Image.open(io.BytesIO(data)))[:5000]
        except Exception:
            ocr='OCR unavailable; proof stored for manual/reference reconciliation.'
        proof_dir='/opt/svm-v11-2v/payment-proofs'; os.makedirs(proof_dir,exist_ok=True)
        path=os.path.join(proof_dir,f'{order_id}-{digest[:16]}.bin'); open(path,'wb').write(data)
        conn=v112v_db(); conn.execute("INSERT INTO v112v_payment_proofs(order_id,user_id,sha256,filename,ocr_text,status,created_at) VALUES(?,?,?,?,?,?,?)",(order_id,str(ctx.author.id),digest,att.filename,ocr,'received',datetime.now().isoformat())); conn.commit(); conn.close()
        await ctx.send(embed=create_success_embed('📎 Payment Proof Received','The screenshot was stored and scanned for reference. **It does not override gateway verification.**'))
        v112v_audit(ctx.author.id,'payment_proof_received',str(order_id),digest)
    except Exception as e:
        await ctx.send(embed=create_error_embed('Proof Upload Failed',str(e)))

@bot.command(name='v11-2v-order')
async def v112v_order(ctx, order_id: int):
    conn=v112v_db(); row=conn.execute("SELECT * FROM v112v_orders WHERE id=? AND user_id=?",(order_id,str(ctx.author.id))).fetchone(); conn.close()
    if not row: await ctx.send(embed=create_error_embed('Order Not Found','Order not found.')); return
    r=dict(row); await ctx.send(embed=create_info_embed('🧾 Order Status',f"Order: `{r['id']}`\nPlan: **{r['plan_slug']}**\nAmount: **₹{r['amount_paise']/100:.2f}**\nStatus: **{r['status']}**\nPayment ID: `{r['provider_payment_id'] or 'Pending'}`"))

@bot.command(name='vpsstats-legacy')
async def v112v_vpsstats(ctx, query: str = None):
    if not query:
        await ctx.send(embed=create_error_embed('Usage',f'Use `{PREFIX}vpsstats <VPS ID/name>`')); return
    v=v112v_find_vps(query)
    if not v: await ctx.send(embed=create_error_embed('VPS Not Found','No VPS matched that ID/name.')); return
    if str(v['user_id'])!=str(ctx.author.id) and str(ctx.author.id) not in main_admin_ids and str(ctx.author.id) not in admin_data.get('admins',[]):
        await ctx.send(embed=create_error_embed('Access Denied','You can only view your own VPS stats.')); return
    stats=await get_container_stats(v['container_name'],v.get('node_id',1)); svg=v112v_svg(v,stats); out=io.BytesIO(svg.encode()); out.seek(0)
    file=discord.File(out,filename=f"svm-v11-2v-{v.get('vmid') or v['id']}.svg")
    embed=create_info_embed(f"📊 VPS {v.get('vmid') or v['id']} Live Stats",f"🖥️ **{v['container_name']}**\nCPU: `{float(stats.get('cpu',0)):.1f}%`\nRAM: `{(stats.get('ram') or {}).get('pct',0):.1f}%`\nDisk: `{stats.get('disk','Unknown')}`\nStatus: `{stats.get('status','unknown')}`\n\n**Svm-v11.2 • Made by AnkitCoder**")
    await ctx.send(embed=embed,file=file)

@bot.command(name='v10info')
async def v112v_info(ctx, query: str = None):
    if not query: await ctx.send(embed=create_error_embed('Usage',f'Use `{PREFIX}v10info <VPS ID/name>`')); return
    v=v112v_find_vps(query)
    if not v: await ctx.send(embed=create_error_embed('Not Found','VPS not found.')); return
    if str(v['user_id'])!=str(ctx.author.id) and str(ctx.author.id) not in main_admin_ids and str(ctx.author.id) not in admin_data.get('admins',[]): return
    embed=create_info_embed(f"🖥️ Svm-v11.2 VPS • {v.get('vmid') or v['id']}",f"**Svm-v11.2 Bot • Made by {SVM_V11_2V_DEVELOPER}**")
    for name,val in [('Status',v.get('status')),('Provider',v.get('provider') or 'lxc'),('Node',v.get('node_id')),('CPU',v.get('cpu')),('RAM',v.get('ram')),('Disk',v.get('storage')),('IPv4',v.get('ipv4') or 'Not assigned'),('IPv6',v.get('ipv6') or 'Not assigned'),('SSH Port',v.get('ssh_port') or 22),('PufferPanel',f"{v.get('panel_status','not_installed')} : {v.get('panel_port',8080)}")]: add_field(embed,name,str(val),True)
    await ctx.send(embed=embed)

@bot.command(name='panel-install')
async def v112v_panel_install(ctx, query: str, panel: str='pufferpanel'):
    v=v112v_find_vps(query)
    if not v: await ctx.send(embed=create_error_embed('VPS Not Found','No VPS matched that ID/name.')); return
    allowed=str(v['user_id'])==str(ctx.author.id) or str(ctx.author.id) in main_admin_ids or str(ctx.author.id) in admin_data.get('admins',[])
    if not allowed: await ctx.send(embed=create_error_embed('Access Denied','You do not own this VPS.')); return
    await ctx.send(embed=create_info_embed('⚙️ Panel Installation Started',f"VPS `{v['container_name']}`\nPanel: `{panel}`\nThis runs as a background Discord task."))
    async def job():
        try:
            if panel.lower() in ('puffer','pufferpanel','puffer-panel'):
                u,p,e,port=await v112v_install_pufferpanel(v)
                await ctx.send(embed=create_success_embed('✅ PufferPanel Installed',f"VPS: `{v.get('vmid') or v['id']}`\nPort: **{port}**\nUsername: `{u}`\nEmail: `{e}`\nPassword: `{p}`\n\nUse HTTPS/reverse proxy before public production use."))
            elif panel.lower() in ('svm','svm-panel','vm-panel'):
                await v112v_install_svm_panel(v)
                await ctx.send(embed=create_success_embed('✅ SVM Panel Source Installed',f"Source cloned from configured repository into `{PANEL_INSTALL_DIR}`. Follow that repository's launcher/configuration for the web service."))
            else: await ctx.send(embed=create_error_embed('Unknown Panel','Supported: `pufferpanel`, `svm-panel`'))
        except Exception as e: logger.exception('Panel install failed'); await ctx.send(embed=create_error_embed('Panel Install Failed',str(e)[:1500]))
    asyncio.create_task(job())

@bot.command(name='kvm-status')
@is_admin()
async def v112v_kvm_status(ctx):
    c=v112v_kvm_health(); await ctx.send(embed=create_info_embed('🧩 KVM Health', '\n'.join(f"{'🟢' if v else '🔴'} **{k}**: `{v}`" for k,v in c.items())))

@bot.command(name='kvm-install')
@is_main_admin()
async def v112v_kvm_install(ctx):
    await ctx.send(embed=create_info_embed('⚙️ KVM Setup','Installing/checking QEMU-KVM + libvirt on the bot host...'))
    try:
        c=await v112v_kvm_install_host(); await ctx.send(embed=create_success_embed('KVM Setup Finished','\n'.join(f"{'🟢' if v else '🔴'} {k}: `{v}`" for k,v in c.items())))
    except Exception as e: await ctx.send(embed=create_error_embed('KVM Setup Failed',str(e)))

@bot.command(name='v11-2v-retry-payment')
@is_admin()
async def v112v_retry_payment(ctx, order_id: int):
    await ctx.send(embed=create_info_embed('🔄 Rechecking Payment', f'Authoritative gateway verification for order `{order_id}`...'))
    try:
        await v112v_retry_failed_job(order_id)
        await ctx.send(embed=create_success_embed('✅ Retry Submitted', 'Gateway payment was revalidated and provisioning was attempted. Check the job/audit log for the final result.'))
    except Exception as e:
        await ctx.send(embed=create_error_embed('❌ Retry Failed', str(e)[:1500]))

@bot.command(name='v11-2v-jobs')
@is_admin()
async def v112v_jobs(ctx):
    conn=v112v_db(); rows=conn.execute("SELECT * FROM v112v_jobs ORDER BY created_at DESC LIMIT 15").fetchall(); conn.close()
    if not rows: await ctx.send(embed=create_info_embed('V10 Jobs','No jobs yet.')); return
    text='\n'.join(f"`{r['id'][:10]}` • **{r['kind']}** • `{r['status']}` • {r['progress']}% • {r['message'][:70]}" for r in rows)
    await ctx.send(embed=create_info_embed('⚙️ Svm-v11.2 Jobs',text))

@bot.command(name='v11-2v-audit')
@is_admin()
async def v112v_audit_cmd(ctx, limit: int=20):
    limit=max(1,min(50,limit)); conn=v112v_db(); rows=conn.execute("SELECT * FROM v112v_audit ORDER BY id DESC LIMIT ?",(limit,)).fetchall(); conn.close()
    text='\n'.join(f"`{r['created_at'][:19]}` • `{r['actor_id']}` • **{r['action']}** • `{r['target']}`" for r in rows) or 'No audit events.'
    await ctx.send(embed=create_info_embed('🛡️ V10 Audit Log',text))

# Assign VMIDs to existing VPS records without changing their original DB primary keys.
def v112v_backfill_vmids():
    conn=v112v_db(); rows=conn.execute("SELECT id,node_id,container_name,ipv4,ipv6,provider FROM vps WHERE id NOT IN (SELECT vps_db_id FROM v112v_vps_meta)").fetchall()
    for r in rows:
        vmid=v112v_next_vmid(); conn.execute("INSERT INTO v112v_vps_meta(vps_db_id,vmid,ipv4,ipv6,provider,updated_at) VALUES(?,?,?,?,?,?)",(r['id'],vmid,r['ipv4'] or '',r['ipv6'] or '',r['provider'] or 'lxc',datetime.now().isoformat()))
        conn.execute("UPDATE vps SET vmid=? WHERE id=?",(vmid,r['id']))
    conn.commit(); conn.close()
v112v_backfill_vmids()
logger.info('%s upgrade layer loaded • Made by %s',SVM_V11_2V_NAME,SVM_V11_2V_DEVELOPER)


# ============================================================================
# SVM+ V11.3 ADVANCED LAYER
# IP POOL (IPAM v2) • PORT FORWARDING v2 • MULTI-GATEWAY PAYMENTS • RENEWALS
# Made by AnkitCoder
#
# This layer is loaded BEFORE bot.run() (the old layer sat after bot.run and
# therefore never executed). Functions redefined here intentionally replace the
# older versions because Python resolves module globals at call time.
# ============================================================================
import ipaddress
import itertools
from urllib.parse import quote
from discord.ext import tasks as _svmp_tasks

PINGGY_LOG_PATH = os.getenv("PINGGY_LOG_PATH", "/tmp/pinggy.log")   # was undefined in the old code (NameError during provisioning)

SVMP_VERSION = "11.3-PLUS"
SVMP_LOOP = None            # set in on_ready, used by webhook threads
_SVMP_STARTED = False


def _svmp_env_int(name, default, lo=None, hi=None):
    try:
        value = int(str(os.getenv(name, default)).strip())
    except Exception:
        value = int(default)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def _svmp_env_float(name, default):
    try:
        return float(str(os.getenv(name, default)).strip())
    except Exception:
        return float(default)


def _svmp_env_bool(name, default=False):
    return str(os.getenv(name, str(default))).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------- configuration ---------------------------------
SVMP_GATEWAYS_RAW = os.getenv("PAYMENT_GATEWAYS", "razorpay,upi")
SVMP_DEFAULT_GATEWAY = os.getenv("DEFAULT_GATEWAY", "").strip().lower()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_CURRENCY = os.getenv("STRIPE_CURRENCY", "inr").strip().lower()
STRIPE_AMOUNT_RATE = _svmp_env_float("STRIPE_AMOUNT_RATE", 1.0)   # INR paise -> Stripe minor units
PAYMENT_SUCCESS_URL = os.getenv("PAYMENT_SUCCESS_URL", "") or SVM_PUBLIC_URL or "https://discord.com/app"
PAYMENT_CANCEL_URL = os.getenv("PAYMENT_CANCEL_URL", "") or PAYMENT_SUCCESS_URL
SVMP_ORDER_TTL_MIN = _svmp_env_int("ORDER_TTL_MINUTES", 60, lo=35, hi=1440)
SVMP_UPI_TTL_MIN = _svmp_env_int("UPI_ORDER_TTL_MINUTES", 1440, lo=30, hi=10080)
SVMP_MAX_PENDING_ORDERS = _svmp_env_int("MAX_PENDING_ORDERS", 3, lo=1, hi=20)
SVMP_RENEW_DAYS = _svmp_env_int("RENEW_DAYS", 30, lo=1, hi=365)
SVMP_ACCEPT_AUTHORIZED = _svmp_env_bool("RAZORPAY_ACCEPT_AUTHORIZED", False)
SVMP_ADMIN_CHANNEL_ID = _svmp_env_int("PAYMENT_ADMIN_CHANNEL_ID", 0, lo=0)

_p_lo = _svmp_env_int("PORT_RANGE_START", 20000, lo=1024, hi=65534)
_p_hi = _svmp_env_int("PORT_RANGE_END", 50000, lo=1025, hi=65535)
SVMP_PORT_LO, SVMP_PORT_HI = (_p_lo, _p_hi) if _p_lo < _p_hi else (20000, 50000)
SVMP_PORT_MAX_PER_VPS = _svmp_env_int("PORT_MAX_PER_VPS", 20, lo=1, hi=500)
SVMP_PORT_ALLOW_CUSTOM = _svmp_env_bool("PORT_ALLOW_CUSTOM", False)
SVMP_TCP_ONLY_PORTS = {22, 80, 443, 5000, 8080, 8443}

SVMP_IP_MODE = os.getenv("IPAM_BIND_MODE", "record").strip().lower()      # record | bridged | nat
SVMP_IP_AUTO = _svmp_env_bool("IPAM_AUTO_ASSIGN", False)
SVMP_IP_HOST_IFACE = os.getenv("IPAM_HOST_IFACE", "").strip()
SVMP_POOL_MAX = _svmp_env_int("IPAM_POOL_MAX_ADDRS", 4096, lo=16, hi=65536)


# ------------------------------- DB helpers ---------------------------------
def svmp_exec(sql, params=(), fetch=None):
    """Thread-safe single statement helper. fetch: None|'one'|'all'|'id'."""
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.execute(sql, params)
            if fetch == "one":
                row = cur.fetchone()
                out = dict(row) if row else None
            elif fetch == "all":
                out = [dict(r) for r in cur.fetchall()]
            elif fetch == "id":
                out = cur.lastrowid
            else:
                out = cur.rowcount
            conn.commit()
            return out
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def svmp_now():
    return datetime.now().isoformat()


def svmp_migrate():
    with DB_LOCK:
        conn = get_db()
        try:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS svm_ip_pools (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                cidr TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 4,
                gateway TEXT,
                node_id INTEGER,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS svm_ipam (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                address TEXT UNIQUE NOT NULL,
                version INTEGER NOT NULL DEFAULT 4,
                status TEXT NOT NULL DEFAULT 'available',
                vps_id INTEGER,
                node_id INTEGER,
                note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS svm_billing (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                vps_id INTEGER,
                plan_slug TEXT,
                amount_paise INTEGER NOT NULL DEFAULT 0,
                currency TEXT NOT NULL DEFAULT 'INR',
                status TEXT NOT NULL DEFAULT 'pending',
                period_days INTEGER NOT NULL DEFAULT 30,
                starts_at TEXT,
                expires_at TEXT,
                provider TEXT,
                provider_ref TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS svm_port_reserved (
                port INTEGER PRIMARY KEY,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS svm_webhook_events (
                event_id TEXT PRIMARY KEY,
                gateway TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS svm_provider_health (
                provider TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                details TEXT,
                checked_at TEXT NOT NULL
            );
            """)

            def add_col(table, name, ddl):
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                if name not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

            add_col("svm_ipam", "pool_id", "INTEGER")
            add_col("svm_ipam", "container_name", "TEXT")
            add_col("svm_ipam", "bind_mode", "TEXT")
            add_col("svm_ipam", "private_ip", "TEXT")
            add_col("port_forwards", "proto", "TEXT DEFAULT 'both'")
            add_col("v112v_orders", "gateway_ref", "TEXT")
            add_col("v112v_orders", "pay_url", "TEXT")
            add_col("v112v_orders", "gw_amount", "INTEGER")
            add_col("v112v_orders", "kind", "TEXT DEFAULT 'new'")
            add_col("v112v_orders", "vps_container", "TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_svmp_ipam_status ON svm_ipam(status, version)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_svmp_orders_status ON v112v_orders(status, created_at)")
            conn.commit()
        finally:
            conn.close()


svmp_migrate()


# ============================================================================
# PORT FORWARDING v2
#  - configurable range, reserved ports, real host-socket check (local node)
#  - TCP / UDP / both, per-VPS limit, ownership checks, sync/repair
# ============================================================================
_SVMP_PORT_LOCK = threading.Lock()
_SVMP_PORT_INFLIGHT = set()


def svmp_reserved_ports():
    ports = set()
    for chunk in os.getenv("PORT_RESERVED", "").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ports.add(int(chunk))
    try:
        for row in svmp_exec("SELECT port FROM svm_port_reserved", fetch="all"):
            ports.add(int(row["port"]))
    except Exception:
        pass
    return ports


def svmp_host_port_free(port):
    """True when nothing on this host is bound to the port (TCP+UDP)."""
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        sock = socket.socket(socket.AF_INET, kind)
        try:
            sock.bind(("0.0.0.0", int(port)))
        except OSError:
            return False
        finally:
            sock.close()
    return True


def get_available_host_port(node_id: int) -> Optional[int]:
    rows = svmp_exec(
        "SELECT host_port FROM port_forwards WHERE vps_container IN "
        "(SELECT container_name FROM vps WHERE node_id = ?)", (node_id,), fetch="all")
    used = {int(r["host_port"]) for r in rows}
    reserved = svmp_reserved_ports()
    try:
        node = get_node(node_id)
    except Exception:
        node = None
    check_socket = bool(node and node.get("is_local"))
    span = range(SVMP_PORT_LO, SVMP_PORT_HI + 1)
    sample = random.sample(span, min(len(span), 600))
    with _SVMP_PORT_LOCK:
        for port in itertools.chain(sample, span):
            if port in used or port in reserved or port in _SVMP_PORT_INFLIGHT:
                continue
            if check_socket and not svmp_host_port_free(port):
                continue
            _SVMP_PORT_INFLIGHT.add(port)
            return port
    return None


def _svmp_protos(proto):
    proto = (proto or "both").lower()
    return ["tcp", "udp"] if proto == "both" else [proto]


async def create_port_forward(user_id: str, container: str, vps_port: int, node_id: int,
                              proto: Optional[str] = None, host_port: Optional[int] = None) -> Optional[int]:
    try:
        vps_port = int(vps_port)
        if not 1 <= vps_port <= 65535:
            return None
    except (TypeError, ValueError):
        return None
    if proto is None:
        proto = "tcp" if vps_port in SVMP_TCP_ONLY_PORTS else "both"
    proto = proto.lower()
    if proto not in ("tcp", "udp", "both"):
        return None

    existing = svmp_exec("SELECT COUNT(*) AS c FROM port_forwards WHERE vps_container = ?", (container,), fetch="one")
    if existing and existing["c"] >= SVMP_PORT_MAX_PER_VPS:
        logger.warning("Port forward limit reached for %s", container)
        return None

    if host_port is not None:
        host_port = int(host_port)
        taken = svmp_exec("SELECT 1 AS x FROM port_forwards WHERE host_port = ? AND vps_container IN "
                          "(SELECT container_name FROM vps WHERE node_id = ?)", (host_port, node_id), fetch="one")
        if (taken or not SVMP_PORT_LO <= host_port <= SVMP_PORT_HI
                or host_port in svmp_reserved_ports()):
            return None
        with _SVMP_PORT_LOCK:
            if host_port in _SVMP_PORT_INFLIGHT:
                return None
            _SVMP_PORT_INFLIGHT.add(host_port)
    else:
        host_port = get_available_host_port(node_id)
    if not host_port:
        logger.error("No available host port for %s", container)
        return None

    created = []
    try:
        for p in _svmp_protos(proto):
            await execute_lxc(
                container,
                f"config device add {container} {p}_proxy_{host_port} "
                f"proxy listen={p}:0.0.0.0:{host_port} connect={p}:127.0.0.1:{vps_port}",
                node_id=node_id)
            created.append(p)
        svmp_exec(
            "INSERT INTO port_forwards (user_id, vps_container, vps_port, host_port, proto, created_at, last_modified) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (str(user_id), container, vps_port, host_port, proto, svmp_now()))
        return host_port
    except Exception as e:
        logger.error("Failed to create port forward %s->%s on %s: %s", host_port, vps_port, container, e)
        for p in created:      # roll back half-created devices
            try:
                await execute_lxc(container, f"config device remove {container} {p}_proxy_{host_port}", node_id=node_id)
            except Exception:
                pass
        return None
    finally:
        with _SVMP_PORT_LOCK:
            _SVMP_PORT_INFLIGHT.discard(host_port)


async def remove_port_forward(forward_id: int, is_admin: bool = False) -> tuple[bool, Optional[str]]:
    row = svmp_exec("SELECT user_id, vps_container, host_port, proto FROM port_forwards WHERE id = ?",
                    (forward_id,), fetch="one")
    if not row:
        return False, None
    container, host_port = row["vps_container"], row["host_port"]
    try:
        node_id = find_node_id_for_container(container)
    except Exception as e:
        logger.error("remove_port_forward: node lookup failed: %s", e)
        return False, None
    failed = False
    for p in _svmp_protos(row.get("proto") or "both"):
        try:
            await execute_lxc(container, f"config device remove {container} {p}_proxy_{host_port}", node_id=node_id)
        except Exception as e:
            msg = str(e).lower()
            if "exist" in msg or "not found" in msg:      # device already gone
                continue
            logger.error("Failed to remove %s proxy %s on %s: %s", p, host_port, container, e)
            failed = True
    if failed:
        return False, None
    svmp_exec("DELETE FROM port_forwards WHERE id = ?", (forward_id,))
    return True, row["user_id"]


async def recreate_port_forwards(container_name: str) -> int:
    node_id = find_node_id_for_container(container_name)
    rows = svmp_exec("SELECT vps_port, host_port, proto FROM port_forwards WHERE vps_container = ?",
                     (container_name,), fetch="all")
    readded = 0
    for row in rows:
        ok = True
        for p in _svmp_protos(row.get("proto") or "both"):
            try:
                await execute_lxc(
                    container_name,
                    f"config device add {container_name} {p}_proxy_{row['host_port']} "
                    f"proxy listen={p}:0.0.0.0:{row['host_port']} connect={p}:127.0.0.1:{row['vps_port']}",
                    node_id=node_id)
            except Exception as e:
                if "already exists" in str(e).lower():
                    continue
                ok = False
                logger.error("Failed to re-add %s forward %s->%s for %s: %s", p, row["host_port"], row["vps_port"], container_name, e)
        readded += 1 if ok else 0
    return readded


async def svmp_ports_sync(container=None):
    """Compare DB rules with real LXD devices; re-add what is missing."""
    sql = "SELECT * FROM port_forwards" + (" WHERE vps_container = ?" if container else "")
    rows = svmp_exec(sql, (container,) if container else (), fetch="all")
    by_c = {}
    for r in rows:
        by_c.setdefault(r["vps_container"], []).append(r)
    checked = repaired = failed = 0
    for cname, forwards in by_c.items():
        try:
            node_id = find_node_id_for_container(cname)
            listing = str(await execute_lxc(cname, f"config device list {cname}", node_id=node_id))
            present = {line.strip() for line in listing.splitlines()}
        except Exception as e:
            logger.warning("ports sync: cannot list devices for %s: %s", cname, e)
            failed += len(forwards)
            continue
        for r in forwards:
            for p in _svmp_protos(r.get("proto") or "both"):
                checked += 1
                dev = f"{p}_proxy_{r['host_port']}"
                if dev in present:
                    continue
                try:
                    await execute_lxc(
                        cname, f"config device add {cname} {dev} proxy "
                        f"listen={p}:0.0.0.0:{r['host_port']} connect={p}:127.0.0.1:{r['vps_port']}", node_id=node_id)
                    repaired += 1
                except Exception as e:
                    failed += 1
                    logger.error("ports sync add %s failed: %s", dev, e)
    return checked, repaired, failed


bot.remove_command("ports")        # replace the old implementation (no ownership check)


@bot.command(name="ports")
async def svmp_ports_command(ctx, subcmd: str = None, *args):
    user_id = str(ctx.author.id)
    allocated, used = get_user_allocation(user_id), get_user_used_ports(user_id)
    available = max(0, allocated - used)
    if subcmd is None:
        embed = create_info_embed("🔌 Port Forwarding", f"**Quota:** allocated `{allocated}` • used `{used}` • free `{available}`")
        add_field(embed, "Commands",
                  f"`{PREFIX}ports add <vps_num> <port> [tcp|udp|both]`\n`{PREFIX}ports list`\n`{PREFIX}ports remove <id>`", False)
        add_field(embed, "Public range", f"`{SVMP_PORT_LO}-{SVMP_PORT_HI}` on `{YOUR_SERVER_IP}`", False)
        await ctx.send(embed=embed)
        return
    sub = subcmd.lower()
    if sub == "add":
        if len(args) < 2:
            await ctx.send(embed=create_error_embed("Usage", f"`{PREFIX}ports add <vps_num> <vps_port> [tcp|udp|both]`")); return
        try:
            vps_num, vps_port = int(args[0]), int(args[1])
            assert 1 <= vps_port <= 65535
        except (ValueError, AssertionError):
            await ctx.send(embed=create_error_embed("Invalid Input", "VPS number must be an integer and the port must be 1-65535.")); return
        proto = (args[2].lower() if len(args) > 2 else None)
        if proto not in (None, "tcp", "udp", "both"):
            await ctx.send(embed=create_error_embed("Invalid Protocol", "Use tcp, udp or both.")); return
        custom = None
        if len(args) > 3:
            if not SVMP_PORT_ALLOW_CUSTOM:
                await ctx.send(embed=create_error_embed("Custom Port Disabled", "Custom public ports are disabled by the admin.")); return
            try:
                custom = int(args[3])
            except ValueError:
                await ctx.send(embed=create_error_embed("Invalid Port", "Public port must be a number.")); return
        vps_list = vps_data.get(user_id, [])
        if not 1 <= vps_num <= len(vps_list):
            await ctx.send(embed=create_error_embed("Invalid VPS", f"Choose 1-{len(vps_list)}. Use `{PREFIX}myvps` to list.")); return
        if used >= allocated:
            await ctx.send(embed=create_error_embed("Quota Exceeded", f"Allocated `{allocated}`, used `{used}`. Ask an admin for more slots.")); return
        vps = vps_list[vps_num - 1]
        host_port = await create_port_forward(user_id, vps["container_name"], vps_port, vps["node_id"], proto, custom)
        if not host_port:
            await ctx.send(embed=create_error_embed("Failed", "Could not create the forward (no free port, per-VPS limit, or container error).")); return
        shown = proto or ("tcp" if vps_port in SVMP_TCP_ONLY_PORTS else "both")
        embed = create_success_embed("Port Forward Created", f"VPS #{vps_num} port `{vps_port}` ({shown.upper()}) → public port `{host_port}`")
        add_field(embed, "Access", f"`{YOUR_SERVER_IP}:{host_port}`", False)
        add_field(embed, "Quota", f"{used + 1}/{allocated}", True)
        await ctx.send(embed=embed)
    elif sub == "list":
        forwards = get_user_forwards(user_id)
        embed = create_info_embed("Your Port Forwards", f"**Quota:** allocated `{allocated}` • used `{used}` • free `{available}`")
        if not forwards:
            add_field(embed, "Forwards", "No active port forwards.", False)
        else:
            lines = []
            for f in forwards[:15]:
                num = next((i + 1 for i, v in enumerate(vps_data.get(user_id, [])) if v["container_name"] == f["vps_container"]), "?")
                lines.append(f"**#{f['id']}** VPS {num}: `{f['vps_port']}` → `{YOUR_SERVER_IP}:{f['host_port']}` ({(f.get('proto') or 'both').upper()})")
            add_field(embed, "Active", "\n".join(lines), False)
            if len(forwards) > 15:
                add_field(embed, "Note", f"Showing 15 of {len(forwards)}.", False)
        await ctx.send(embed=embed)
    elif sub == "remove":
        try:
            fid = int(args[0])
        except (IndexError, ValueError):
            await ctx.send(embed=create_error_embed("Usage", f"`{PREFIX}ports remove <forward_id>`")); return
        owner = svmp_exec("SELECT user_id FROM port_forwards WHERE id = ?", (fid,), fetch="one")
        is_adm = user_id == str(MAIN_ADMIN_ID) or user_id in admin_data.get("admins", [])
        if not owner or (owner["user_id"] != user_id and not is_adm):
            await ctx.send(embed=create_error_embed("Not Found", "Forward not found in your account.")); return
        ok, _ = await remove_port_forward(fid, is_admin=is_adm)
        await ctx.send(embed=create_success_embed("Removed", f"Forward `{fid}` removed.") if ok
                       else create_error_embed("Failed", "Could not remove the forward. Check the logs."))
    else:
        await ctx.send(embed=create_error_embed("Invalid Subcommand", "Use add, list or remove."))


@bot.command(name="portadmin")
@is_admin()
async def svmp_portadmin(ctx, action: str = "stats", *args):
    action = action.lower()
    if action == "stats":
        total = svmp_exec("SELECT COUNT(*) AS c FROM port_forwards", fetch="one")["c"]
        reserved = len(svmp_reserved_ports())
        span = SVMP_PORT_HI - SVMP_PORT_LO + 1
        embed = create_info_embed("🔌 Port Forwarding Stats", f"Range `{SVMP_PORT_LO}-{SVMP_PORT_HI}` ({span} ports)")
        add_field(embed, "Active forwards", str(total), True)
        add_field(embed, "Reserved", str(reserved), True)
        add_field(embed, "Per-VPS limit", str(SVMP_PORT_MAX_PER_VPS), True)
        await ctx.send(embed=embed)
    elif action == "list":
        rows = svmp_exec("SELECT * FROM port_forwards " + ("WHERE user_id = ? " if args else "") + "ORDER BY id DESC LIMIT 25",
                         (str(args[0]).strip("<@!>"),) if args else (), fetch="all")
        text = "\n".join(f"#{r['id']} <@{r['user_id']}> `{r['vps_container']}` {r['vps_port']}→{r['host_port']} ({(r.get('proto') or 'both')})" for r in rows) or "None."
        await ctx.send(embed=create_info_embed("Port Forwards", text[:4000]))
    elif action in ("reserve", "unreserve"):
        try:
            port = int(args[0])
            assert 1 <= port <= 65535
        except (IndexError, ValueError, AssertionError):
            await ctx.send(embed=create_error_embed("Usage", f"`{PREFIX}portadmin {action} <port> [note]`")); return
        if action == "reserve":
            svmp_exec("INSERT OR REPLACE INTO svm_port_reserved(port,note,created_at) VALUES(?,?,?)", (port, " ".join(args[1:])[:200], svmp_now()))
        else:
            svmp_exec("DELETE FROM svm_port_reserved WHERE port = ?", (port,))
        await ctx.send(embed=create_success_embed("Done", f"Port `{port}` {action}d."))
    elif action == "sync":
        msg = await ctx.send(embed=create_info_embed("Syncing", "Comparing database rules with LXD proxy devices…"))
        checked, repaired, failed = await svmp_ports_sync()
        await msg.edit(embed=create_success_embed("Port Sync Complete", f"Checked `{checked}` • repaired `{repaired}` • failed `{failed}`"))
    else:
        await ctx.send(embed=create_error_embed("Usage", f"`{PREFIX}portadmin stats|list [user]|reserve <port>|unreserve <port>|sync`"))


# ============================================================================
# IP POOL (IPAM v2)
#  - CIDR pools with per-node scoping, atomic allocation, reserve/release
#  - bind modes: record (bookkeeping) | bridged (LXD static eth0 address) |
#    nat (host iptables DNAT/SNAT for public IPs on the local node)
# ============================================================================
def svmp_expand_cidr(cidr, limit=None):
    """Return (network, [host addresses], truncated)."""
    limit = limit or SVMP_POOL_MAX
    net = ipaddress.ip_network(str(cidr).strip(), strict=False)
    hosts = iter(net) if net.version == 4 and net.prefixlen >= 31 else net.hosts()
    addrs = list(itertools.islice(hosts, limit + 1))
    truncated = len(addrs) > limit
    if truncated:
        if net.version == 4:
            raise ValueError(f"Pool has more than {limit} addresses. Split it or raise IPAM_POOL_MAX_ADDRS.")
        addrs = addrs[:limit]
    return net, addrs, truncated


def svmp_pool_add(name, cidr, gateway=None, node_id=None, reserve_first=0):
    net, addrs, truncated = svmp_expand_cidr(cidr)
    gw = str(ipaddress.ip_address(gateway)) if gateway else None
    now = svmp_now()
    with DB_LOCK:
        conn = get_db()
        try:
            cur = conn.execute(
                "INSERT INTO svm_ip_pools(name,cidr,version,gateway,node_id,enabled,created_at) VALUES(?,?,?,?,?,1,?)",
                (name, str(net), net.version, gw, node_id, now))
            pool_id = cur.lastrowid
            rows = []
            for i, a in enumerate(addrs):
                a = str(a)
                if a == gw:
                    continue
                status = "reserved" if i < reserve_first else "available"
                rows.append((a, net.version, status, node_id, pool_id, now, now))
            conn.executemany(
                "INSERT OR IGNORE INTO svm_ipam(address,version,status,node_id,pool_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", rows)
            conn.commit()
            return pool_id, len(rows), truncated
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()



def svmp_seed_pools():
    """IPAM_POOLS="name|cidr|gateway|node_id;name2|cidr2" -> created once, existing names are skipped."""
    created = 0
    for spec in filter(None, (s.strip() for s in os.getenv("IPAM_POOLS", "").split(";"))):
        parts = [p.strip() for p in spec.split("|")]
        if len(parts) < 2:
            logger.warning("IPAM_POOLS entry ignored (need name|cidr): %s", spec)
            continue
        name, cidr = parts[0], parts[1]
        gateway = parts[2] if len(parts) > 2 and parts[2] else None
        node = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        if svmp_exec("SELECT 1 AS x FROM svm_ip_pools WHERE name=?", (name,), fetch="one"):
            continue
        try:
            _, count, _ = svmp_pool_add(name, cidr, gateway, node)
            created += 1
            logger.info("IP pool %s seeded with %s addresses", name, count)
        except Exception as e:
            logger.error("IPAM_POOLS seed failed for %s: %s", name, e)
    return created


def svmp_ip_alloc(container, vps_id=None, node_id=None, version=4, pool=None):
    with DB_LOCK:
        conn = get_db()
        try:
            sql = ("SELECT a.* FROM svm_ipam a LEFT JOIN svm_ip_pools p ON p.id = a.pool_id "
                   "WHERE a.status='available' AND a.version=? AND (p.id IS NULL OR p.enabled=1)")
            params = [version]
            if pool:
                sql += " AND p.name = ?"
                params.append(pool)
            if node_id is not None:
                sql += " AND (a.node_id IS NULL OR a.node_id = ?)"
                params.append(node_id)
            row = conn.execute(sql + " ORDER BY a.id LIMIT 1", params).fetchone()
            if not row:
                return None
            cur = conn.execute(
                "UPDATE svm_ipam SET status='allocated', vps_id=?, container_name=?, bind_mode=?, updated_at=? "
                "WHERE id=? AND status='available'", (vps_id, container, SVMP_IP_MODE, svmp_now(), row["id"]))
            conn.commit()
            if cur.rowcount != 1:
                return None
            out = dict(row)
            out.update(status="allocated", container_name=container, bind_mode=SVMP_IP_MODE)
            return out
        finally:
            conn.close()


def svmp_ip_free(address):
    svmp_exec("UPDATE svm_ipam SET status='available', vps_id=NULL, container_name=NULL, bind_mode=NULL, "
              "private_ip=NULL, updated_at=? WHERE address=?", (svmp_now(), address))


async def svmp_host(*args, timeout=20):
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, out.decode(errors="ignore").strip(), err.decode(errors="ignore").strip()
    except FileNotFoundError:
        return 127, "", f"{args[0]} not found"
    except asyncio.TimeoutError:
        return 124, "", "timeout"


async def svmp_container_private_ip(container, node_id):
    out = str(await execute_lxc(container, f"list ^{container}$ -c 4 --format csv", node_id=node_id))
    m = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})\s*\(eth0\)", out) or re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", out)
    return m.group(1) if m else None


async def svmp_nat_apply(public_ip, private_ip, add=True):
    pub, priv = str(ipaddress.IPv4Address(public_ip)), str(ipaddress.IPv4Address(private_ip))
    rules = [("PREROUTING", ["-d", pub, "-j", "DNAT", "--to-destination", priv], "-A"),
             ("POSTROUTING", ["-s", priv, "-j", "SNAT", "--to-source", pub], "-I")]
    for chain, spec, insert_flag in rules:
        rc, _, _ = await svmp_host("iptables", "-t", "nat", "-C", chain, *spec)
        exists = rc == 0
        if add and not exists:
            extra = ["1"] if insert_flag == "-I" else []
            rc, _, err = await svmp_host("iptables", "-t", "nat", insert_flag, chain, *extra, *spec)
            if rc != 0:
                return False, f"iptables failed: {err[:200]}"
        elif not add and exists:
            await svmp_host("iptables", "-t", "nat", "-D", chain, *spec)
    if SVMP_IP_HOST_IFACE:
        if add:
            await svmp_host("ip", "addr", "replace", f"{pub}/32", "dev", SVMP_IP_HOST_IFACE)
        else:
            await svmp_host("ip", "addr", "del", f"{pub}/32", "dev", SVMP_IP_HOST_IFACE)
    return True, "NAT rules active"


async def svmp_ip_bind(addr, version, container, node_id, mode=None):
    """Returns (ok, detail, private_ip)."""
    mode = (mode or SVMP_IP_MODE or "record").lower()
    if mode == "record":
        return True, "Recorded in IPAM (no network change)", None
    if mode == "bridged":
        key = "ipv4.address" if version == 4 else "ipv6.address"
        try:
            await execute_lxc(container, f"config device override {container} eth0 {key}={addr}", node_id=node_id)
        except Exception:
            try:
                await execute_lxc(container, f"config device set {container} eth0 {key} {addr}", node_id=node_id)
            except Exception as e:
                return False, f"LXD bind failed: {str(e)[:300]}", None
        return True, "Bound to eth0 — restart the VPS to apply", None
    if mode == "nat":
        if version != 4:
            return False, "NAT mode supports IPv4 only", None
        node = get_node(node_id)
        if not node or not node.get("is_local"):
            return False, "NAT mode works only for VPS on the bot's local node", None
        priv = await svmp_container_private_ip(container, node_id)
        if not priv:
            return False, "Could not detect the VPS private IPv4 (is it running?)", None
        ok, detail = await svmp_nat_apply(addr, priv, add=True)
        return ok, detail, (priv if ok else None)
    return False, f"Unknown IPAM_BIND_MODE `{mode}`", None


async def svmp_ip_unbind(row):
    mode, addr = (row.get("bind_mode") or "record"), row["address"]
    container = row.get("container_name")
    try:
        if mode == "bridged" and container:
            node_id = find_node_id_for_container(container)
            key = "ipv4.address" if row["version"] == 4 else "ipv6.address"
            await execute_lxc(container, f"config device unset {container} eth0 {key}", node_id=node_id)
        elif mode == "nat" and row.get("private_ip"):
            await svmp_nat_apply(addr, row["private_ip"], add=False)
    except Exception as e:
        logger.warning("IP unbind %s (%s) incomplete: %s", addr, mode, e)


async def svmp_ip_sync():
    """Re-apply NAT mappings (iptables rules do not survive a reboot)."""
    ok = bad = 0
    rows = svmp_exec("SELECT * FROM svm_ipam WHERE status='allocated' AND bind_mode='nat' AND private_ip IS NOT NULL", fetch="all")
    for r in rows:
        success, _ = await svmp_nat_apply(r["address"], r["private_ip"], add=True)
        ok, bad = (ok + 1, bad) if success else (ok, bad + 1)
    return ok, bad


def svmp_find_vps(query):
    q = str(query).strip()
    for uid, items in vps_data.items():
        for v in items:
            if q in (str(v.get("container_name", "")), str(v.get("id", "")), str(v.get("vmid", ""))):
                out = dict(v)
                out["_owner_id"] = str(uid)
                return out
    try:
        row = v112v_find_vps(q)
        if row:
            row["_owner_id"] = str(row.get("user_id", ""))
            return row
    except Exception:
        pass
    return None


async def svmp_assign_ip(vps, version=4, pool=None, mode=None):
    """Allocate + bind. Returns (ok, message, address)."""
    container, node_id = vps["container_name"], vps.get("node_id", 1)
    row = svmp_ip_alloc(container, vps.get("id"), node_id, version, pool)
    if not row:
        return False, f"No free IPv{version} address" + (f" in pool `{pool}`" if pool else ""), None
    ok, detail, priv = await svmp_ip_bind(row["address"], version, container, node_id, mode)
    if not ok:
        svmp_ip_free(row["address"])
        return False, detail, None
    if priv:
        svmp_exec("UPDATE svm_ipam SET private_ip=? WHERE id=?", (priv, row["id"]))
    try:                                       # mirror to the VPS record shown by other commands
        field = "ipv4" if version == 4 else "ipv6"
        vps_ref = next((v for v in vps_data.get(vps.get("_owner_id", ""), []) if v["container_name"] == container), None)
        if vps_ref is not None:
            vps_ref[field] = row["address"]
            save_vps_data()
        if vps.get("id"):
            svmp_exec(f"UPDATE v112v_vps_meta SET {field}=?, updated_at=? WHERE vps_db_id=?", (row["address"], svmp_now(), vps["id"]))
    except Exception as e:
        logger.debug("IP mirror skipped: %s", e)
    return True, detail, row["address"]


@bot.command(name="ipool", aliases=["ipam"])
@is_admin()
async def svmp_ipool(ctx, action: str = "list", *args):
    action = action.lower()
    usage = (f"`{PREFIX}ipool add <name> <cidr> [gateway] [node_id]`\n`{PREFIX}ipool list` • `show <pool>`\n"
             f"`{PREFIX}ipool alloc <vps> [4|6] [pool]` • `release <ip>` • `reserve <ip> [note]`\n"
             f"`{PREFIX}ipool remove <pool>` • `sync` • `mode`")
    try:
        if action == "add":
            if len(args) < 2:
                await ctx.send(embed=create_error_embed("Usage", usage)); return
            gateway = args[2] if len(args) > 2 and not args[2].isdigit() else None
            node_arg = args[-1] if len(args) > 2 and args[-1].isdigit() else None
            _, count, truncated = svmp_pool_add(args[0], args[1], gateway, int(node_arg) if node_arg else None)
            note = "\nIPv6 pool truncated to the configured maximum." if truncated else ""
            await ctx.send(embed=create_success_embed("Pool Created", f"`{args[0]}` ← `{args[1]}` • **{count}** addresses{note}"))
        elif action == "list":
            rows = svmp_exec(
                "SELECT p.name, p.cidr, p.version, p.node_id, p.enabled, COUNT(a.id) AS total, "
                "COALESCE(SUM(a.status='allocated'),0) AS used, COALESCE(SUM(a.status='reserved'),0) AS res, "
                "COALESCE(SUM(a.status='available'),0) AS free FROM svm_ip_pools p "
                "LEFT JOIN svm_ipam a ON a.pool_id=p.id GROUP BY p.id ORDER BY p.id", fetch="all")
            loose = svmp_exec("SELECT COUNT(*) AS c FROM svm_ipam WHERE pool_id IS NULL", fetch="one")["c"]
            lines = [f"**{r['name']}** `{r['cidr']}` • node `{r['node_id'] or 'any'}` • free `{r['free']}` / used `{r['used']}` / reserved `{r['res']}` / total `{r['total']}`"
                     for r in rows]
            if loose:
                lines.append(f"Unpooled addresses: `{loose}`")
            await ctx.send(embed=create_info_embed(f"🌐 IP Pools • mode `{SVMP_IP_MODE}`", "\n".join(lines) or f"No pools yet.\n{usage}"))
        elif action == "show":
            if not args:
                await ctx.send(embed=create_error_embed("Usage", usage)); return
            rows = svmp_exec(
                "SELECT a.address, a.status, a.container_name FROM svm_ipam a JOIN svm_ip_pools p ON p.id=a.pool_id "
                "WHERE p.name=? ORDER BY a.id LIMIT 40", (args[0],), fetch="all")
            text = "\n".join(f"`{r['address']}` • **{r['status']}**" + (f" • `{r['container_name']}`" if r["container_name"] else "") for r in rows) or "Pool not found."
            await ctx.send(embed=create_info_embed(f"Pool {args[0]} (first 40)", text[:4000]))
        elif action == "alloc":
            if not args:
                await ctx.send(embed=create_error_embed("Usage", usage)); return
            vps = svmp_find_vps(args[0])
            if not vps:
                await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS matched `{args[0]}`.")); return
            version = 6 if len(args) > 1 and args[1] == "6" else 4
            pool = args[2] if len(args) > 2 else (args[1] if len(args) > 1 and args[1] not in ("4", "6") else None)
            ok, detail, address = await svmp_assign_ip(vps, version, pool)
            await ctx.send(embed=create_success_embed("IP Allocated", f"`{address}` → `{vps['container_name']}`\n{detail}") if ok
                           else create_error_embed("Allocation Failed", detail))
        elif action == "release":
            if not args:
                await ctx.send(embed=create_error_embed("Usage", usage)); return
            row = svmp_exec("SELECT * FROM svm_ipam WHERE address=?", (args[0],), fetch="one")
            if not row:
                await ctx.send(embed=create_error_embed("Not Found", f"`{args[0]}` is not in IPAM.")); return
            await svmp_ip_unbind(row)
            svmp_ip_free(row["address"])
            await ctx.send(embed=create_success_embed("IP Released", f"`{row['address']}` is available again."))
        elif action == "reserve":
            if not args:
                await ctx.send(embed=create_error_embed("Usage", usage)); return
            addr = str(ipaddress.ip_address(args[0]))
            now = svmp_now()
            svmp_exec("INSERT OR IGNORE INTO svm_ipam(address,version,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                      (addr, ipaddress.ip_address(addr).version, "available", now, now))
            svmp_exec("UPDATE svm_ipam SET status='reserved', note=?, updated_at=? WHERE address=? AND status='available'",
                      (" ".join(args[1:])[:200], now, addr))
            await ctx.send(embed=create_success_embed("Reserved", f"`{addr}` will not be auto-assigned."))
        elif action == "remove":
            if not args:
                await ctx.send(embed=create_error_embed("Usage", usage)); return
            pool = svmp_exec("SELECT id FROM svm_ip_pools WHERE name=?", (args[0],), fetch="one")
            if not pool:
                await ctx.send(embed=create_error_embed("Not Found", "Pool not found.")); return
            busy = svmp_exec("SELECT COUNT(*) AS c FROM svm_ipam WHERE pool_id=? AND status='allocated'", (pool["id"],), fetch="one")["c"]
            if busy:
                await ctx.send(embed=create_error_embed("Pool In Use", f"{busy} address(es) are still allocated. Release them first.")); return
            svmp_exec("DELETE FROM svm_ipam WHERE pool_id=?", (pool["id"],))
            svmp_exec("DELETE FROM svm_ip_pools WHERE id=?", (pool["id"],))
            await ctx.send(embed=create_success_embed("Pool Removed", f"`{args[0]}` deleted."))
        elif action == "sync":
            ok, bad = await svmp_ip_sync()
            await ctx.send(embed=create_success_embed("IP Sync", f"NAT mappings re-applied: `{ok}` ok • `{bad}` failed"))
        elif action == "mode":
            await ctx.send(embed=create_info_embed("IP Bind Mode", f"Current: `{SVMP_IP_MODE}` • auto-assign on purchase: `{SVMP_IP_AUTO}`\nChange `IPAM_BIND_MODE` (record|bridged|nat) in `.env` and restart."))
        else:
            await ctx.send(embed=create_error_embed("Usage", usage))
    except sqlite3.IntegrityError:
        await ctx.send(embed=create_error_embed("Already Exists", "A pool with that name already exists."))
    except ValueError as e:
        await ctx.send(embed=create_error_embed("Invalid Input", str(e)[:500]))


# ============================================================================
# PAYMENT GATEWAYS v2  (Razorpay Payment Links • Stripe Checkout • manual UPI)
#  - the gateway backend / signed webhook is the ONLY automatic payment authority
#  - one atomic status transition (created -> paid) so duplicate events can never
#    provision twice; orders end as provisioned / renewed
#  - signed webhooks (Razorpay HMAC-SHA256, Stripe t=/v1= scheme), event dedupe
# ============================================================================
if "main_admin_ids" not in globals():
    main_admin_ids = {str(MAIN_ADMIN_ID)}

_svmp_orig_provision = v112v_auto_provision_order


def svmp_enabled_gateways():
    out = []
    for g in [x.strip().lower() for x in SVMP_GATEWAYS_RAW.split(",") if x.strip()]:
        if g == "razorpay" and RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
            out.append(g)
        elif g == "stripe" and STRIPE_SECRET_KEY:
            out.append(g)
        elif g == "upi" and UPI_ENABLED and UPI_ID:
            out.append(g)
    return out


def svmp_is_admin_id(user_id):
    return str(user_id) == str(MAIN_ADMIN_ID) or str(user_id) in admin_data.get("admins", [])


def svmp_get_order(order_id):
    try:
        return svmp_exec("SELECT * FROM v112v_orders WHERE id=?", (int(order_id),), fetch="one")
    except (TypeError, ValueError):
        return None


def svmp_set_order_status(order_id, status):
    svmp_exec("UPDATE v112v_orders SET status=? WHERE id=?", (status, int(order_id)))


def svmp_create_order(user_id, plan_slug, amount_paise, provider, kind="new", vps_container=None):
    return svmp_exec(
        "INSERT INTO v112v_orders(user_id,plan_slug,amount_paise,currency,provider,status,created_at,kind,vps_container) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (str(user_id), plan_slug, int(amount_paise), "INR", provider, "created", svmp_now(), kind, vps_container), fetch="id")


# ----------------------------- gateway calls --------------------------------
def svmp_gw_razorpay(order_id, user_id, desc, amount_paise):
    payload = {
        "amount": int(amount_paise), "currency": "INR", "accept_partial": False,
        "reference_id": f"svm-{order_id}", "description": desc[:200],
        "notes": {"order_id": str(order_id), "user_id": str(user_id)},
        "expire_by": int(time.time()) + SVMP_ORDER_TTL_MIN * 60, "reminder_enable": False,
    }
    r = requests.post("https://api.razorpay.com/v1/payment_links", headers=razorpay_headers(), json=payload, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Razorpay HTTP {r.status_code}: {r.text[:250]}")
    data = r.json()
    return {"ref": data["id"], "url": data.get("short_url", ""), "gw_amount": int(amount_paise)}


def svmp_gw_stripe(order_id, user_id, desc, amount_paise):
    minor = int(round(int(amount_paise) * STRIPE_AMOUNT_RATE))
    if minor <= 0:
        raise RuntimeError("Computed Stripe amount is zero; check STRIPE_AMOUNT_RATE")
    form = {
        "mode": "payment", "success_url": PAYMENT_SUCCESS_URL, "cancel_url": PAYMENT_CANCEL_URL,
        "client_reference_id": str(order_id), "metadata[order_id]": str(order_id), "metadata[user_id]": str(user_id),
        "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": STRIPE_CURRENCY,
        "line_items[0][price_data][unit_amount]": str(minor),
        "line_items[0][price_data][product_data][name]": desc[:120],
        "expires_at": str(int(time.time()) + max(31, SVMP_ORDER_TTL_MIN) * 60),
    }
    r = requests.post("https://api.stripe.com/v1/checkout/sessions", data=form,
                      headers={"Authorization": f"Bearer {STRIPE_SECRET_KEY}"}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe HTTP {r.status_code}: {r.text[:250]}")
    data = r.json()
    return {"ref": data["id"], "url": data.get("url", ""), "gw_amount": minor}


def svmp_gw_upi(order_id, user_id, desc, amount_paise):
    ref = f"SVM{order_id}"
    link = (f"upi://pay?pa={quote(UPI_ID)}&pn={quote(UPI_NAME)}&am={amount_paise / 100:.2f}&cu=INR&tn={ref}")
    return {"ref": ref, "url": "", "gw_amount": int(amount_paise), "upi_link": link}


def svmp_checkout(gateway, order_id, user_id, desc, amount_paise):
    info = {"razorpay": svmp_gw_razorpay, "stripe": svmp_gw_stripe, "upi": svmp_gw_upi}[gateway](order_id, user_id, desc, amount_paise)
    svmp_exec("UPDATE v112v_orders SET gateway_ref=?, provider_order_id=?, pay_url=?, gw_amount=? WHERE id=?",
              (info["ref"], info["ref"], info.get("url") or info.get("upi_link", ""), info["gw_amount"], order_id))
    return info


# ----------------------------- verification ---------------------------------
def svmp_verify_razorpay_signature(raw, signature):
    if not RAZORPAY_WEBHOOK_SECRET or not signature:
        return False
    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def svmp_verify_stripe_signature(raw, header, tolerance=300):
    if not STRIPE_WEBHOOK_SECRET or not header:
        return False
    stamp, sigs = None, []
    for item in header.split(","):
        key, _, val = item.strip().partition("=")
        if key == "t":
            stamp = val
        elif key == "v1":
            sigs.append(val)
    try:
        if not stamp or not sigs or abs(time.time() - int(stamp)) > tolerance:
            return False
    except ValueError:
        return False
    expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), f"{stamp}.".encode() + raw, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def svmp_razorpay_confirm(payment_id, expected_amount):
    """Ask Razorpay directly - never trust the webhook body alone."""
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET) or not re.fullmatch(r"pay_[A-Za-z0-9]+", str(payment_id or "")):
        return False, "credentials or payment id invalid"
    r = requests.get(f"https://api.razorpay.com/v1/payments/{payment_id}", headers=razorpay_headers(), timeout=15)
    r.raise_for_status()
    p = r.json()
    if int(p.get("amount", -1)) != int(expected_amount) or str(p.get("currency", "INR")).upper() != "INR":
        return False, "amount/currency mismatch"
    allowed = {"captured"} | ({"authorized"} if SVMP_ACCEPT_AUTHORIZED else set())
    if p.get("status") not in allowed:
        return False, f"payment status {p.get('status')}"
    return True, p


# ------------------------------ order engine --------------------------------
def svmp_schedule_provision(order_id):
    if SVMP_LOOP and SVMP_LOOP.is_running():
        asyncio.run_coroutine_threadsafe(v112v_auto_provision_order(order_id), SVMP_LOOP)
    else:
        logger.error("Bot loop not ready; order %s stays 'paid' - run the retry command", order_id)


def svmp_mark_order_paid(order_id, payment_ref, raw="", source="gateway", allow_from=("created", "expired", "cancelled")):
    marks = ",".join("?" * len(allow_from))
    try:
        n = svmp_exec(
            f"UPDATE v112v_orders SET status='paid', provider_payment_id=?, verified_at=?, raw_event=? "
            f"WHERE id=? AND status IN ({marks})", (payment_ref, svmp_now(), raw[:20000], int(order_id), *allow_from))
    except sqlite3.IntegrityError:
        logger.warning("Payment reference %s already used on another order", payment_ref)
        return False
    if n != 1:
        return False
    v112v_audit("system", "payment_verified", str(order_id), f"{source}:{payment_ref}")
    svmp_schedule_provision(order_id)
    return True


def svmp_handle_razorpay(event):
    et = event.get("event", "")
    payload = event.get("payload") or {}
    pay = ((payload.get("payment") or {}).get("entity")) or {}
    if et == "payment_link.paid":
        link = ((payload.get("payment_link") or {}).get("entity")) or {}
        order = svmp_exec("SELECT * FROM v112v_orders WHERE gateway_ref=? AND provider='razorpay'", (link.get("id"),), fetch="one")
    elif et == "payment.captured" or (et == "payment.authorized" and SVMP_ACCEPT_AUTHORIZED):
        order = svmp_exec("SELECT * FROM v112v_orders WHERE provider_order_id=? AND provider='razorpay'", (pay.get("order_id"),), fetch="one")
    else:
        return "ignored"
    if not order:
        return "unknown order"
    if order["status"] not in ("created", "expired", "cancelled"):
        return f"order already {order['status']}"
    ok, detail = svmp_razorpay_confirm(pay.get("id"), order["gw_amount"] or order["amount_paise"])
    if not ok:
        logger.warning("Razorpay payment rejected for order %s: %s", order["id"], detail)
        return f"rejected: {detail}"
    return "paid" if svmp_mark_order_paid(order["id"], pay["id"], json.dumps(event), "razorpay") else "duplicate"


def svmp_handle_stripe(event):
    if event.get("type") not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return "ignored"
    obj = ((event.get("data") or {}).get("object")) or {}
    if obj.get("payment_status") != "paid":
        return "not paid yet"
    order = svmp_exec("SELECT * FROM v112v_orders WHERE gateway_ref=? AND provider='stripe'", (obj.get("id"),), fetch="one")
    if not order:
        return "unknown session"
    if order["status"] not in ("created", "expired", "cancelled"):
        return f"order already {order['status']}"
    if int(obj.get("amount_total", -1)) != int(order["gw_amount"] or -2) or str(obj.get("currency", "")).lower() != STRIPE_CURRENCY:
        logger.warning("Stripe amount/currency mismatch for order %s", order["id"])
        return "rejected: amount mismatch"
    ref = obj.get("payment_intent") or obj["id"]
    return "paid" if svmp_mark_order_paid(order["id"], ref, json.dumps(event), "stripe") else "duplicate"


# ------------------------------ webhook server ------------------------------
_SVMP_WEBHOOK = {"server": None}


class SvmpWebhookHandler(BaseHTTPRequestHandler):
    server_version = "SVMPlus"

    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._send(200, json.dumps({"ok": True, "version": SVMP_VERSION}).encode(), "application/json")
        else:
            self._send(404, b"not found")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 1_000_000:
            self._send(413, b"bad length")
            return
        raw = self.rfile.read(length)
        try:
            if path == "/razorpay/webhook":
                if not svmp_verify_razorpay_signature(raw, self.headers.get("X-Razorpay-Signature", "")):
                    self._send(401, b"bad signature")
                    return
                gateway, handler = "razorpay", svmp_handle_razorpay
                event_id = self.headers.get("X-Razorpay-Event-Id") or hashlib.sha256(raw).hexdigest()
            elif path == "/stripe/webhook":
                if not svmp_verify_stripe_signature(raw, self.headers.get("Stripe-Signature", "")):
                    self._send(401, b"bad signature")
                    return
                gateway, handler = "stripe", svmp_handle_stripe
                event_id = None
            else:
                self._send(404, b"not found")
                return
            event = json.loads(raw.decode())
            event_id = event_id or str(event.get("id") or hashlib.sha256(raw).hexdigest())
            if svmp_exec("SELECT 1 AS x FROM svm_webhook_events WHERE event_id=?", (event_id,), fetch="one"):
                self._send(200, b"duplicate")
                return
            result = handler(event)
            svmp_exec("INSERT OR IGNORE INTO svm_webhook_events(event_id,gateway,received_at) VALUES(?,?,?)", (event_id, gateway, svmp_now()))
            logger.info("%s webhook %s -> %s", gateway, event_id, result)
            self._send(200, result.encode()[:100])
        except Exception:
            logger.exception("Webhook processing failed")
            self._send(500, b"error")      # gateway will retry

    def log_message(self, *args):
        pass


def svmp_start_webhook_server():
    if _SVMP_WEBHOOK["server"]:
        return
    if not (RAZORPAY_WEBHOOK_SECRET or STRIPE_WEBHOOK_SECRET):
        logger.warning("Webhook server disabled: no RAZORPAY_WEBHOOK_SECRET / STRIPE_WEBHOOK_SECRET set")
        return
    try:
        srv = ThreadingHTTPServer((PAYMENT_WEBHOOK_HOST, PAYMENT_WEBHOOK_PORT), SvmpWebhookHandler)
        threading.Thread(target=srv.serve_forever, daemon=True, name="svmp-webhook").start()
        _SVMP_WEBHOOK["server"] = srv
        logger.info("SVM+ webhook server on %s:%s (/razorpay/webhook, /stripe/webhook, /health)", PAYMENT_WEBHOOK_HOST, PAYMENT_WEBHOOK_PORT)
    except Exception as e:
        logger.error("Could not start webhook server: %s", e)


# --------------------- provisioning wrapper / renewals ----------------------
async def svmp_notify_admins(embed):
    try:
        if SVMP_ADMIN_CHANNEL_ID:
            channel = bot.get_channel(SVMP_ADMIN_CHANNEL_ID) or await bot.fetch_channel(SVMP_ADMIN_CHANNEL_ID)
            await channel.send(embed=embed)
            return
        owner = await bot.fetch_user(int(MAIN_ADMIN_ID))
        await owner.send(embed=embed)
    except Exception as e:
        logger.warning("Could not notify admins: %s", e)


def svmp_bill(order, vps_id, status="paid", period_days=None):
    days = period_days or SVMP_RENEW_DAYS
    now = datetime.now()
    svmp_exec(
        "INSERT INTO svm_billing(user_id,vps_id,plan_slug,amount_paise,currency,status,period_days,starts_at,expires_at,provider,provider_ref,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (order["user_id"], vps_id, order["plan_slug"], order["amount_paise"], "INR", status, days, now.isoformat(),
         (now + timedelta(days=days)).isoformat(), order["provider"], order.get("provider_payment_id"), now.isoformat(), now.isoformat()))


async def svmp_apply_renewal(order):
    uid, container = str(order["user_id"]), order.get("vps_container")
    target = next((v for v in vps_data.get(uid, []) if v.get("container_name") == container), None)
    if not target:
        await svmp_notify_admins(create_error_embed("⚠️ Renewal Failed", f"Order `{order['id']}` is paid but VPS `{container}` was not found for <@{uid}>."))
        return
    base = datetime.now()
    try:
        current = datetime.fromisoformat(target.get("expiration_date") or "")
        if current > base:
            base = current
    except ValueError:
        pass
    target["expiration_date"] = (base + timedelta(days=SVMP_RENEW_DAYS)).isoformat()
    restarted = False
    history = target.get("suspension_history") or []
    if target.get("suspended") and history and str(history[-1].get("reason", "")).startswith("Auto-suspended due to VPS expiration"):
        try:                                       # only undo suspensions caused by expiry, never admin suspensions
            await safe_start_container(container, target.get("node_id", 1))
            target["suspended"], target["status"], restarted = False, "running", True
        except Exception as e:
            logger.warning("Renewal restart failed for %s: %s", container, e)
    save_vps_data_immediate()
    svmp_set_order_status(order["id"], "renewed")
    svmp_bill(order, target.get("id"))
    v112v_audit(uid, "vps_renewed", container, f"order={order['id']}")
    try:
        user = await bot.fetch_user(int(uid))
        await user.send(embed=create_success_embed("🔁 VPS Renewed", f"`{container}` now expires on **{target['expiration_date'][:10]}**." + ("\nThe VPS was started again." if restarted else "")))
    except Exception:
        pass


async def v112v_auto_provision_order(order_id):
    """Idempotent wrapper: renewals, provisioning, billing, auto-IP, failure alerts."""
    order = svmp_get_order(order_id)
    if not order or order["status"] != "paid":
        return
    if order.get("kind") == "renew":
        await svmp_apply_renewal(order)
        return
    if svmp_exec("SELECT 1 AS x FROM v112v_provision_locks WHERE order_id=?", (order["id"],), fetch="one"):
        return                                            # already running
    uid = str(order["user_id"])
    before = len(vps_data.get(uid, []))
    await _svmp_orig_provision(order_id)
    if len(vps_data.get(uid, [])) > before:
        svmp_set_order_status(order_id, "provisioned")
        vps = vps_data[uid][-1]
        try:
            row = svmp_exec("SELECT id FROM vps WHERE container_name=?", (vps["container_name"],), fetch="one")
            vps_db_id = row["id"] if row else None
            svmp_bill(svmp_get_order(order_id), vps_db_id, period_days=_svmp_env_int("PLAN_PERIOD_DAYS", 30, lo=1))
            if SVMP_IP_AUTO:
                payload = dict(vps, id=vps_db_id, _owner_id=uid)
                ok, detail, addr = await svmp_assign_ip(payload)
                if ok:
                    user = await bot.fetch_user(int(uid))
                    await user.send(embed=create_info_embed("🌐 Dedicated IP", f"Your VPS received `{addr}`.\n{detail}"))
                else:
                    logger.warning("Auto IP failed for %s: %s", vps["container_name"], detail)
        except Exception:
            logger.exception("Post-provision hook failed for order %s", order_id)
    else:
        await svmp_notify_admins(create_error_embed(
            "⚠️ Paid order not provisioned",
            f"Order `{order_id}` (<@{uid}>) is **paid** but no VPS was created.\nCheck logs, then run `{PREFIX}retry-payment {order_id}`."))


async def v112v_retry_failed_job(order_id):
    order = svmp_get_order(order_id)
    if not order:
        raise RuntimeError("Order not found")
    if order["status"] != "paid":
        raise RuntimeError(f"Order status is `{order['status']}`; only paid orders can be retried")
    await v112v_auto_provision_order(order_id)


# ------------------------------ user commands -------------------------------
for _n in ("plans", "buy", "payment-proof"):
    bot.remove_command(_n)


def svmp_gateway_help():
    gws = svmp_enabled_gateways()
    return ", ".join(f"`{g}`" for g in gws) if gws else "none configured"


@bot.command(name="plans")
async def svmp_plans(ctx):
    rows = svmp_exec("SELECT * FROM v112v_plans WHERE active=1 ORDER BY price_paise", fetch="all")
    embed = create_info_embed("🛒 VPS Plans", f"Pay with: {svmp_gateway_help()}")
    for p in rows:
        add_field(embed, f"🖥️ {p['name']}",
                  f"CPU **{p['cpu']}** • RAM **{p['ram']} GB** • Disk **{p['disk']} GB**\nPrice **₹{p['price_paise'] / 100:.2f}**\n`{PREFIX}buy {p['slug']} [gateway]`", True)
    add_field(embed, "🔐 Verification", "Gateway payments are verified automatically by signed webhook. UPI payments are approved by an admin after bank verification.", False)
    await ctx.send(embed=embed)


async def svmp_start_checkout(ctx, plan, gateway, kind="new", vps_container=None):
    gws = svmp_enabled_gateways()
    if not gws:
        await ctx.send(embed=create_error_embed("Payments Disabled", "No payment gateway is configured. Contact an admin.")); return
    gw = (gateway or SVMP_DEFAULT_GATEWAY or gws[0]).lower()
    if gw not in gws:
        await ctx.send(embed=create_error_embed("Gateway Unavailable", f"Available: {svmp_gateway_help()}")); return
    amount = int(plan["price_paise"])
    if amount <= 0:
        await ctx.send(embed=create_error_embed("Price Not Set", "This plan has no price configured.")); return
    pending = svmp_exec("SELECT COUNT(*) AS c FROM v112v_orders WHERE user_id=? AND status='created'", (str(ctx.author.id),), fetch="one")["c"]
    if pending >= SVMP_MAX_PENDING_ORDERS:
        await ctx.send(embed=create_error_embed("Too Many Open Orders", f"Pay or cancel an existing order first (`{PREFIX}myorders`).")); return
    order_id = svmp_create_order(ctx.author.id, plan["slug"], amount, gw, kind, vps_container)
    label = f"SVM {plan['name']} {'renewal' if kind == 'renew' else 'VPS'}"
    try:
        info = await asyncio.to_thread(svmp_checkout, gw, order_id, ctx.author.id, label, amount)
    except Exception as e:
        logger.error("Checkout creation failed (%s): %s", gw, e)
        svmp_set_order_status(order_id, "cancelled")
        await ctx.send(embed=create_error_embed("Payment Setup Failed", "The gateway rejected the request. An admin can see the details in the logs.")); return
    embed = create_warning_embed("💳 Complete Your Payment", f"Plan **{plan['name']}** • **₹{amount / 100:.2f}** • Order `#{order_id}` • via **{gw}**")
    if gw == "upi":
        add_field(embed, "📱 Pay by UPI", f"UPI ID: `{UPI_ID}`\nName: **{UPI_NAME}**\nAmount: **₹{amount / 100:.2f}**\nNote/remark: `{info['ref']}`", False)
        if UPI_QR_URL:
            add_field(embed, "QR", UPI_QR_URL, False)
        add_field(embed, "Next step", f"After paying run `{PREFIX}payment-proof {order_id}` with the screenshot attached. An admin will approve it.", False)
    else:
        add_field(embed, "🔗 Pay securely", info["url"], False)
        add_field(embed, "Automatic", f"The link expires in {SVMP_ORDER_TTL_MIN} minutes. Your VPS is created automatically after payment.", False)
    try:
        await ctx.author.send(embed=embed)
        await ctx.send(embed=create_success_embed("📩 Payment Details Sent", "Check your DMs."), delete_after=20)
    except discord.Forbidden:
        await ctx.send(embed=create_error_embed("DMs Closed", f"Enable DMs from server members and use `{PREFIX}order {order_id}` to view the payment link."))
    v112v_audit(ctx.author.id, "order_created", str(order_id), f"{kind}:{plan['slug']}:{gw}")


@bot.command(name="buy")
async def svmp_buy(ctx, plan_slug: str, gateway: str = None):
    plan = v112v_get_plan(plan_slug)
    if not plan:
        await ctx.send(embed=create_error_embed("Plan Not Found", f"Use `{PREFIX}plans`.")); return
    await svmp_start_checkout(ctx, plan, gateway)


@bot.command(name="renew")
async def svmp_renew(ctx, vps_num: int, gateway: str = None):
    vps_list = vps_data.get(str(ctx.author.id), [])
    if not 1 <= vps_num <= len(vps_list):
        await ctx.send(embed=create_error_embed("Invalid VPS", f"Choose 1-{len(vps_list)}. See `{PREFIX}myvps`.")); return
    vps = vps_list[vps_num - 1]
    plan = v112v_get_plan(vps.get("plan_slug") or "")
    if not plan:
        await ctx.send(embed=create_error_embed("No Plan Attached", "This VPS was not bought through a plan. Ask an admin to renew it.")); return
    await svmp_start_checkout(ctx, plan, gateway, "renew", vps["container_name"])


@bot.command(name="payment-proof")
async def svmp_payment_proof(ctx, order_id: int):
    order = svmp_get_order(order_id)
    if not order or order["user_id"] != str(ctx.author.id):
        await ctx.send(embed=create_error_embed("Order Not Found", "That order does not belong to you.")); return
    if not ctx.message.attachments:
        await ctx.send(embed=create_error_embed("Attachment Required", "Attach the payment screenshot to the same message.")); return
    att = ctx.message.attachments[0]
    if not (att.content_type or "").startswith("image/") or att.size > 8 * 1024 * 1024:
        await ctx.send(embed=create_error_embed("Invalid File", "Attach an image smaller than 8 MB.")); return
    data = await att.read()
    digest = hashlib.sha256(data).hexdigest()
    reused = svmp_exec("SELECT order_id FROM v112v_payment_proofs WHERE sha256=? AND order_id!=?", (digest, order_id), fetch="one")
    proof_dir = BASE_DIR / "payment_proofs"
    proof_dir.mkdir(parents=True, exist_ok=True)
    (proof_dir / f"{order_id}-{digest[:16]}.bin").write_bytes(data)
    svmp_exec("INSERT INTO v112v_payment_proofs(order_id,user_id,sha256,filename,ocr_text,status,created_at) VALUES(?,?,?,?,?,?,?)",
              (order_id, str(ctx.author.id), digest, att.filename, "", "received", svmp_now()))
    await ctx.send(embed=create_success_embed("📎 Proof Received", "Stored for the admin's review. A screenshot alone never activates an order."))
    if order["provider"] == "upi":
        warn = f"\n⚠️ Same screenshot was already used on order `{reused['order_id']}`." if reused else ""
        embed = create_warning_embed("🧾 UPI approval needed",
                                     f"Order `#{order_id}` • <@{order['user_id']}> • plan `{order['plan_slug']}` • ₹{order['amount_paise'] / 100:.2f}\n"
                                     f"Check your bank for remark `{order['gateway_ref']}`, then `{PREFIX}approve-order {order_id}` or `{PREFIX}reject-order {order_id} <reason>`.{warn}")
        await svmp_notify_admins(embed)


def svmp_order_line(r):
    return f"`#{r['id']}` • {r['plan_slug']} ({r.get('kind') or 'new'}) • ₹{r['amount_paise'] / 100:.2f} • {r['provider']} • **{r['status']}**"


@bot.command(name="myorders")
async def svmp_myorders(ctx):
    rows = svmp_exec("SELECT * FROM v112v_orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (str(ctx.author.id),), fetch="all")
    await ctx.send(embed=create_info_embed("🧾 Your Orders", "\n".join(svmp_order_line(r) for r in rows) or "No orders yet."))


@bot.command(name="order")
async def svmp_order_cmd(ctx, order_id: int):
    order = svmp_get_order(order_id)
    if not order or (order["user_id"] != str(ctx.author.id) and not svmp_is_admin_id(ctx.author.id)):
        await ctx.send(embed=create_error_embed("Order Not Found", "No such order on your account.")); return
    embed = create_info_embed(f"Order #{order_id}", svmp_order_line(order))
    if order["status"] == "created" and order.get("pay_url") and order["provider"] != "upi":
        add_field(embed, "Pay link", order["pay_url"], False)
    await ctx.send(embed=embed)


@bot.command(name="cancel-order")
async def svmp_cancel_order(ctx, order_id: int):
    n = svmp_exec("UPDATE v112v_orders SET status='cancelled' WHERE id=? AND user_id=? AND status='created'", (order_id, str(ctx.author.id)))
    await ctx.send(embed=create_success_embed("Cancelled", f"Order `#{order_id}` cancelled.") if n == 1
                   else create_error_embed("Cannot Cancel", "Only your own unpaid orders can be cancelled."))


# ------------------------------ admin commands ------------------------------
@bot.command(name="orders")
@is_admin()
async def svmp_orders_admin(ctx, status: str = None):
    rows = (svmp_exec("SELECT * FROM v112v_orders WHERE status=? ORDER BY id DESC LIMIT 20", (status,), fetch="all") if status
            else svmp_exec("SELECT * FROM v112v_orders ORDER BY id DESC LIMIT 20", fetch="all"))
    text = "\n".join(f"{svmp_order_line(r)} • <@{r['user_id']}>" for r in rows) or "No orders."
    await ctx.send(embed=create_info_embed("🧾 Orders", text[:4000]))


@bot.command(name="approve-order")
@is_admin()
async def svmp_approve(ctx, order_id: int):
    order = svmp_get_order(order_id)
    if not order or order["provider"] != "upi":
        await ctx.send(embed=create_error_embed("Not Found", "Only manual UPI orders can be approved by hand.")); return
    if svmp_mark_order_paid(order_id, f"upi-manual-{order_id}-{ctx.author.id}", f"approved_by={ctx.author.id}", "upi-admin", ("created", "expired")):
        v112v_audit(ctx.author.id, "upi_approved", str(order_id), "")
        await ctx.send(embed=create_success_embed("Approved", f"Order `#{order_id}` marked paid; provisioning started."))
    else:
        await ctx.send(embed=create_error_embed("Cannot Approve", f"Order is `{order['status']}`."))


@bot.command(name="reject-order")
@is_admin()
async def svmp_reject(ctx, order_id: int, *, reason: str = "not verified"):
    n = svmp_exec("UPDATE v112v_orders SET status='rejected' WHERE id=? AND provider='upi' AND status IN ('created','expired')", (order_id,))
    if n == 1:
        order = svmp_get_order(order_id)
        v112v_audit(ctx.author.id, "upi_rejected", str(order_id), reason[:200])
        try:
            user = await bot.fetch_user(int(order["user_id"]))
            await user.send(embed=create_error_embed("Payment Not Verified", f"Order `#{order_id}` was rejected: {reason[:300]}"))
        except Exception:
            pass
    await ctx.send(embed=create_success_embed("Rejected", f"Order `#{order_id}` rejected.") if n == 1
                   else create_error_embed("Cannot Reject", "Only open UPI orders can be rejected."))


@bot.command(name="retry-payment")
@is_admin()
async def svmp_retry(ctx, order_id: int):
    try:
        await v112v_retry_failed_job(order_id)
        await ctx.send(embed=create_success_embed("Retry Submitted", f"Order `#{order_id}` was re-processed."))
    except Exception as e:
        await ctx.send(embed=create_error_embed("Retry Failed", str(e)[:1500]))


@bot.command(name="gateways")
@is_admin()
async def svmp_gateways(ctx):
    base = (SVM_PUBLIC_URL or "https://YOUR-DOMAIN").rstrip("/")
    rows = [
        ("Razorpay", bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET), bool(RAZORPAY_WEBHOOK_SECRET), f"{base}/razorpay/webhook"),
        ("Stripe", bool(STRIPE_SECRET_KEY), bool(STRIPE_WEBHOOK_SECRET), f"{base}/stripe/webhook"),
        ("UPI (manual)", bool(UPI_ENABLED and UPI_ID), True, "no webhook — admin approves"),
    ]
    embed = create_info_embed("💳 Payment Gateways", f"Enabled: {svmp_gateway_help()} • default `{SVMP_DEFAULT_GATEWAY or 'first enabled'}`")
    for name, keys, hook, url in rows:
        add_field(embed, name, f"API keys: {'🟢' if keys else '🔴'} • webhook secret: {'🟢' if hook else '🔴'}\n`{url}`", False)
    add_field(embed, "Webhook server", f"{'🟢 running' if _SVMP_WEBHOOK['server'] else '🔴 stopped'} on `{PAYMENT_WEBHOOK_HOST}:{PAYMENT_WEBHOOK_PORT}`", False)
    await ctx.send(embed=embed)


@bot.command(name="billing")
@is_admin()
async def svmp_billing(ctx, query: str = "summary"):
    if query.lower() == "summary":
        rows = svmp_exec("SELECT substr(created_at,1,7) AS month, COUNT(*) AS n, SUM(amount_paise) AS total FROM svm_billing "
                         "WHERE status='paid' GROUP BY month ORDER BY month DESC LIMIT 6", fetch="all")
        text = "\n".join(f"`{r['month']}` • {r['n']} payments • **₹{(r['total'] or 0) / 100:,.2f}**" for r in rows) or "No billing records yet."
    else:
        uid = query.strip("<@!>")
        rows = svmp_exec("SELECT * FROM svm_billing WHERE user_id=? ORDER BY id DESC LIMIT 15", (uid,), fetch="all")
        text = "\n".join(f"#{r['id']} • {r['plan_slug'] or '-'} • ₹{r['amount_paise'] / 100:.2f} • {r['status']} • until `{(r['expires_at'] or '-')[:10]}`" for r in rows) or "No records."
    await ctx.send(embed=create_info_embed("💰 Billing", text[:4000]))


# --------------------- health / stats / info commands -----------------------
def svmp_provider_checks():
    checks = {"lxc": shutil.which("lxc") is not None, "docker": shutil.which("docker") is not None,
              "virsh": shutil.which("virsh") is not None, "kvm": os.path.exists("/dev/kvm")}
    now = svmp_now()
    for name, ok in checks.items():
        svmp_exec("INSERT OR REPLACE INTO svm_provider_health(provider,status,details,checked_at) VALUES(?,?,?,?)",
                  (name, "ready" if ok else "unavailable", "", now))
    return checks


@bot.command(name="svm-health")
@is_admin()
async def svmp_health(ctx):
    checks = svmp_provider_checks()
    orders = {r["status"]: r["c"] for r in svmp_exec("SELECT status, COUNT(*) AS c FROM v112v_orders GROUP BY status", fetch="all")}
    ip = svmp_exec("SELECT COALESCE(SUM(status='available'),0) AS free, COALESCE(SUM(status='allocated'),0) AS used FROM svm_ipam", fetch="one")
    fw = svmp_exec("SELECT COUNT(*) AS c FROM port_forwards", fetch="one")["c"]
    try:
        db_mb = os.path.getsize(DB_FILE) / 1048576
    except OSError:
        db_mb = 0
    embed = create_info_embed(f"🩺 SVM+ {SVMP_VERSION} Health", "\n".join(f"{'🟢' if ok else '🔴'} **{k.upper()}**" for k, ok in checks.items()))
    add_field(embed, "Webhook", "🟢 running" if _SVMP_WEBHOOK["server"] else "🔴 stopped", True)
    add_field(embed, "Gateways", svmp_gateway_help(), True)
    add_field(embed, "Orders", ", ".join(f"{k}:{v}" for k, v in orders.items()) or "none", True)
    add_field(embed, "IP pool", f"free {ip['free']} / used {ip['used']} • mode `{SVMP_IP_MODE}`", True)
    add_field(embed, "Port forwards", str(fw), True)
    add_field(embed, "Database", f"{db_mb:.1f} MB", True)
    await ctx.send(embed=embed)


@bot.command(name="svm-config")
@is_admin()
async def svmp_config(ctx):
    lines = [f"Public URL: `{SVM_PUBLIC_URL or 'not set'}`", f"Gateways: {svmp_gateway_help()}",
             f"Order TTL: `{SVMP_ORDER_TTL_MIN}m` • UPI TTL `{SVMP_UPI_TTL_MIN}m` • renew `{SVMP_RENEW_DAYS}d`",
             f"Port range: `{SVMP_PORT_LO}-{SVMP_PORT_HI}` • max/VPS `{SVMP_PORT_MAX_PER_VPS}` • custom `{SVMP_PORT_ALLOW_CUSTOM}`",
             f"IP mode: `{SVMP_IP_MODE}` • auto-assign `{SVMP_IP_AUTO}` • host iface `{SVMP_IP_HOST_IFACE or '-'}`"]
    await ctx.send(embed=create_info_embed("⚙️ SVM+ Configuration (no secrets)", "\n".join(lines)))


@bot.command(name="vmid")
@is_admin()
async def svmp_vmid(ctx, query: str):
    v = svmp_find_vps(query)
    if not v:
        await ctx.send(embed=create_error_embed("VPS Not Found", f"No VPS matched `{query}`.")); return
    await ctx.send(embed=create_info_embed("🆔 VPS VMID", f"`{v.get('container_name', '-')}` → VMID `{v.get('vmid') or v.get('id')}`"))


@bot.command(name="vpsstats")
async def svmp_vpsstats(ctx, query: str = None):
    if not query:
        await ctx.send(embed=create_error_embed("Usage", f"`{PREFIX}vpsstats <VPS id/name>`")); return
    v = svmp_find_vps(query)
    if not v or (str(v.get("_owner_id")) != str(ctx.author.id) and not svmp_is_admin_id(ctx.author.id)):
        await ctx.send(embed=create_error_embed("VPS Not Found", "No VPS of yours matched that id/name.")); return
    try:
        stats = await get_container_stats(v["container_name"], v.get("node_id", 1))
    except Exception as e:
        logger.warning("vpsstats: %s", e)
        stats = {"status": "unknown", "cpu": 0, "ram": {"pct": 0}, "disk": "Unknown"}
    ips = svmp_exec("SELECT address, bind_mode FROM svm_ipam WHERE container_name=?", (v["container_name"],), fetch="all")
    fwd = svmp_exec("SELECT vps_port, host_port, proto FROM port_forwards WHERE vps_container=? LIMIT 8", (v["container_name"],), fetch="all")
    embed = create_info_embed(f"📊 VPS {v.get('vmid') or v.get('id')}", f"**{v.get('container_name')}**")
    add_field(embed, "Status", str(stats.get("status", "unknown")), True)
    add_field(embed, "CPU", f"{float(stats.get('cpu', 0) or 0):.1f}%", True)
    add_field(embed, "RAM", f"{float((stats.get('ram') or {}).get('pct', 0) or 0):.1f}%", True)
    add_field(embed, "Disk", str(stats.get("disk", "Unknown")), True)
    add_field(embed, "IPs", "\n".join(f"`{i['address']}`" for i in ips) or "shared host IP", True)
    add_field(embed, "Forwards", "\n".join(f"{f['vps_port']}→{f['host_port']} ({f.get('proto') or 'both'})" for f in fwd) or "none", True)
    await ctx.send(embed=embed)


@bot.command(name="docker-status")
@is_admin()
async def svmp_docker_status(ctx):
    rc, out, err = await svmp_host("docker", "info", "--format", "{{.ServerVersion}}")
    await ctx.send(embed=create_success_embed("🐳 Docker Ready", f"Server `{out}`") if rc == 0
                   else create_error_embed("🐳 Docker Unavailable", (err or "docker not installed")[:300]))


@bot.command(name="svm-version")
async def svmp_version_cmd(ctx):
    await ctx.send(embed=create_info_embed(f"🚀 SVM+ {SVMP_VERSION}", "IP pools • port forwarding v2 • Razorpay / Stripe / UPI • renewals • billing\n**Made by AnkitCoder**"))


# ------------------------------ background tasks ----------------------------
@_svmp_tasks.loop(minutes=10)
async def svmp_maintenance():
    try:
        now = datetime.now()
        for r in svmp_exec("SELECT id, provider, created_at FROM v112v_orders WHERE status='created'", fetch="all"):
            ttl = SVMP_UPI_TTL_MIN if r["provider"] == "upi" else SVMP_ORDER_TTL_MIN
            try:
                if datetime.fromisoformat(r["created_at"]) < now - timedelta(minutes=ttl):
                    svmp_set_order_status(r["id"], "expired")
            except ValueError:
                continue
        svmp_provider_checks()
    except Exception:
        logger.exception("SVM+ maintenance failed")


async def svmp_on_ready():
    global SVMP_LOOP, _SVMP_STARTED
    SVMP_LOOP = asyncio.get_running_loop()
    if _SVMP_STARTED:
        return
    _SVMP_STARTED = True
    svmp_start_webhook_server()
    try:
        svmp_seed_pools()
    except Exception:
        logger.exception("IPAM pool seeding failed")
    if not svmp_maintenance.is_running():
        svmp_maintenance.start()
    if SVMP_IP_MODE == "nat":
        try:
            ok, bad = await svmp_ip_sync()
            logger.info("NAT mappings restored: %s ok / %s failed", ok, bad)
        except Exception:
            logger.exception("NAT restore failed")
    logger.info("SVM+ %s layer active • Made by AnkitCoder", SVMP_VERSION)


bot.add_listener(svmp_on_ready, "on_ready")
logger.info("SVM+ %s layer loaded", SVMP_VERSION)


# ============================================================================
# Run the bot (must stay LAST: bot.run() blocks, everything above is loaded first)
# ============================================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == 'your_discord_bot_token_here':
        logger.error("[ERROR] No valid Discord token found!")
        logger.error("Please update your .env file with a valid Discord bot token.")
        logger.error("DISCORD_TOKEN in .env is currently set to: " + str(DISCORD_TOKEN))
        exit(1)
    try:
        bot.run(DISCORD_TOKEN)
    except discord.errors.LoginFailure as e:
        logger.error(f"[ERROR] Failed to login with Discord token: {e}")
        logger.error("Please check your DISCORD_TOKEN in the .env file.")
        exit(1)
