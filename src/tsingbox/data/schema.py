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
    reserved TEXT NOT NULL,
    peer_public_key TEXT,
    peer_endpoint_host TEXT,
    peer_endpoint_port INTEGER,
    peer_allowed_ips TEXT
);

CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    selected_node_id INTEGER,
    routing_mode TEXT NOT NULL DEFAULT 'global',
    dns_leak_protection INTEGER NOT NULL DEFAULT 0,
    warp_enabled INTEGER NOT NULL DEFAULT 0,
    singbox_binary_path TEXT,
    singbox_active_version TEXT,
    active_routing_rule_set_id INTEGER,
    rule_set_url_proxy_prefix TEXT
);

CREATE TABLE IF NOT EXISTS routing_rule_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    is_default INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS routing_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_set_id INTEGER NOT NULL,
    match_type TEXT NOT NULL,
    match_value TEXT NOT NULL,
    action TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(rule_set_id) REFERENCES routing_rule_sets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rule_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    tag TEXT NOT NULL UNIQUE,
    format TEXT NOT NULL DEFAULT 'binary',
    url TEXT NOT NULL,
    download_detour TEXT,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    auto_enabled INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
"""
