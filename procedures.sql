-- TSIS 1: PhoneBook - new server-side objects (PL/pgSQL)
-- Run AFTER schema.sql.  Practice 8 procedures are not duplicated here.

-- 1. add_phone: add a new phone number to an existing contact -----------------
CREATE OR REPLACE PROCEDURE add_phone(
    p_contact_name VARCHAR,
    p_phone        VARCHAR,
    p_type         VARCHAR
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_contact_id INTEGER;
BEGIN
    IF p_type IS NULL OR p_type NOT IN ('home', 'work', 'mobile') THEN
        RAISE EXCEPTION 'Invalid phone type "%": use home, work or mobile', p_type;
    END IF;

    SELECT id INTO v_contact_id FROM contacts WHERE name = p_contact_name;
    IF v_contact_id IS NULL THEN
        RAISE EXCEPTION 'Contact "%" not found', p_contact_name;
    END IF;

    INSERT INTO phones (contact_id, phone, type)
    VALUES (v_contact_id, p_phone, p_type)
    ON CONFLICT (contact_id, phone) DO UPDATE SET type = EXCLUDED.type;
END;
$$;

-- 2. move_to_group: move contact to a group, create the group if missing -------
CREATE OR REPLACE PROCEDURE move_to_group(
    p_contact_name VARCHAR,
    p_group_name   VARCHAR
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_group_id   INTEGER;
    v_contact_id INTEGER;
BEGIN
    SELECT id INTO v_contact_id FROM contacts WHERE name = p_contact_name;
    IF v_contact_id IS NULL THEN
        RAISE EXCEPTION 'Contact "%" not found', p_contact_name;
    END IF;

    INSERT INTO groups (name) VALUES (p_group_name)
    ON CONFLICT (name) DO NOTHING;

    SELECT id INTO v_group_id FROM groups WHERE name = p_group_name;

    UPDATE contacts SET group_id = v_group_id WHERE id = v_contact_id;
END;
$$;

-- 3. search_contacts: pattern search over name, email, group, birthday and ALL phones
CREATE OR REPLACE FUNCTION search_contacts(p_query TEXT)
RETURNS SETOF contacts_full
LANGUAGE sql
STABLE
AS $$
    SELECT cf.*
    FROM contacts_full cf
    WHERE cf.name                ILIKE '%' || p_query || '%'
       OR COALESCE(cf.email, '') ILIKE '%' || p_query || '%'
       OR COALESCE(cf.group_name, '') ILIKE '%' || p_query || '%'
       OR COALESCE(cf.birthday::TEXT, '') ILIKE '%' || p_query || '%'
       OR EXISTS (SELECT 1 FROM phones p
                  WHERE p.contact_id = cf.id
                    AND p.phone ILIKE '%' || p_query || '%')
    ORDER BY cf.name;
$$;
