"""Private local storage. Never commit its database or publish it with GTFS."""
import json
import sqlite3


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS notices (
          key_id TEXT, notice_id TEXT, revision INTEGER NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(key_id, notice_id));
        CREATE TABLE IF NOT EXISTS subscriptions (
          device_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, feed_id TEXT NOT NULL,
          stop_id TEXT NOT NULL, route_ids TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS outbox (
          owner_id TEXT, event_id TEXT, device_id TEXT, payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(owner_id, event_id, device_id));
        ''')

    def accept(self, verified_notice):
        """Caller must verify first. Atomic monotonic revision update retains cancellations."""
        p = verified_notice
        with self.db:
            cur = self.db.execute('''INSERT INTO notices VALUES (?, ?, ?, ?)
              ON CONFLICT(key_id, notice_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload
              WHERE excluded.revision > notices.revision''',
              (p['key_id'], p['id'], p['revision'], json.dumps(p)))
        return cur.rowcount == 1

    def current(self, groups, now):
        values = [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM notices')]
        return [p for p in values if p['group'] in groups and p['action'] != 'cancel'
                and p['starts_at'] <= now < p['expires_at']]

    def subscribe(self, owner_id, device_id, feed_id, stop_id, route_ids):
        """Internal call only; public API must authenticate ownership before invoking."""
        with self.db:
            row = self.db.execute('SELECT owner_id FROM subscriptions WHERE device_id=?', (device_id,)).fetchone()
            if row and row[0] != owner_id:
                raise PermissionError('device belongs to another owner')
            self.db.execute('INSERT OR REPLACE INTO subscriptions VALUES (?, ?, ?, ?, ?)',
                            (device_id, owner_id, feed_id, stop_id, json.dumps(route_ids)))

    def queue_change(self, event_id, feed_id, change):
        """Durable owner inbox/outbox; sending requires a separately configured worker."""
        with self.db:
            for device_id, owner_id in self.db.execute(
                'SELECT device_id, owner_id FROM subscriptions WHERE feed_id=? AND stop_id=?',
                (feed_id, change['stop_id'])).fetchall():
                self.db.execute('INSERT OR IGNORE INTO outbox(owner_id,event_id,device_id,payload) VALUES (?,?,?,?)',
                                (owner_id, event_id, device_id, json.dumps(change)))

    def inbox(self, authenticated_owner_id):
        return [{'event_id': row[0], 'device_id': row[1], 'payload': json.loads(row[2]), 'state': row[3]}
                for row in self.db.execute('SELECT event_id,device_id,payload,state FROM outbox WHERE owner_id=?',
                                          (authenticated_owner_id,))]
