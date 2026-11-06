"""Synthetic-only integration suite. No environment database URL is used.
Start a disposable Postgres on 127.0.0.1:55489, then run unittest discovery.
"""
import concurrent.futures
import getpass
import uuid
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DSN = f'host=127.0.0.1 port=55489 dbname=postgres user={getpass.getuser()} sslmode=disable connect_timeout=3'
SCHEMA = 'careconnect_phase2_synthetic_' + uuid.uuid4().hex[:10]
SQL = (ROOT / 'phase2_schema.sql').read_text()

# No credentials or AI/network calls are used by this suite.
chat = types.ModuleType('chatbot')
for name in ('ask_careconnect', 'extract_matching_preferences', 'generate_onboarding_reply',
             'interpret_confirmation', 'safe_adapt_message', 'remember_matching_language',
             'get_matching_language_example'):
    setattr(chat, name, Mock(return_value=None))
chat.MODEL = 'synthetic-model'
chat.client = Mock()
sys.modules['chatbot'] = chat


def connect():
    return psycopg2.connect(DSN, options=f'-c search_path={SCHEMA} -c statement_timeout=4000 -c lock_timeout=3000 -c timezone=UTC')


import database_postgres
# Patch before importing the compatibility backend, which captures this function.
database_postgres.get_connection = connect
import database
import phase2_analytics as analytics
analytics.get_connection = connect
import handlers
import profile_suggestions as suggestions
import app as web
web.get_connection = connect


class Phase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT inet_server_addr()::text, inet_server_port()')
                address, port = cur.fetchone()
                assert address.split('/')[0] == '127.0.0.1' and port == 55489
                cur.execute('SHOW data_directory')
                assert cur.fetchone()[0] == '/tmp/careconnect-phase2-audit-pg', 'Refusing to use an unverified database cluster'
                cur.execute(f'CREATE SCHEMA {SCHEMA}')
        database.create_tables()
        cls.migrate()

    @classmethod
    def tearDownClass(cls):
        with psycopg2.connect(DSN) as conn:
            with conn.cursor() as cur:
                cur.execute(f'DROP SCHEMA {SCHEMA} CASCADE')

    @staticmethod
    def migrate():
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(SQL)
        finally:
            conn.close()

    def setUp(self):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute('TRUNCATE users CASCADE')
                cur.execute('TRUNCATE whatsapp_receipts, conversation_messages')
        database.create_user('synthetic-a')
        database.create_user('synthetic-b')
        for name in ('ask_careconnect', 'get_matching_language_example', 'remember_matching_language'):
            getattr(chat, name).reset_mock()
        chat.get_matching_language_example.return_value = None
        chat.ask_careconnect.return_value = 'Synthetic AI reply'
        chat.client.reset_mock()

    def rows(self, sql, params=()):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []

    def pending(self):
        analytics.grant_profiling_consent('synthetic-a')
        return analytics.propose_profile_field('synthetic-a', 'support_needs', 'Peer support')

    def test_validation_all_direct_writes(self):
        from profile_validation import is_safe_profile_value
        unsafe = ['Call +65 9123 4567', 'a@example.com', 'S1234567D',
                  '12 Orchard Road', '#12-123', 'Postal code 123456',
                  '９１２３４５６７', '9123\u200b4567', 'https://example.com',
                  'My name is Alice', 'contact 123 456 7890', '', 'x' * 301]
        for value in unsafe:
            with self.subTest(value=value):
                self.assertFalse(is_safe_profile_value(value))
                with self.assertRaises(ValueError):
                    analytics.propose_profile_field('synthetic-a', 'support_needs', value)
        sid = self.pending()
        for value in unsafe:
            with self.assertRaises(ValueError):
                analytics.review_profile_suggestion('synthetic-a', sid, True, value)
            with self.assertRaises(ValueError):
                analytics.save_pending_profile_edit('synthetic-a', sid, value)
        self.rows('UPDATE caregiver_profile_suggestions SET proposed_value=%s WHERE id=%s', ('Call 91234567',sid))
        with self.assertRaises(ValueError):
            analytics.review_profile_suggestion('synthetic-a', sid, True)
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])

    def test_accept_edit_ownership_and_replay(self):
        sid = self.pending()
        with self.assertRaises(PermissionError):
            analytics.review_profile_suggestion('synthetic-b', sid, True)
        analytics.save_pending_profile_edit('synthetic-a', sid, 'Evening peer support')
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        analytics.confirm_pending_profile_edit('synthetic-a', sid)
        self.assertEqual(self.rows('SELECT field_value FROM caregiver_profile_fields'), [('Evening peer support',)])
        with self.assertRaises(PermissionError):
            analytics.confirm_pending_profile_edit('synthetic-a', sid)
        analytics.withdraw_profiling_consent('synthetic-a')
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_suggestions'), [])

    def test_decline_erases_previous_grant(self):
        sid = self.pending()
        analytics.review_profile_suggestion('synthetic-a', sid, True)
        analytics.decline_profiling_consent('synthetic-a')
        self.assertEqual(analytics.get_profiling_consent('synthetic-a'), 'declined')
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_suggestions'), [])

    def test_stale_ai_result_rejected_after_regrant(self):
        analytics.grant_profiling_consent('synthetic-a')
        epoch = analytics.get_profiling_epoch('synthetic-a')
        analytics.withdraw_profiling_consent('synthetic-a')
        analytics.grant_profiling_consent('synthetic-a')
        with self.assertRaises(PermissionError):
            analytics.propose_profile_field('synthetic-a','support_needs','Peer support', expected_epoch=epoch)

    def test_context_excludes_before_grant_and_non_user(self):
        self.rows("INSERT INTO conversation_messages(sender,role,message,created_at) VALUES ('synthetic-a','user','Old', CURRENT_TIMESTAMP - interval '1 day')")
        analytics.grant_profiling_consent('synthetic-a')
        self.rows("INSERT INTO conversation_messages(sender,role,message) VALUES ('synthetic-a','user','New'), ('synthetic-a','assistant','Assistant'), ('synthetic-b','user','Other')")
        self.assertEqual(analytics.prepare_consented_profile_context('synthetic-a'), ['New'])
        analytics.withdraw_profiling_consent('synthetic-a')
        with self.assertRaises(PermissionError):
            analytics.prepare_consented_profile_context('synthetic-a')

    def test_concurrency_both_orders(self):
        for operation in ('original','edited','draft'):
            for first in ('approval','withdrawal'):
                with self.subTest(operation=operation, first=first):
                    analytics.withdraw_profiling_consent('synthetic-a')
                    sid = self.pending()
                    analytics.save_pending_profile_edit('synthetic-a', sid, 'Evening support')
                    ready = threading.Event()
                    release = threading.Event()
                    def action():
                        try:
                            if operation == 'original':
                                analytics.review_profile_suggestion('synthetic-a', sid, True)
                            elif operation == 'edited':
                                analytics.confirm_pending_profile_edit('synthetic-a', sid)
                            else:
                                analytics.save_pending_profile_edit('synthetic-a', sid, 'Weekend support')
                        except (PermissionError, ValueError):
                            pass
                    def first_worker():
                        conn = connect()
                        try:
                            with conn:
                                with conn.cursor() as cur:
                                    cur.execute("SELECT status FROM caregiver_profiling_consent WHERE sender='synthetic-a' FOR UPDATE")
                                    # Use this same connection for the first operation, retaining its consent lock.
                                    with patch.object(analytics, 'get_connection', lambda: NonClosing(conn)):
                                        (action if first == 'approval' else lambda: analytics.withdraw_profiling_consent('synthetic-a'))()
                                    ready.set()
                                    release.wait(2)
                        finally:
                            conn.close()
                    with concurrent.futures.ThreadPoolExecutor(2) as pool:
                        f1 = pool.submit(first_worker)
                        self.assertTrue(ready.wait(3))
                        f2 = pool.submit(analytics.withdraw_profiling_consent if first == 'approval' else action,
                                         *(['synthetic-a'] if first == 'approval' else []))
                        time.sleep(0.05)
                        release.set()
                        f1.result(timeout=5)
                        f2.result(timeout=5)
                    self.assertEqual(analytics.get_profiling_consent('synthetic-a'), 'withdrawn')
                    self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
                    self.assertEqual(self.rows('SELECT * FROM caregiver_profile_suggestions'), [])

    def test_migration_idempotent_and_data_preserved(self):
        sid = self.pending()
        self.migrate()
        self.migrate()
        self.assertEqual(analytics.get_pending_profile_suggestion('synthetic-a')['id'], sid)

    def test_migration_incompatible_schema_rolls_back(self):
        self.rows('ALTER TABLE caregiver_profile_fields ALTER COLUMN field_value TYPE varchar(300)')
        try:
            with self.assertRaises(psycopg2.Error):
                self.migrate()
        finally:
            self.rows('ALTER TABLE caregiver_profile_fields ALTER COLUMN field_value TYPE text')
        self.migrate()

    def test_migration_missing_constraint_fails(self):
        self.rows('ALTER TABLE caregiver_profile_fields DROP CONSTRAINT caregiver_profile_fields_field_name_check')
        try:
            with self.assertRaises(psycopg2.Error):
                self.migrate()
        finally:
            self.rows("ALTER TABLE caregiver_profile_fields ADD CONSTRAINT caregiver_profile_fields_field_name_check CHECK (field_name IN ('care_recipient_profile','support_needs','availability','caregiving_context'))")
        self.migrate()

    def test_migration_dry_run_leaves_schema_unchanged(self):
        self.rows('DROP TABLE whatsapp_receipts')
        conn=connect()
        try:
            with conn.cursor() as cur:
                cur.execute(SQL.rsplit('COMMIT;',1)[0]+'ROLLBACK;')
            self.assertEqual(self.rows("SELECT to_regclass('whatsapp_receipts')"), [(None,)])
        finally:
            conn.close()
            self.migrate()

    def test_migration_duplicate_pending_fails_without_deleting(self):
        self.pending()
        self.rows('DROP INDEX uq_caregiver_one_pending_suggestion')
        self.rows("INSERT INTO caregiver_profile_suggestions(sender,field_name,proposed_value) VALUES ('synthetic-a','availability','Weekends')")
        try:
            with self.assertRaises(psycopg2.Error):
                self.migrate()
            self.assertEqual(len(self.rows('SELECT id FROM caregiver_profile_suggestions')), 2)
        finally:
            self.rows("UPDATE caregiver_profile_suggestions SET status='rejected'")
            self.migrate()

    def test_routing_restored_and_withdrawal_global(self):
        database.update_user('synthetic-a', state='ai_chat')
        self.assertEqual(handlers.handle_message('synthetic-a','Hello Mixed CASE'), 'Synthetic AI reply')
        chat.ask_careconnect.assert_called_once_with('synthetic-a','Hello Mixed CASE')
        database.update_user('synthetic-a', state='resources_menu')
        self.assertIn('Type', handlers.handle_message('synthetic-a','1'))
        database.update_user('synthetic-a', state='main_menu')
        self.pending()
        self.assertIn('withdrawn', handlers.handle_message('synthetic-a','withdraw profile consent'))
        self.assertNotIn('\\n', handlers.PROFILING_CONSENT_PROMPT)

    def test_restored_buddy_onboarding_matching_states(self):
        chat.extract_matching_preferences.return_value={'support_type':'Peer support','availability':'Evenings'}
        chat.generate_onboarding_reply.return_value='Synthetic onboarding'
        chat.safe_adapt_message.side_effect=lambda message,*args,**kwargs: message
        database.update_user('synthetic-a',state='ai_onboarding')
        self.assertIn('Does this sound right',handlers.handle_message('synthetic-a','Evening peer support'))
        self.assertEqual(database.get_user('synthetic-a')['state'],'ai_onboarding_confirm')
        with patch.object(handlers,'find_matches',return_value=[]):
            self.assertIn('Buddy',handlers.handle_message('synthetic-a','1'))
        database.update_user('synthetic-a',state='confirm_match')
        self.assertIn("hasn't been sent",handlers.handle_message('synthetic-a','2'))
        database.update_user('synthetic-a',state='match_pending')
        self.assertIn('awaiting',handlers.handle_message('synthetic-a','checking update'))
        database.update_user('synthetic-a',state='matched')
        self.assertIn('matched',handlers.handle_message('synthetic-a','checking update'))

    def test_profile_routing_full_edit_confirmation(self):
        self.pending()
        database.update_user('synthetic-a', state='ai_chat')
        self.assertIn('Accept suggestion', handlers.handle_message('synthetic-a','review profile'))
        handlers.handle_message('synthetic-a','2')
        self.assertIn('Evening Support', handlers.handle_message('synthetic-a','Evening Support'))
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        self.assertIn('saved', handlers.handle_message('synthetic-a','1'))
        self.assertEqual(self.rows('SELECT field_value FROM caregiver_profile_fields'), [('Evening Support',)])

    def test_ai_filters_identifiers_and_disables_response_storage(self):
        chat.client.responses.create.return_value.output_text = json.dumps({'support_needs':'Peer support','availability':'91234567','unknown':'x'})
        self.assertEqual(suggestions.generate_profile_suggestions(['Peer support','Call 91234567']), {'support_needs':'Peer support'})
        args = chat.client.responses.create.call_args.kwargs
        self.assertFalse(args['store'])
        self.assertNotIn('91234567', args['input'])

    def post(self, data, signed=True):
        raw = json.dumps(data).encode()
        signature = 'sha256=' + hmac.new(b'synthetic-secret', raw, hashlib.sha256).hexdigest()
        with patch.dict(os.environ, WHATSAPP_APP_SECRET='synthetic-secret'):
            return web.app.test_client().post('/webhook',data=raw,content_type='application/json',
                        headers={'X-Hub-Signature-256': signature if signed else 'bad'})

    def test_webhook_signed_batch_case_dedup_no_private_logs(self):
        payload={'entry':[{'changes':[{'value':{'messages':[
            {'id':'synthetic-msg-1','from':'synthetic-a','type':'text','text':{'body':'Mixed CASE'}},
            {'id':'synthetic-msg-2','from':'synthetic-b','type':'text','text':{'body':'Second'}}]}}]}]}
        with patch.object(web,'handle_message',return_value='private reply') as handler, patch.object(web,'send_message') as send:
            self.assertEqual(self.post(payload,False).status_code,403)
            handler.assert_not_called()
            self.assertEqual(self.post(payload).status_code,200)
            self.assertEqual(self.post(payload).status_code,200)
            self.assertEqual(handler.call_count,2)
            handler.assert_any_call('synthetic-a','Mixed CASE')
            self.assertEqual(send.call_count,2)
        self.assertEqual(self.rows("SELECT count(*) FROM whatsapp_receipts WHERE status='completed'"), [(2,)])

    def test_signed_webhook_through_real_profile_handler(self):
        self.pending()
        database.update_user('synthetic-a',state='ai_chat')
        def payload(identifier,body):
            return {'entry':[{'changes':[{'value':{'messages':[
                {'id':identifier,'from':'synthetic-a','type':'text','text':{'body':body}}]}}]}]}
        with patch.object(web,'send_message') as send:
            self.assertEqual(self.post(payload('full-review','review profile')).status_code,200)
            self.assertIn('Accept suggestion',send.call_args.args[1])
            self.assertEqual(self.post(payload('full-accept','1')).status_code,200)
            self.assertEqual(self.rows('SELECT field_value FROM caregiver_profile_fields'), [('Peer support',)])
            self.assertEqual(self.post(payload('full-withdraw','withdraw profile consent')).status_code,200)
            self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
            self.assertEqual(self.rows('SELECT * FROM caregiver_profile_suggestions'), [])

    def test_webhook_failure_is_private_and_recorded(self):
        payload={'entry':[{'changes':[{'value':{'messages':[
            {'id':'synthetic-fail','from':'synthetic-a','type':'text','text':{'body':'private input'}}]}}]}]}
        with patch.object(web,'handle_message',side_effect=RuntimeError('SECRET')), self.assertLogs(web.logger,level='ERROR') as logs:
            self.assertEqual(self.post(payload).status_code,503)
        self.assertNotIn('SECRET',' '.join(logs.output))
        self.assertNotIn('private input',' '.join(logs.output))
        self.assertEqual(self.rows('SELECT status FROM whatsapp_receipts'), [('failed',)])
        self.assertEqual(self.post(payload).status_code,503)

    def test_unsafe_browser_routes_disabled(self):
        client=web.app.test_client()
        for path in ('/test/synthetic-a/menu','/caregiver/name/requests','/caregiver/name/accept/1','/caregiver/name/decline/1'):
            self.assertEqual(client.get(path).status_code,404)


class NonClosing:
    """Nested transaction adapter used only by deterministic concurrency tests."""
    def __init__(self, conn): self.conn=conn
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def cursor(self): return self.conn.cursor()
    def close(self): pass


if __name__ == '__main__':
    unittest.main(verbosity=2)
