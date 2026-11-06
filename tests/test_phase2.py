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
