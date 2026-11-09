<?php
/**
 * sync.php — End-to-End Encrypted Note Synchronization API for Asd.
 *
 * Architecture:
 * - Zero-knowledge: The server NEVER receives or stores plaintext.
 *   Only encrypted ciphertext strings (enc_title, enc_content) are stored.
 * - Authenticated via Bearer token (API Key) or X-API-Key header.
 * - Stores notes in a lightweight SQLite database.
 * - Two-way sync: Clients upload modified notes since their last_sync,
 *   server saves changes (last updated_at wins), and server returns remote changes.
 * - Synchronizes top favorite notes (favorite_pos: 0..9, or -1 for unpinned).
 * - Synchronizes zero-knowledge vault cryptographic metadata (salt, verify_token)
 *   so new devices can connect and decrypt without manual database file transfers.
 */

declare(strict_types=1);

header('Content-Type: application/json; charset=UTF-8');

// ==============================================================================
// 1. CONFIGURATION
// ==============================================================================

// Set your private API sync key here (or configure via environment variable ASD_SYNC_KEY)
define('ASD_SYNC_API_KEY', getenv('ASD_SYNC_KEY') ?: 'CHANGE_THIS_TO_YOUR_SECURE_RANDOM_KEY');

// Path to server SQLite storage file (stored safely outside web root or restricted)
define('ASD_DB_PATH', __DIR__ . '/asd_sync.db');

// ==============================================================================
// 2. AUTHENTICATION CHECK
// ==============================================================================

// Check X-API-Key header first (never stripped by Apache/LiteSpeed/Nginx)
$providedKey = $_SERVER['HTTP_X_API_KEY'] ?? '';

// Fallback to Authorization / Bearer header
if (empty($providedKey)) {
    $authHeader = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if (empty($authHeader) && function_exists('apache_request_headers')) {
        $headers = apache_request_headers();
        $authHeader = $headers['Authorization'] ?? $headers['authorization'] ?? $headers['X-API-Key'] ?? $headers['x-api-key'] ?? '';
    }

    if (preg_match('/Bearer\s+(.+)$/i', $authHeader, $matches)) {
        $providedKey = trim($matches[1]);
    } elseif (!empty($authHeader) && !str_starts_with(strtolower($authHeader), 'bearer ')) {
        $providedKey = trim($authHeader);
    }
}

if (empty($providedKey) || !hash_equals(ASD_SYNC_API_KEY, $providedKey)) {
    http_response_code(401);
    echo json_encode([
        'success' => false,
        'error' => 'Unauthorized: Invalid or missing API Key.'
    ], JSON_UNESCAPED_UNICODE);
    exit;
}

// ==============================================================================
// 3. DATABASE INITIALIZATION
// ==============================================================================

try {
    $db = new PDO('sqlite:' . ASD_DB_PATH, null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_TIMEOUT => 10
    ]);
    
    // Set strict file permissions on database file
    if (file_exists(ASD_DB_PATH)) {
        @chmod(ASD_DB_PATH, 0600);
    }

    $db->exec("PRAGMA journal_mode = WAL;");
    $db->exec("PRAGMA synchronous = NORMAL;");
    $db->exec("
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notes (
            uuid TEXT PRIMARY KEY,
            enc_title TEXT NOT NULL,
            enc_content TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            favorite_pos INTEGER NOT NULL DEFAULT -1,
            server_updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_notes_server_upd ON notes(server_updated_at);
        CREATE INDEX IF NOT EXISTS idx_notes_upd ON notes(updated_at);
    ");

    // Migration: ensure favorite_pos exists if table was created in an older version
    $cols = $db->query("PRAGMA table_info(notes)")->fetchAll();
    $colNames = array_column($cols, 'name');
    if (!in_array('favorite_pos', $colNames, true)) {
        $db->exec("ALTER TABLE notes ADD COLUMN favorite_pos INTEGER NOT NULL DEFAULT -1;");
    }
} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => 'Database error: ' . $e->getMessage()]);
    exit;
}

function get_meta_value(PDO $db, string $key, string $default = ''): string {
    $stmt = $db->prepare("SELECT value FROM meta WHERE key = ?");
    $stmt->execute([$key]);
    $row = $stmt->fetch();
    return $row ? (string)$row['value'] : $default;
}

function set_meta_value(PDO $db, string $key, string $value): void {
    $stmt = $db->prepare("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value");
    $stmt->execute([$key, $value]);
}

// ==============================================================================
// 4. REQUEST ROUTING
// ==============================================================================

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';

if ($method === 'GET') {
    // Health / Ping / Vault info check
    $countStmt = $db->query("SELECT COUNT(*) AS total, SUM(CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END) AS active, SUM(CASE WHEN is_deleted = 0 AND favorite_pos >= 0 THEN 1 ELSE 0 END) AS favorites FROM notes");
    $stats = $countStmt->fetch();

    $vaultSalt = get_meta_value($db, 'vault_salt', '');
    $vaultVerifyToken = get_meta_value($db, 'vault_verify_token', '');

    echo json_encode([
        'success' => true,
        'message' => 'Asd Encrypted Sync API is running.',
        'stats' => [
            'total_records' => (int)($stats['total'] ?? 0),
            'active_notes' => (int)($stats['active'] ?? 0),
            'favorite_notes' => (int)($stats['favorites'] ?? 0),
        ],
        'vault' => [
            'has_vault' => (!empty($vaultSalt) && !empty($vaultVerifyToken)),
            'salt' => $vaultSalt,
            'verify_token' => $vaultVerifyToken,
        ],
        'server_time' => gmdate('Y-m-d H:i:s')
    ]);
    exit;
}

if ($method !== 'POST') {
    http_response_code(405);
    echo json_encode(['success' => false, 'error' => 'Method not allowed. Use POST to sync.']);
    exit;
}

// ==============================================================================
// 5. PROCESS SYNC PAYLOAD
// ==============================================================================

$rawBody = file_get_contents('php://input');
$payload = json_decode($rawBody, true);

if (!is_array($payload)) {
    http_response_code(400);
    echo json_encode(['success' => false, 'error' => 'Invalid JSON payload.']);
    exit;
}

// Check and register / update vault cryptographic credentials
$incomingSalt = trim((string)($payload['vault_salt'] ?? ''));
$incomingVerify = trim((string)($payload['vault_verify_token'] ?? ''));
$serverSalt = get_meta_value($db, 'vault_salt', '');
$serverVerify = get_meta_value($db, 'vault_verify_token', '');

if (!empty($incomingSalt) && !empty($incomingVerify)) {
    if (empty($serverSalt)) {
        // First sync registers this cloud vault
        set_meta_value($db, 'vault_salt', $incomingSalt);
        set_meta_value($db, 'vault_verify_token', $incomingVerify);
        $serverSalt = $incomingSalt;
        $serverVerify = $incomingVerify;
    }
}

$lastSync = trim((string)($payload['last_sync'] ?? ''));
$clientNotes = is_array($payload['notes'] ?? null) ? $payload['notes'] : [];

$appliedCount = 0;
$nowUtc = gmdate('Y-m-d H:i:s');

$db->beginTransaction();
try {
    $selectStmt = $db->prepare("SELECT updated_at, is_deleted FROM notes WHERE uuid = ?");
    $upsertStmt = $db->prepare("
        INSERT INTO notes (uuid, enc_title, enc_content, updated_at, is_deleted, favorite_pos, server_updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(uuid) DO UPDATE SET
            enc_title = excluded.enc_title,
            enc_content = excluded.enc_content,
            updated_at = excluded.updated_at,
            is_deleted = excluded.is_deleted,
            favorite_pos = excluded.favorite_pos,
            server_updated_at = CURRENT_TIMESTAMP
    ");

    // 1. Process client incoming changes
    foreach ($clientNotes as $note) {
        $uuid = trim((string)($note['uuid'] ?? ''));
        $encTitle = (string)($note['enc_title'] ?? '');
        $encContent = (string)($note['enc_content'] ?? '');
        $updatedAt = trim((string)($note['updated_at'] ?? ''));
        $isDeleted = !empty($note['is_deleted']) ? 1 : 0;
        $favPos = isset($note['favorite_pos']) ? (int)$note['favorite_pos'] : -1;

        if (empty($uuid) || empty($updatedAt)) {
            continue;
        }

        // Check existing record on server: "last updated_at wins"
        $selectStmt->execute([$uuid]);
        $existing = $selectStmt->fetch();

        if ($existing) {
            // If server's note is newer than client's note, do not overwrite server
            if (strcmp($existing['updated_at'], $updatedAt) > 0) {
                continue;
            }
        }

        $upsertStmt->execute([$uuid, $encTitle, $encContent, $updatedAt, $isDeleted, $favPos]);
        $appliedCount++;
    }

    $db->commit();
} catch (Exception $e) {
    $db->rollBack();
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => 'Sync commit failed: ' . $e->getMessage()]);
    exit;
}

// 2. Fetch remote notes modified since client's last_sync
$remoteNotes = [];
try {
    if (!empty($lastSync)) {
        // Fetch notes where server_updated_at > lastSync OR updated_at > lastSync
        $queryStmt = $db->prepare("
            SELECT uuid, enc_title, enc_content, updated_at, is_deleted, favorite_pos
            FROM notes
            WHERE server_updated_at > ? OR updated_at > ?
            ORDER BY updated_at ASC
        ");
        $queryStmt->execute([$lastSync, $lastSync]);
        $remoteNotes = $queryStmt->fetchAll();
    } else {
        // Full initial sync
        $queryStmt = $db->query("
            SELECT uuid, enc_title, enc_content, updated_at, is_deleted, favorite_pos
            FROM notes
            ORDER BY updated_at ASC
        ");
        $remoteNotes = $queryStmt->fetchAll();
    }
} catch (Exception $e) {
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => 'Remote query failed: ' . $e->getMessage()]);
    exit;
}

// Return response to client
echo json_encode([
    'success' => true,
    'applied_count' => $appliedCount,
    'remote_notes' => $remoteNotes,
    'sync_timestamp' => $nowUtc,
    'vault' => [
        'has_vault' => (!empty($serverSalt) && !empty($serverVerify)),
        'salt' => $serverSalt,
        'verify_token' => $serverVerify,
    ]
], JSON_UNESCAPED_UNICODE);
