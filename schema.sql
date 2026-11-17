-- TSIS 1: PhoneBook - extended schema
-- Safe to run on a fresh DB and on a DB left over from Practice 7-8 (idempotent).

-- 1. Groups -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS groups (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL
);

INSERT INTO groups (name)
VALUES ('Family'), ('Work'), ('Friend'), ('Other')
ON CONFLICT (name) DO NOTHING;

-- 2. Contacts (created only if Practice 7 table is missing) -------------------
CREATE TABLE IF NOT EXISTS contacts (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL
);

-- Practice 7 may have called the column "username" - rename it to "name"
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'contacts' AND column_name = 'username')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'contacts' AND column_name = 'name') THEN
        ALTER TABLE contacts RENAME COLUMN username TO name;
    END IF;
END $$;

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS email      VARCHAR(100),
    ADD COLUMN IF NOT EXISTS birthday   DATE,
    ADD COLUMN IF NOT EXISTS group_id   INTEGER REFERENCES groups(id),
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW();

-- 3. Phones (1-to-many) -------------------------------------------------------
CREATE TABLE IF NOT EXISTS phones (
    id         SERIAL PRIMARY KEY,
    contact_id INTEGER     REFERENCES contacts(id) ON DELETE CASCADE,
    phone      VARCHAR(20) NOT NULL,
    type       VARCHAR(10) CHECK (type IN ('home', 'work', 'mobile')),
    UNIQUE (contact_id, phone)
);

-- Migrate the old single "phone" column from Practice 7 (if it still exists)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'contacts' AND column_name = 'phone') THEN
        INSERT INTO phones (contact_id, phone, type)
        SELECT id, phone, 'mobile' FROM contacts WHERE phone IS NOT NULL
        ON CONFLICT (contact_id, phone) DO NOTHING;
        ALTER TABLE contacts DROP COLUMN phone;
    END IF;
END $$;

-- Default group for contacts without one
UPDATE contacts SET group_id = (SELECT id FROM groups WHERE name = 'Other')
WHERE group_id IS NULL;

-- 4. Indexes ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts (email);
CREATE INDEX IF NOT EXISTS idx_contacts_group ON contacts (group_id);
CREATE INDEX IF NOT EXISTS idx_phones_contact ON phones (contact_id);

-- 5. Flat view used by the console app and the DB functions ------------------
CREATE OR REPLACE VIEW contacts_full AS
SELECT c.id,
       c.name,
       c.email,
       c.birthday,
       g.name AS group_name,
       COALESCE(string_agg(p.phone || ' (' || p.type || ')', ', ' ORDER BY p.id), '') AS phones,
       c.created_at
FROM contacts c
LEFT JOIN groups g ON g.id = c.group_id
LEFT JOIN phones p ON p.contact_id = c.id
GROUP BY c.id, g.name;
