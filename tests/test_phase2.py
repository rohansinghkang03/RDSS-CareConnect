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
                cur.execute('TRUNCATE support_buddy_applications, support_buddy_drafts, match_requests, match_previews, admin_review_events RESTART IDENTITY CASCADE')
        database.create_user('synthetic-a')
        database.create_user('synthetic-b')
        for name in ('ask_careconnect', 'get_matching_language_example', 'remember_matching_language'):
            getattr(chat, name).reset_mock()
        chat.get_matching_language_example.return_value = None
        chat.ask_careconnect.return_value = 'Synthetic AI reply'
        chat.safe_adapt_message.side_effect=lambda message,*args,**kwargs: message
        chat.client.reset_mock()

    def rows(self, sql, params=()):
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []

    def pending(self):
        analytics.grant_profiling_consent('synthetic-a')
        return analytics.propose_profile_field('synthetic-a', 'support_needs', 'Peer support')

    def test_admin_allowlist_parses_multiple_numbers_and_fails_closed(self):
        numbers=handlers.parse_admin_phone_numbers(' +6500000001,6500000002, 6500000001, ,invalid, ６５０００００００３,650000 0004,')
        self.assertEqual(numbers,frozenset({'6500000001','6500000002'}))
        self.assertNotIn('650000000',numbers)
        for value in ('', ' , ', 'invalid', None):
            self.assertEqual(handlers.parse_admin_phone_numbers(value),frozenset())

    def test_multiple_approved_admins_require_password_and_have_independent_states(self):
        with patch.object(handlers,'ADMIN_PHONE_NUMBERS',frozenset({'synthetic-a','synthetic-b'})), patch.object(handlers,'ADMIN_PIN','Synthetic-PassCase'):
            for sender in ('synthetic-a','synthetic-b'):
                self.assertIn('Enter your admin PIN',handlers.handle_message(sender,'admin login'))
                self.assertEqual(database.get_user(sender)['state'],'admin_pin')
            self.assertIn('Incorrect PIN',handlers.handle_message('synthetic-a','synthetic-passcase'))
            self.assertEqual(database.get_user('synthetic-a')['state'],'admin_pin')
            self.assertIn('login successful',handlers.handle_message('synthetic-a','Synthetic-PassCase'))
            self.assertEqual(database.get_user('synthetic-b')['state'],'admin_pin')
            self.assertIn('login successful',handlers.handle_message('synthetic-b','Synthetic-PassCase'))
            handlers.handle_message('synthetic-a','3')
            self.assertEqual(database.get_user('synthetic-a')['state'],'main_menu')
            self.assertEqual(database.get_user('synthetic-b')['state'],'admin_menu')

    def test_unapproved_admin_cannot_login_or_use_private_routes(self):
        with patch.object(handlers,'ADMIN_PHONE_NUMBERS',frozenset({'synthetic-a'})), patch.object(handlers,'ADMIN_PIN','Synthetic-PassCase'), patch.object(handlers,'admin_application_summary',side_effect=AssertionError('Private route must not run')):
            self.assertIn('not enabled',handlers.handle_message('synthetic-b','admin login'))
            database.update_user('synthetic-b',state='admin_pin')
            self.assertIn('not enabled',handlers.handle_message('synthetic-b','Synthetic-PassCase'))
            self.assertEqual(database.get_user('synthetic-b')['state'],'main_menu')
            database.update_user('synthetic-b',state='admin_menu')
            self.assertIn('not enabled',handlers.handle_message('synthetic-b','2'))
            self.assertEqual(database.get_user('synthetic-b')['state'],'main_menu')
            self.assertIn('not enabled',handlers.handle_admin_message('synthetic-b','2','admin_menu'))

    def test_removing_approved_number_revokes_admin_state(self):
        with patch.object(handlers,'ADMIN_PHONE_NUMBERS',frozenset({'synthetic-a'})), patch.object(handlers,'ADMIN_PIN','Synthetic-PassCase'):
            handlers.handle_message('synthetic-a','admin login')
            handlers.handle_message('synthetic-a','Synthetic-PassCase')
            with patch.object(handlers,'ADMIN_PHONE_NUMBERS',frozenset()):
                self.assertIn('not enabled',handlers.handle_message('synthetic-a','menu'))
                self.assertEqual(database.get_user('synthetic-a')['state'],'main_menu')
            self.assertIn('Enter your admin PIN',handlers.handle_message('synthetic-a','admin login'))
            self.assertEqual(database.get_user('synthetic-a')['state'],'admin_pin')

    def test_missing_admin_configuration_cannot_reuse_logged_in_state(self):
        with patch.object(handlers,'ADMIN_PHONE_NUMBERS',frozenset()), patch.object(handlers,'ADMIN_PIN','Synthetic-PassCase'):
            self.assertIn('not enabled',handlers.handle_message('synthetic-a','admin login'))
        database.update_user('synthetic-a',state='admin_menu')
        with patch.object(handlers,'ADMIN_PHONE_NUMBERS',frozenset({'synthetic-a'})), patch.object(handlers,'ADMIN_PIN',''):
            self.assertIn('unavailable',handlers.handle_message('synthetic-a','2'))
            self.assertEqual(database.get_user('synthetic-a')['state'],'main_menu')

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
        self.assertIn('Synthetic AI reply', handlers.handle_message('synthetic-a','Hello Mixed CASE'))
        chat.ask_careconnect.assert_called_once_with('synthetic-a','Hello Mixed CASE')
        database.update_user('synthetic-a', state='resources_menu')
        self.assertIn('You can type these other commands too:', handlers.handle_message('synthetic-a','1'))
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

    def test_main_menu_profile_status_and_language_are_visible(self):
        chat.get_matching_language_example.return_value='English'
        menu=handlers.handle_message('synthetic-a','menu')
        for label in ('6. 👤 My profile','7. 📋 My request','8. 🌐 Change language'):
            self.assertIn(label,menu)
        profile=handlers.handle_message('synthetic-a','6')
        self.assertIn('Not enabled',profile)
        self.assertIn('Withdraw permission',profile)
        self.assertEqual(database.get_user('synthetic-a')['state'],'profile_menu')
        handlers.handle_message('synthetic-a','4')
        self.assertIn('My status',handlers.handle_message('synthetic-a','7'))
        self.assertIn('do not have any match requests',handlers.handle_message('synthetic-a','1'))
        self.assertIn("haven't submitted",handlers.handle_message('synthetic-a','2'))
        handlers.handle_message('synthetic-a','3')
        self.assertIn('which language',handlers.handle_message('synthetic-a','8'))

    def test_numbered_profile_enable_view_withdraw_cancel_confirm(self):
        chat.get_matching_language_example.return_value='English'
        handlers.handle_message('synthetic-a','profile')
        prompt=handlers.handle_message('synthetic-a','2')
        self.assertIn('choose 6',prompt)
        self.assertIn('then 3',prompt)
        self.assertEqual(analytics.get_profiling_consent('synthetic-a'),'not_given')
        enabled=handlers.handle_message('synthetic-a','1')
        self.assertIn('Enabled',enabled)
        self.assertIn('Withdraw permission',enabled)
        epoch=analytics.get_profiling_epoch('synthetic-a')
        # Reading the permission notice again must not reset the message window.
        handlers.handle_message('synthetic-a','2')
        handlers.handle_message('synthetic-a','1')
        self.assertEqual(analytics.get_profiling_epoch('synthetic-a'),epoch)
        sid=analytics.propose_profile_field('synthetic-a','support_needs','Evening support')
        analytics.review_profile_suggestion('synthetic-a',sid,True)
        saved=handlers.handle_message('synthetic-a','profile')
        self.assertIn('Evening support',saved)
        self.assertNotIn('Evening support',handlers.handle_message('synthetic-b','profile'))
        confirmation=handlers.handle_message('synthetic-a','3')
        self.assertIn('1. Yes, withdraw',confirmation)
        self.assertEqual(analytics.get_profiling_consent('synthetic-a'),'granted')
        self.assertIn('cancelled',handlers.handle_message('synthetic-a','2'))
        self.assertIn('Evening support',handlers.handle_message('synthetic-a','profile'))
        handlers.handle_message('synthetic-a','3')
        withdrawn=handlers.handle_message('synthetic-a','1')
        self.assertIn('Disabled (withdrawn)',withdrawn)
        self.assertIn('No profile information is saved',withdrawn)
        self.assertNotIn('Evening support',withdrawn)
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_suggestions'), [])

    def test_profile_translation_excludes_and_preserves_caregiver_text(self):
        import profile_navigation
        self.pending()
        sid=analytics.get_pending_profile_suggestion('synthetic-a')['id']
        exact='需要情绪支持，晚上有空。'
        analytics.review_profile_suggestion('synthetic-a',sid,True,exact)
        chat.get_matching_language_example.return_value='Mandarin Chinese'
        seen=[]
        def translate(message,*args,**kwargs):
            seen.append(message)
            return message.replace('My caregiver profile','我的照护者档案').replace('Withdraw permission','撤回同意')
        chat.safe_adapt_message.side_effect=translate
        result=handlers.handle_message('synthetic-a','profile')
        self.assertIn('我的照护者档案',result)
        self.assertIn(exact,result)
        self.assertTrue(seen)
        self.assertTrue(all(exact not in message for message in seen))
        # Corrupted translation placeholders fall back to the complete original template.
        chat.safe_adapt_message.side_effect=lambda message,*a,**k: 'broken translation'
        result=handlers.handle_message('synthetic-a','profile')
        self.assertIn(exact,result)
        self.assertIn('3. Withdraw permission',result)
        self.assertEqual(profile_navigation.profile_text('synthetic-a','__ONE__ __TWO__',
                         {'__ONE__':'__TWO__','__TWO__':'exact'}),'__TWO__ exact')

    def test_profile_cancel_edit_and_reject_remain_visible(self):
        self.pending()
        handlers.handle_message('synthetic-a','review profile')
        handlers.handle_message('synthetic-a','2')
        handlers.handle_message('synthetic-a','Evening support')
        cancelled=handlers.handle_message('synthetic-a','2')
        self.assertIn('Accept suggestion',cancelled)
        rejected=handlers.handle_message('synthetic-a','3')
        self.assertIn('Suggestion rejected',rejected)
        self.assertIn('No profile information is saved',rejected)
        self.assertIn('Withdraw permission',rejected)
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])

    def test_profile_review_service_failure_keeps_navigation_available(self):
        import profile_navigation
        self.pending()
        handlers.handle_message('synthetic-a','profile')
        with patch.object(profile_navigation,'generate_and_prepare_profile_review',side_effect=RuntimeError('private diagnostic')):
            with self.assertLogs(profile_navigation.__name__,level='WARNING') as logs:
                result=handlers.handle_message('synthetic-a','1')
        self.assertIn('temporarily unavailable',result)
        self.assertIn('3. Withdraw permission',result)
        self.assertNotIn('private diagnostic',' '.join(logs.output))
        self.assertEqual(analytics.get_profiling_consent('synthetic-a'),'granted')

    def test_profile_numbered_decline_does_not_enable_and_hides_stale_fields(self):
        sid=self.pending()
        analytics.review_profile_suggestion('synthetic-a',sid,True)
        handlers.handle_message('synthetic-a','profile')
        handlers.handle_message('synthetic-a','2')
        result=handlers.handle_message('synthetic-a','2')
        self.assertIn('Disabled (declined)',result)
        self.assertIn('No profile information is saved',result)
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        # Even an externally inserted stale field must not appear without current consent.
        self.rows("INSERT INTO caregiver_profile_fields(sender,field_name,field_value) VALUES ('synthetic-a','support_needs','Stale field')")
        self.assertNotIn('Stale field',handlers.handle_message('synthetic-a','profile'))

    def test_every_ai_reply_has_actionable_navigation_without_translating_reply(self):
        database.update_user('synthetic-a',state='ai_chat')
        chat.ask_careconnect.return_value='Private caregiver-specific reply'
        chat.get_matching_language_example.return_value='Malay'
        seen=[]
        def translate(message,*args,**kwargs):
            seen.append(message)
            return message
        chat.safe_adapt_message.side_effect=translate
        result=handlers.handle_message('synthetic-a','A normal message')
        self.assertIn('Private caregiver-specific reply',result)
        self.assertIn("'menu'",result)
        self.assertIn("'profile'",result)
        self.assertTrue(seen)
        self.assertTrue(all('Private caregiver-specific reply' not in text for text in seen))

    def test_navigation_footer_is_contextual_and_does_not_duplicate(self):
        database.update_user('synthetic-a',state='match_pending')
        result=handlers.add_reply_navigation('synthetic-a','Your request is pending.')
        self.assertIn("'my status'",result)
        self.assertIn("'menu'",result)
        existing="Choose 1 or 2. Type 'menu' to go back."
        self.assertEqual(handlers.add_reply_navigation('synthetic-a',existing),existing)
        database.update_user('synthetic-a',state='language_selection')
        language=handlers.add_reply_navigation('synthetic-a','Choose a language.')
        self.assertIn('to continue to the main menu',language)
        self.assertIn('language choices again',language)
        self.assertNotIn("'my status'",language)

    def test_navigation_footer_handles_invalid_translation_and_unavailable_preferences(self):
        database.update_user('synthetic-a',state='ai_chat')
        chat.get_matching_language_example.return_value='Tamil'
        chat.safe_adapt_message.side_effect=lambda *args,**kwargs: 'commands were lost'
        result=handlers.add_reply_navigation('synthetic-a','A reply')
        self.assertIn("'menu'",result)
        self.assertIn("'profile'",result)
        with patch.object(handlers,'get_user',side_effect=RuntimeError('private database diagnostic')):
            result=handlers.add_reply_navigation('synthetic-a','Please try again.')
        self.assertIn("'menu'",result)
        self.assertNotIn('diagnostic',result)

    def test_short_profile_validation_and_cancel_prompts_have_menu_exit(self):
        self.pending()
        handlers.handle_message('synthetic-a','review profile')
        handlers.handle_message('synthetic-a','2')
        invalid=handlers.handle_message('synthetic-a','Call 91234567')
        self.assertIn("'menu'",invalid)
        self.assertIn('without contact details',invalid)
        handlers.handle_message('synthetic-a','profile')
        handlers.handle_message('synthetic-a','3')
        retry=handlers.handle_message('synthetic-a','invalid choice')
        self.assertIn("'menu'",retry)
        self.assertIn('Cancel and keep my profile',retry)

    def test_malay_withdrawal_cancel_uses_fixed_wording_without_model(self):
        self.pending()
        chat.get_matching_language_example.return_value='Malay'
        chat.safe_adapt_message.side_effect=AssertionError('No model translation should be needed for these screens')
        profile=handlers.handle_message('synthetic-a','profile')
        self.assertIn('Profil penjaga saya',profile)
        confirm=handlers.handle_message('synthetic-a','3')
        self.assertIn('Tarik balik kebenaran profil?',confirm)
        cancelled=handlers.handle_message('synthetic-a','2')
        self.assertIn('Penarikan balik kebenaran dibatalkan',cancelled)
        self.assertIn('Cadangan profil: Diaktifkan',cancelled)
        self.assertNotIn('Withdrawal cancelled',cancelled)
        self.assertNotIn('My caregiver profile',cancelled)
        self.assertEqual(analytics.get_profiling_consent('synthetic-a'),'granted')

    def test_malay_profile_saved_wording_is_preserved_without_model(self):
        sid=self.pending()
        exact='晚上有空，想找人聊聊。'
        analytics.review_profile_suggestion('synthetic-a',sid,True,exact)
        chat.get_matching_language_example.return_value='Bahasa Melayu'
        chat.safe_adapt_message.side_effect=AssertionError('No model translation should be needed')
        profile=handlers.handle_message('synthetic-a','profile')
        self.assertIn('Keperluan sokongan: '+exact,profile)
        handlers.handle_message('synthetic-a','3')
        withdrawn=handlers.handle_message('synthetic-a','1')
        self.assertIn('kebenaran ditarik balik',withdrawn)
        self.assertIn('Tiada maklumat profil disimpan',withdrawn)
        self.assertNotIn(exact,withdrawn)

    def test_profile_translation_accepts_smart_quotes_around_commands(self):
        import profile_navigation
        chat.get_matching_language_example.return_value='Tamil'
        chat.safe_adapt_message.side_effect=lambda *args,**kwargs: 'Taip “menu” untuk menu utama.'
        result=profile_navigation.profile_text('synthetic-a',"Type 'menu' for the main menu.")
        self.assertIn('Taip',result)
        chat.safe_adapt_message.side_effect=lambda *args,**kwargs: 'Command was removed.'
        self.assertEqual(profile_navigation.profile_text('synthetic-a',"Type 'menu' for the main menu."),"Type 'menu' for the main menu.")

    def approved_buddy(self):
        return self.rows("""INSERT INTO support_buddy_applications
            (sender,full_name,display_name,support_types,availability,languages,status,
             consent,submitted_at,verification_required)
            VALUES ('synthetic-b','Synthetic Buddy','Synthetic Buddy','Peer support',
                    'Evenings','English','approved',1,CURRENT_TIMESTAMP,0) RETURNING id""")[0][0]

    def prepare_actual_buddy_request(self):
        self.approved_buddy()
        chat.get_matching_language_example.return_value='English'
        chat.extract_matching_preferences.return_value={'support_type':'Peer support','availability':'Evenings'}
        chat.generate_onboarding_reply.return_value='Synthetic onboarding reply'
        handlers.handle_message('synthetic-a','menu')
        handlers.handle_message('synthetic-a','1')
        handlers.handle_message('synthetic-a','I want Peer support in the Evenings')
        preview=handlers.handle_message('synthetic-a','1')
        self.assertIn('Synthetic Buddy',preview)
        self.assertEqual(database.get_user('synthetic-a')['state'],'confirm_match')
        self.assertEqual(self.rows('SELECT id FROM match_requests'), [])
        sent=handlers.handle_message('synthetic-a','1')
        self.assertIn('Connection request sent',sent)
        return self.rows('SELECT id FROM match_requests')[0][0]

    def test_natural_language_dispatch_covers_all_eight_menu_options(self):
        chat.get_matching_language_example.return_value='English'
        cases=[('1','I want a support buddy','ai_onboarding'),
               ('2','I want to talk to the AI','ai_chat'),
               ('3','I need financial support resources','resources_menu'),
               ('4','I want to volunteer as a buddy','buddy_registration_name'),
               ('5','I want to contact RDSS staff','main_menu'),
               ('6','Show my saved caregiver profile','profile_menu'),
               ('7','Check the progress of my request','status_menu'),
               ('8','I want to change my language','language_selection')]
        for label,utterance,state in cases:
            with self.subTest(label=label):
                database.update_user('synthetic-a',state='main_menu')
                chat.client.responses.create.return_value.output_text=label
                result=handlers.handle_message('synthetic-a',utterance)
                self.assertEqual(database.get_user('synthetic-a')['state'],state)
                self.assertIn("'menu'",result)
                args=chat.client.responses.create.call_args.kwargs
                self.assertEqual(args['input'],utterance)
                self.assertIn('6 =',args['instructions'])
                self.assertIn('7 =',args['instructions'])
                self.assertIn('8 =',args['instructions'])

    def test_natural_language_unknown_and_ambiguous_do_not_guess_or_save(self):
        chat.get_matching_language_example.return_value='English'
        for response in ('CLARIFY','UNKNOWN','9','1 then 6','{"label": "1"}'):
            with self.subTest(response=response):
                database.update_user('synthetic-a',state='main_menu')
                chat.client.responses.create.return_value.output_text=response
                reply=handlers.handle_message('synthetic-a','I am feeling lonely')
                self.assertEqual(database.get_user('synthetic-a')['state'],'main_menu')
                self.assertIn("'menu'",reply)
                self.assertEqual(self.rows('SELECT id FROM match_requests'), [])
                self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'), [])
        chat.client.responses.create.side_effect=RuntimeError('private diagnostic')
        try:
            self.assertIn('choose an option',handlers.handle_message('synthetic-a','Please help me'))
        finally:
            chat.client.responses.create.side_effect=None

    def test_buddy_end_to_end_accept_ownership_and_repeat_response(self):
        request_id=self.prepare_actual_buddy_request()
        inbox=handlers.handle_message('synthetic-b','requests')
        self.assertIn('Request #'+str(request_id),inbox)
        self.assertIn('Peer support',inbox)
        self.assertIn('not found',handlers.handle_message('synthetic-a','accept '+str(request_id)))
        self.assertIn('not found',handlers.handle_message('synthetic-a','request '+str(request_id)))
        accepted=handlers.handle_message('synthetic-b','accept '+str(request_id))
        self.assertIn('accepted',accepted)
        self.assertIn('not enabled',accepted)
        self.assertIn('already accepted',handlers.handle_message('synthetic-b','decline '+str(request_id)))
        self.assertIn('Status: Accepted',handlers.handle_message('synthetic-a','status'))
        self.assertEqual(self.rows('SELECT status FROM match_requests'), [('accepted',)])
        self.assertEqual(self.rows('SELECT * FROM caregiver_sharing_decisions'), [])

    def test_buddy_end_to_end_decline_and_next_search_excludes_same_buddy(self):
        request_id=self.prepare_actual_buddy_request()
        self.assertIn('declined',handlers.handle_message('synthetic-b','decline '+str(request_id)))
        self.assertIn('another buddy',handlers.handle_message('synthetic-a','status'))
        handlers.handle_message('synthetic-a','1')
        handlers.handle_message('synthetic-a','Peer support in Evenings')
        no_match=handlers.handle_message('synthetic-a','1')
        self.assertIn("couldn't find",no_match)
        self.assertEqual(self.rows('SELECT status FROM match_requests'), [('declined',)])

    def test_buddy_concurrent_confirmations_create_one_request(self):
        buddy_id=self.approved_buddy()
        database.update_user('synthetic-a',support_type='Peer support',availability='Evenings')
        database.save_match_preview('synthetic-a',{'buddy_id':buddy_id,'sender':'synthetic-b','name':'Synthetic Buddy','percentage':100},database.get_user('synthetic-a'))
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results=list(pool.map(database.create_selected_match_request,['synthetic-a','synthetic-a']))
        self.assertEqual(sorted(outcome for outcome,_ in results),['created','missing'])
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests'), [(1,)])
        request_id=self.rows('SELECT id FROM match_requests')[0][0]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            outcomes=list(pool.map(lambda decision: database.respond_to_buddy_request('synthetic-b',request_id,decision),['accepted','declined']))
        self.assertEqual(sorted(outcome for outcome,_ in outcomes),['already_resolved','updated'])
        self.assertEqual(len(self.rows('SELECT id FROM match_requests')),1)

    def test_buddy_ineligible_before_confirm_or_accept_is_blocked(self):
        buddy_id=self.approved_buddy()
        database.save_match_preview('synthetic-a',{'buddy_id':buddy_id,'sender':'synthetic-b','name':'Synthetic Buddy','percentage':100},database.get_user('synthetic-a'))
        self.rows("UPDATE support_buddy_applications SET verification_required=1,verified_at=NULL")
        self.assertEqual(database.create_selected_match_request('synthetic-a')[0],'unavailable')
        self.assertEqual(self.rows('SELECT id FROM match_requests'), [])
        self.rows('UPDATE support_buddy_applications SET verification_required=0')
        database.save_match_preview('synthetic-a',{'buddy_id':buddy_id,'sender':'synthetic-b','name':'Synthetic Buddy','percentage':100},database.get_user('synthetic-a'))
        _,request=database.create_selected_match_request('synthetic-a')
        self.rows("UPDATE support_buddy_applications SET status='rejected'")
        self.assertEqual(database.respond_to_buddy_request('synthetic-b',request['id'],'accepted')[0],'unavailable')
        self.assertEqual(self.rows('SELECT status FROM match_requests'), [('pending',)])

    def test_registration_consent_submission_and_events_preserve_name_case(self):
        chat.get_matching_language_example.return_value='English'
        database.update_user('synthetic-a',state='main_menu')
        handlers.handle_message('synthetic-a','4')
        answers=['Synthetic Volunteer','1','Synthetic Display','1','2','1','3','1','skip']
        for answer in answers:
            handlers.handle_message('synthetic-a',answer)
        self.assertEqual(database.get_user('synthetic-a')['state'],'buddy_registration_review')
        self.assertEqual(self.rows('SELECT id FROM support_buddy_applications'), [])
        handlers.handle_message('synthetic-a','1')
        self.assertEqual(self.rows('SELECT id FROM support_buddy_applications'), [])
        submitted=handlers.handle_message('synthetic-a','1')
        self.assertIn('submitted',submitted)
        self.assertEqual(self.rows('SELECT full_name,display_name,consent,status FROM support_buddy_applications'), [('Synthetic Volunteer','Synthetic Display',1,'pending')])
        handlers.handle_message('synthetic-a','1')
        events=[row[0] for row in self.rows('SELECT event_type FROM usage_events')]
        self.assertEqual(events.count('buddy_application_started'),1)
        self.assertEqual(events.count('buddy_application_submitted'),1)

    def test_analytics_rejects_free_text_categories_and_event_payloads(self):
        private='Private caregiver story containing a name'
        for event in analytics.EVENT_TYPES:
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    analytics.record_usage_event('synthetic-a',event,private)
        for event in ('unknown',private,None,{},[]):
            with self.assertRaises(ValueError):
                analytics.record_usage_event('synthetic-a',event)
        self.assertEqual(self.rows('SELECT id FROM usage_events'), [])
        analytics.record_usage_event('synthetic-a','resource_category_opened','2')
        analytics.record_usage_event('synthetic-a','ai_chat_started')
        self.assertEqual(self.rows('SELECT event_type,category FROM usage_events ORDER BY id'), [('resource_category_opened','2'),('ai_chat_started',None)])

    def test_routed_usage_events_cover_buddy_profile_and_numeric_resource(self):
        self.prepare_actual_buddy_request()
        handlers.handle_message('synthetic-a','menu')
        handlers.handle_message('synthetic-a','2')
        handlers.handle_message('synthetic-a','menu')
        handlers.handle_message('synthetic-a','3')
        handlers.handle_message('synthetic-a','2')
        self.pending()
        handlers.handle_message('synthetic-a','review profile')
        handlers.handle_message('synthetic-a','3')
        events=self.rows('SELECT event_type,category FROM usage_events')
        names={event for event,_ in events}
        self.assertTrue({'main_menu_opened','ai_chat_started','resource_hub_opened','resource_category_opened','buddy_search_started','support_need_selected','buddy_match_found','profile_suggestion_reviewed'} <= names)
        self.assertIn(('resource_category_opened','2'),events)
        self.assertTrue(all(category in (None,'1','2','3','4') for _,category in events))
        self.assertEqual(sum(event=='profile_suggestion_reviewed' for event,_ in events),1)
        self.assertTrue(all('Peer support' not in str(row) for row in events))

    def test_analytics_failure_is_private_and_does_not_break_routing(self):
        chat.get_matching_language_example.return_value='English'
        with patch.object(analytics,'record_usage_event',side_effect=RuntimeError('private caregiver text')):
            with self.assertLogs(handlers.__name__,level='WARNING') as logs:
                reply=handlers.handle_message('synthetic-a','menu')
        self.assertIn('How can I support',reply)
        self.assertNotIn('private caregiver text',' '.join(logs.output))

    def test_incoming_buddy_requests_are_visible_through_status_menu(self):
        request_id=self.prepare_actual_buddy_request()
        menu=handlers.handle_message('synthetic-b','my status')
        self.assertIn('4. Incoming buddy connection requests',menu)
        inbox=handlers.handle_message('synthetic-b','4')
        self.assertIn('Request #'+str(request_id),inbox)
        self.assertIn('accept '+str(request_id),inbox)
        self.assertIn("'menu'",inbox)
        self.assertNotIn('synthetic-a',inbox)

    def test_same_display_name_does_not_authorize_another_buddy(self):
        request_id=self.prepare_actual_buddy_request()
        database.create_user('synthetic-c')
        self.rows("""INSERT INTO support_buddy_applications(sender,display_name,support_types,availability,status,consent,submitted_at,verification_required)
            VALUES ('synthetic-c','Synthetic Buddy','Peer support','Evenings','approved',1,CURRENT_TIMESTAMP,0)""")
        self.assertEqual(database.get_buddy_requests('synthetic-c')[0], [])
        self.assertEqual(database.respond_to_buddy_request('synthetic-c',request_id,'accepted')[0],'not_found')
        self.assertEqual(self.rows('SELECT status FROM match_requests'), [('pending',)])

    def test_application_timestamp_formats_postgres_short_offsets_and_iso(self):
        from datetime import datetime,timezone
        values=['2026-11-06 16:20:11.292956+00','2026-11-06T16:20:11+00:00',
                '2026-11-06T16:20:11Z','2026-11-06 16:20:11 UTC',
                '2026-11-06 16:20:11.12345+00','2026-11-06 16:20:11.1+00',
                '2026-11-07 00:20:11+08',datetime(2026,11,6,16,20,11,tzinfo=timezone.utc)]
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(handlers.format_sgt_timestamp(value),'7 November 2026, 12:20 AM SGT')

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
