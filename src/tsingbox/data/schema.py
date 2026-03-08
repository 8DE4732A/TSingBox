SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    last_update TEXT
);

CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sub_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    protocol TEXT NOT NULL,
    config_json TEXT NOT NULL,
    ping_delay INTEGER,
    FOREIGN KEY(sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS warp_accounts (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    private_key TEXT NOT NULL,
    local_address_v4 TEXT NOT NULL,
    local_address_v6 TEXT NOT NULL,
    reserved TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    selected_node_id INTEGER,
    routing_mode TEXT NOT NULL DEFAULT 'rule',
    dns_leak_protection INTEGER NOT NULL DEFAULT 0,
    warp_enabled INTEGER NOT NULL DEFAULT 0,
    singbox_binary_path TEXT
);
"""
