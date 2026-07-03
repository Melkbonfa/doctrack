import sqlite3
conn = sqlite3.connect('doctrack.db')
c = conn.cursor()

# Add payload_json to audit_logs
try:
    c.execute('ALTER TABLE audit_logs ADD COLUMN payload_json TEXT')
    print('OK: payload_json added to audit_logs')
except Exception as e:
    print(f'SKIP: {e}')

# Create responsaveis table if missing
try:
    c.execute('''CREATE TABLE IF NOT EXISTS responsaveis (
        id INTEGER PRIMARY KEY,
        documento_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role VARCHAR(40) NOT NULL,
        atribuido_em DATETIME,
        atribuido_por_id INTEGER,
        FOREIGN KEY(documento_id) REFERENCES documentos(id),
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(atribuido_por_id) REFERENCES users(id),
        UNIQUE(documento_id, user_id, role)
    )''')
    print('OK: responsaveis table ready')
except Exception as e:
    print(f'SKIP: {e}')

conn.commit()
conn.close()
print('Migration complete!')
