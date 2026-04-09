"""
Mail type classification migration script
Add mail_type and original_recipient fields, batch classify mail types
"""

import sys
import re
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

from Sills.base import get_db_connection


def migrate_add_fields():
    """Add new fields"""
    with get_db_connection() as conn:
        # Add mail_type field
        try:
            conn.execute("""
                ALTER TABLE uni_mail
                ADD COLUMN IF NOT EXISTS mail_type INTEGER DEFAULT 0
            """)
            print("[OK] mail_type field added")
        except Exception as e:
            print(f"mail_type field exists or error: {e}")

        # Add original_recipient field
        try:
            conn.execute("""
                ALTER TABLE uni_mail
                ADD COLUMN IF NOT EXISTS original_recipient TEXT
            """)
            print("[OK] original_recipient field added")
        except Exception as e:
            print(f"original_recipient field exists or error: {e}")

        # Add index
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mail_type ON uni_mail(mail_type)")
            print("[OK] idx_mail_type index added")
        except Exception as e:
            print(f"Index exists or error: {e}")

        conn.commit()


def get_mail_type_keywords():
    """Get mail type recognition keywords"""
    return {
        # Read receipt (mail_type = 1)
        'read': [
            'Read', '已读', 'Gelesen', 'Letto', 'Lu', 'Lesebest'
        ],
        # Unread receipt (mail_type = 2)
        'unread': [
            'Not read', 'Nicht gelesen', 'Non letto', '未读', 'Non lu'
        ],
        # Bounced mail (mail_type = 3)
        'bounced': [
            '系统退信', 'Undeliverable', 'Delivery failure', 'Delivery Status',
            'Return Notice', 'Fehlgeschlagen', 'SPAM', 'Returned mail',
            '配信不能', 'Returne'
        ]
    }


def classify_mail_type():
    """Batch classify mail types"""
    keywords = get_mail_type_keywords()

    with get_db_connection() as conn:
        total_updated = 0

        # Mark read receipts
        print("\n[Read receipts]")
        for kw in keywords['read']:
            result = conn.execute("""
                UPDATE uni_mail
                SET mail_type = 1
                WHERE subject LIKE %s AND mail_type = 0
            """, (f'%{kw}%',))
            if result.rowcount > 0:
                print(f"  '{kw}': {result.rowcount}")
                total_updated += result.rowcount

        # Mark unread receipts
        print("\n[Unread receipts]")
        for kw in keywords['unread']:
            result = conn.execute("""
                UPDATE uni_mail
                SET mail_type = 2
                WHERE subject LIKE %s AND mail_type = 0
            """, (f'%{kw}%',))
            if result.rowcount > 0:
                print(f"  '{kw}': {result.rowcount}")
                total_updated += result.rowcount

        # Mark bounced mails
        print("\n[Bounced mails]")
        for kw in keywords['bounced']:
            result = conn.execute("""
                UPDATE uni_mail
                SET mail_type = 3
                WHERE subject LIKE %s AND mail_type = 0
            """, (f'%{kw}%',))
            if result.rowcount > 0:
                print(f"  '{kw}': {result.rowcount}")
                total_updated += result.rowcount

        conn.commit()
        print(f"\nTotal classified: {total_updated}")


def extract_original_recipient(content):
    """
    Extract original recipient from bounce content

    Args:
        content: mail content

    Returns:
        Original recipient email address
    """
    if not content:
        return None

    patterns = [
        # Standard format with colon
        r'Original-Recipient:\s*[rfc822;]*\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'Final-Recipient:\s*[rfc822;]*\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # Chinese format - colon or space
        r'收件人[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'收件人\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'原始收件人[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # English format - colon or space
        r'To[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'To\s+([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # Korean format
        r'받는 사람[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        r'수신자[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # Delivery failed format
        r'Delivery failed:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # Address format
        r'Address[：:]\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        # No such user format
        r'No such user\s*[<]?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})[>]?',
    ]

    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def extract_recipients_for_bounced():
    """Extract original recipients for bounced mails"""
    with get_db_connection() as conn:
        # Get all bounced mails without recipient extracted
        rows = conn.execute("""
            SELECT id, content
            FROM uni_mail
            WHERE mail_type = 3 AND original_recipient IS NULL
            LIMIT 5000
        """).fetchall()

        print(f"\nBounced mails to process: {len(rows)}")

        updated = 0
        for row in rows:
            recipient = extract_original_recipient(row['content'])
            if recipient:
                conn.execute("""
                    UPDATE uni_mail
                    SET original_recipient = %s
                    WHERE id = %s
                """, (recipient, row['id']))
                updated += 1
                if updated % 100 == 0:
                    print(f"  Extracted: {updated}")

        conn.commit()
        print(f"[OK] Original recipients extracted: {updated}")


def show_statistics():
    """Show classification statistics"""
    with get_db_connection() as conn:
        stats = conn.execute("""
            SELECT
                mail_type,
                CASE mail_type
                    WHEN 0 THEN 'Normal'
                    WHEN 1 THEN 'Read receipt'
                    WHEN 2 THEN 'Unread receipt'
                    WHEN 3 THEN 'Bounced'
                    WHEN 4 THEN 'Other system'
                END as type_name,
                COUNT(*) as count
            FROM uni_mail
            GROUP BY mail_type
            ORDER BY mail_type
        """).fetchall()

        print("\nMail type statistics:")
        print("-" * 40)
        for row in stats:
            print(f"{row['type_name']}: {row['count']}")

        # Bounced recipient extraction stats
        bounced_with_recipient = conn.execute("""
            SELECT COUNT(*) as count
            FROM uni_mail
            WHERE mail_type = 3 AND original_recipient IS NOT NULL
        """).fetchone()

        total_bounced = conn.execute("""
            SELECT COUNT(*) as count
            FROM uni_mail WHERE mail_type = 3
        """).fetchone()

        print("-" * 40)
        print(f"Bounced with recipient extracted: {bounced_with_recipient['count']}/{total_bounced['count']}")


def main():
    print("=" * 60)
    print("Mail Type Classification Migration")
    print("=" * 60)

    # Step 1: Add fields
    print("\n[Step 1] Adding fields...")
    migrate_add_fields()

    # Step 2: Classify
    print("\n[Step 2] Classifying mail types...")
    classify_mail_type()

    # Step 3: Extract recipients
    print("\n[Step 3] Extracting original recipients...")
    extract_recipients_for_bounced()

    # Step 4: Show statistics
    show_statistics()

    print("\n" + "=" * 60)
    print("Migration complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()