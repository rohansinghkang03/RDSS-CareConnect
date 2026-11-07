"""Reporting integration tests: isolated PostgreSQL, synthetic people, no network."""
import hashlib
import os
import tempfile
import threading
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

import test_phase2 as base
import reporting_tracking as tracking
import reporting_auth as auth
import reporting_data as data
import reporting_jobs as jobs
import reporting_workbook as excel
import reporting_fixtures as fixtures
import whatsapp

for module in (tracking,auth,data,jobs,fixtures):module.get_connection=base.connect

class Phase3Tests(unittest.TestCase):
    def rows(self,sql,params=()):
        with base.connect() as connection:
            with connection.cursor() as cur:
                if params:cur.execute(sql,params)
                else:cur.execute(sql)
                return cur.fetchall() if cur.description else []
    setUpClass=classmethod(base.Phase2Tests.setUpClass.__func__)
    tearDownClass=classmethod(base.Phase2Tests.tearDownClass.__func__)
    migrate=staticmethod(base.Phase2Tests.migrate)

    def setUp(self):
        # Each test starts with existing Phase 2 accounts, then an additive migration.
        base.Phase2Tests.setUp(self)
        with base.connect() as conn:
            with conn.cursor() as cur:cur.execute((base.ROOT/'phase3_schema.sql').read_text())
        self.rows('TRUNCATE reporting_ai,reporting_outgoing,reporting_statuses,reporting_jobs,reporting_admin_sessions,reporting_login_attempts,reporting_activity,reporting_facts')
        self.env=patch.dict(os.environ,{'REPORTING_ENABLED':'true','ADMIN_PIN':'Synthetic-PassCase','ADMIN_PHONE_NUMBERS':'6500000001'})
        self.env.start();self.addCleanup(self.env.stop)
        network=patch('requests.sessions.Session.request',side_effect=AssertionError('External network is forbidden in synthetic tests'))
        network.start();self.addCleanup(network.stop)
        base.database.create_user('6500000001')
        self.now=self.rows('SELECT CURRENT_TIMESTAMP')[0][0]
        self.today=self.now.astimezone(data.SGT).date()
        # Cover current test reporting periods explicitly; production migration never invents this history.
        self.rows("UPDATE reporting_settings SET value=CURRENT_TIMESTAMP-INTERVAL '90 days' WHERE key='coverage_start'")
        self.rows("DELETE FROM reporting_settings WHERE key='tracking_live_start'")

    def grant(self,sender='synthetic-a'):
        base.analytics.grant_profiling_consent(sender)

    def approved_profile(self):
        self.grant()
        sid=base.analytics.propose_profile_field('synthetic-a','support_needs','Peer support')
        base.analytics.review_profile_suggestion('synthetic-a',sid,True)

    def login(self):
        return auth.login('6500000001','Synthetic-PassCase','Synthetic-PassCase',{'6500000001'})

    def snapshot(self):return data.snapshot(self.today-timedelta(days=6),self.today,excluded={'6500000001'})

    def test_migration_repeated_preserves_data_and_coverage(self):
        self.approved_profile();before=self.rows('SELECT * FROM reporting_people ORDER BY sender')
        for _ in range(2):
            self.rows((base.ROOT/'phase3_schema.sql').read_text())
        self.assertEqual(self.rows('SELECT * FROM reporting_people ORDER BY sender'),before)
        self.assertEqual(self.rows('SELECT field_value FROM caregiver_profile_fields'),[('Peer support',)])

    def test_old_accounts_have_unknown_first_seen_new_accounts_have_timestamp(self):
        # Existing accounts were created before the trigger on the first test; create a true legacy row by clearing metadata.
        self.rows('UPDATE reporting_people SET first_seen=NULL WHERE sender=%s',('synthetic-a',))
        base.database.create_user('synthetic-new')
        self.assertIsNone(self.rows('SELECT first_seen FROM reporting_people WHERE sender=%s',('synthetic-a',))[0][0])
        self.assertIsNotNone(self.rows('SELECT first_seen FROM reporting_people WHERE sender=%s',('synthetic-new',))[0][0])

    def test_activity_duplicate_and_unique_users(self):
        self.grant()
        for key in ['one','one','two']:tracking.record_activity('synthetic-a',key)
        result=self.snapshot()
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reporting_activity')[0][0],2)
        self.assertEqual(result['periods'][1][1],1)
        self.assertEqual(result['caregivers'][0][8],1)

    def test_consent_facts_do_not_retain_profile_text_on_withdrawal(self):
        self.approved_profile();base.analytics.withdraw_profiling_consent('synthetic-a')
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_fields'),[])
        self.assertEqual(self.rows('SELECT * FROM caregiver_profile_suggestions'),[])
        events=[r[0] for r in self.rows('SELECT event FROM reporting_facts')]
        self.assertIn('profile_accepted',events);self.assertIn('consent_withdrawn',events)
        self.assertEqual(self.snapshot()['caregivers'],[])

    def test_edited_profile_outcome_is_distinct(self):
        self.grant();sid=base.analytics.propose_profile_field('synthetic-a','support_needs','Peer support')
        base.analytics.save_pending_profile_edit('synthetic-a',sid,'Evening peer support')
        base.analytics.confirm_pending_profile_edit('synthetic-a',sid)
        self.assertIn(('profile_edited',),self.rows('SELECT event FROM reporting_facts'))

    def test_legacy_consent_not_exported(self):
        self.approved_profile()
        self.rows("UPDATE caregiver_profiling_consent SET consent_version='careconnect-profiling-v1'")
        self.assertEqual(self.snapshot()['caregivers'],[])
        self.assertEqual(self.snapshot()['fields'],[])

    def test_unsafe_legacy_profile_text_is_omitted_at_export_boundary(self):
        self.approved_profile()
        self.rows("UPDATE caregiver_profile_fields SET field_value='Call +65 9123 4567'")
        report=self.snapshot()
        self.assertIsNone(report['caregivers'][0][4])
        with data.permission_guard(report):pass
        self.assertTrue(any('privacy validation' in s for s in report['warnings']))

    def test_legacy_permission_can_be_renewed_through_profile_screen(self):
        self.approved_profile()
        self.rows("UPDATE caregiver_profiling_consent SET consent_version='careconnect-profiling-v1'")
        base.database.update_user('synthetic-a',state='profile_menu')
        prompt=base.handlers.handle_message('synthetic-a','2')
        self.assertIn('administrators',prompt)
        base.handlers.handle_message('synthetic-a','1')
        self.assertEqual(self.rows('SELECT consent_version FROM caregiver_profiling_consent')[0][0],'careconnect-profiling-v2-reports')
        self.assertEqual(len(self.snapshot()['caregivers']),1)

    def test_profile_continue_ai_chat_records_entry(self):
        base.database.update_user('synthetic-a',state='profile_menu')
        base.handlers.handle_message('synthetic-a','5')
        self.assertIn(('ai_chat_started',),self.rows('SELECT event_type FROM usage_events'))

    def test_permission_guard_blocks_stale_withdrawal_regrant_and_edits(self):
        self.approved_profile();old=self.snapshot()
        base.analytics.withdraw_profiling_consent('synthetic-a');self.approved_profile()
        with self.assertRaises(PermissionError):
            with data.permission_guard(old):pass
        current=self.snapshot()
        self.rows("UPDATE caregiver_profile_fields SET field_value='Evening peer support'")
        with self.assertRaises(PermissionError):
            with data.permission_guard(current):pass

    def test_network_transfer_never_holds_profile_consent_locks(self):
        self.approved_profile();report=self.snapshot();errors=[]
        def withdraw():
            try:base.analytics.withdraw_profiling_consent('synthetic-a')
            except Exception as error:errors.append(type(error).__name__)
        with data.permission_guard(report):
            thread=threading.Thread(target=withdraw);thread.start();thread.join(2)
            self.assertFalse(thread.is_alive(),'Withdrawal must not wait on external network work')
        self.assertEqual(errors,[])

    def test_withdrawal_during_upload_cancels_before_document_send(self):
        self.approved_profile();self.login()
        with patch.object(jobs,'wake_worker'):jobs.request_report('6500000001','7','Synthetic-PassCase',{'6500000001'})
        def upload(path):
            base.analytics.withdraw_profiling_consent('synthetic-a');return '123456'
        with patch.object(whatsapp,'upload_document',side_effect=upload),patch.object(whatsapp,'send_document') as send,patch.object(whatsapp,'delete_media') as delete:
            jobs.process_one();send.assert_not_called();delete.assert_called_once_with('123456')
        self.assertEqual(self.rows('SELECT status FROM reporting_jobs')[0][0],'cancelled')

    def test_search_outcomes_are_explicit_and_nonnegative(self):
        self.grant();tracking.record_search('synthetic-a',False);tracking.record_search('synthetic-a',True)
        row=self.snapshot()['caregivers'][0]
        self.assertEqual(row[11:14],[2,1,1])

    def test_token_formats_failures_and_missing_cache(self):
        responses=SimpleNamespace(model='synthetic-model',usage=SimpleNamespace(input_tokens=100,input_tokens_details=SimpleNamespace(cached_tokens=20),output_tokens=30))
        chat=SimpleNamespace(model='synthetic-model',usage=SimpleNamespace(prompt_tokens=80,prompt_tokens_details=SimpleNamespace(cached_tokens=0),completion_tokens=10))
        for response in [responses,chat,SimpleNamespace(usage=None)]:tracking.feature_call('Translation',Mock(return_value=response),model='synthetic-model')
        with self.assertRaises(RuntimeError):tracking.feature_call('AI Chat',Mock(side_effect=RuntimeError('private provider detail')),model='synthetic-model')
        rows=self.rows('SELECT outcome,input_tokens,cached_tokens,output_tokens FROM reporting_ai ORDER BY occurred_at')
        self.assertEqual(rows[0],('completed',100,20,30));self.assertEqual(rows[1],('completed',80,0,10))
        self.assertEqual(rows[2],('unknown',None,None,None));self.assertEqual(rows[3],('failed',None,None,None))

    def test_unapproved_number_and_wrong_case_pin_denied(self):
        self.assertEqual(auth.login('synthetic-b','Synthetic-PassCase','Synthetic-PassCase',{'6500000001'}),'denied')
        self.assertEqual(auth.login('6500000001','synthetic-passcase','Synthetic-PassCase',{'6500000001'}),'incorrect')
        self.assertFalse(auth.session_valid('6500000001','Synthetic-PassCase',{'6500000001'}))

    def test_rate_limit_is_per_sender_and_cannot_be_reset_by_login_command(self):
        for _ in range(5):self.assertEqual(auth.login('6500000001','wrong','Synthetic-PassCase',{'6500000001'}),'incorrect')
        self.assertEqual(self.login(),'locked')

    def test_expiry_pin_rotation_number_removal_and_logout(self):
        self.assertEqual(self.login(),'ok');self.assertTrue(auth.session_valid('6500000001','Synthetic-PassCase',{'6500000001'}))
        self.assertFalse(auth.session_valid('6500000001','Changed-PIN',{'6500000001'}))
        self.assertFalse(auth.session_valid('6500000001','Synthetic-PassCase',set()))
        self.rows("UPDATE reporting_admin_sessions SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second'")
        self.assertFalse(auth.session_valid('6500000001','Synthetic-PassCase',{'6500000001'}))
        self.login();auth.logout('6500000001')
        self.assertFalse(auth.session_valid('6500000001','Synthetic-PassCase',{'6500000001'}))

    def test_period_validation_singapore_and_boundaries(self):
        start,end=data.parse_period('7',self.now)
        self.assertEqual((end-start).days,6)
        for text in ['garbage','01-11-2026 01-10-2026','01-01-2020 01-03-2020','01-01-2099 02-01-2099']:
            with self.assertRaises(ValueError):data.parse_period(text,self.now)
        self.assertIsNotNone(data.timestamp('2026-11-07 12:34:56.1+00'))
        self.assertIsNotNone(data.timestamp('2026-11-07'))

    def test_provider_status_deduplicates_read_and_delivered(self):
        self.rows("INSERT INTO reporting_outgoing(attempt_id,provider_id,kind,outcome) VALUES('one','wamid.synthetic','text','accepted')")
        for state in ['read','delivered','delivered','sent']:
            tracking.record_status({'id':'wamid.synthetic','status':state,'timestamp':str(int(self.now.timestamp())),'pricing':{'category':'utility','billable':True,'pricing_model':'PMP'}})
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reporting_statuses')[0][0],3)
        today=self.snapshot()['daily'][self.today]
        self.assertEqual([today[x] for x in ['outgoing','delivered','read']],[1,1,1])

    def test_queue_authorisation_and_duplicate_requests(self):
        with self.assertRaises(PermissionError):jobs.request_report('synthetic-b','7','Synthetic-PassCase',{'6500000001'})
        self.login()
        with patch.object(jobs,'wake_worker'):
            self.assertIn('queued',jobs.request_report('6500000001','7','Synthetic-PassCase',{'6500000001'}))
            self.assertIn('already',jobs.request_report('6500000001','30','Synthetic-PassCase',{'6500000001'}))
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reporting_jobs')[0][0],1)

    def test_complete_job_builds_xlsx_delivers_only_to_requester_and_cleans_local_file(self):
        self.approved_profile();tracking.record_activity('synthetic-a','one');self.login();paths=[]
        with patch.object(jobs,'wake_worker'):jobs.request_report('6500000001','7','Synthetic-PassCase',{'6500000001'})
        def upload(path):
            self.assertTrue(path.is_file());paths.append(path)
            with __import__('zipfile').ZipFile(path) as z:self.assertIn('xl/workbook.xml',z.namelist())
            return '123456'
        with patch.object(whatsapp,'upload_document',side_effect=upload),patch.object(whatsapp,'send_document',return_value='wamid.report') as send:
            self.assertTrue(jobs.process_one())
        self.assertEqual(send.call_args[0][0],'6500000001')
        self.assertIn('last7d.xlsx',send.call_args[0][2]);self.assertFalse(paths[0].exists())
        self.assertEqual(self.rows('SELECT status FROM reporting_jobs')[0][0],'sent')

    def test_send_timeout_requires_review_and_never_auto_resends(self):
        self.login()
        with patch.object(jobs,'wake_worker'):jobs.request_report('6500000001','7','Synthetic-PassCase',{'6500000001'})
        with patch.object(whatsapp,'upload_document',return_value='123456'),patch.object(whatsapp,'send_document',side_effect=RuntimeError('unknown')) as send:
            jobs.process_one();jobs.process_one()
        self.assertEqual(send.call_count,1)
        self.assertEqual(self.rows('SELECT status FROM reporting_jobs')[0][0],'review')

    def test_removed_admin_job_cancelled_before_upload(self):
        self.login()
        with patch.object(jobs,'wake_worker'):jobs.request_report('6500000001','7','Synthetic-PassCase',{'6500000001'})
        with patch.dict(os.environ,{'ADMIN_PHONE_NUMBERS':''}),patch.object(whatsapp,'upload_document') as upload:
            jobs.process_one();upload.assert_not_called()
        self.assertEqual(self.rows('SELECT status FROM reporting_jobs')[0][0],'cancelled')

    def test_job_restart_recovers_building_but_not_ambiguous_sending(self):
        self.login()
        with patch.object(jobs,'wake_worker'):jobs.request_report('6500000001','7','Synthetic-PassCase',{'6500000001'})
        self.rows("UPDATE reporting_jobs SET status='sending'")
        with patch.object(whatsapp,'send_document') as send:jobs.process_one();send.assert_not_called()
        self.assertEqual(self.rows('SELECT status FROM reporting_jobs')[0][0],'review')

    def test_workbook_rates_formula_cache_and_no_phone_or_mock_records(self):
        self.approved_profile();tracking.record_activity('synthetic-a','one')
        tracking.feature_call('AI Chat',Mock(return_value=SimpleNamespace(model='synthetic-model',usage=SimpleNamespace(input_tokens=100,cached_tokens=0,input_tokens_details=SimpleNamespace(cached_tokens=20),output_tokens=30))),model='synthetic-model')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.xlsx';excel.build_report(self.snapshot(),path);book=excel.Book(path)
            self.assertEqual(book.value('AI usage','F8'),100)
            self.assertEqual(book.value('AI usage','M8'),'')
            for cell,value in [('J8',1),('K8',0.1),('L8',2)]:book.set('AI usage',cell,value)
            book.memo.clear();self.assertAlmostEqual(book.value('AI usage','M8'),0.000142)
            book.save(path)
            with __import__('zipfile').ZipFile(path) as z:
                contents=b''.join(z.read(n) for n in z.namelist() if n.endswith('.xml'))
                self.assertNotIn(b'synthetic-a',contents);self.assertNotIn(b'6500000001',contents)
                self.assertNotIn(b'Demo model A',contents);self.assertNotIn(b'#REF!',contents)

    def test_formula_injection_stays_literal_and_large_caregiver_table_expands(self):
        result=self.snapshot()
        result['caregivers']=[['CC-test-'+str(i),'granted','=HYPERLINK("https://bad.example")',None,None,None,None,None,0,0,0,0,0,0,0,0,0,0] for i in range(240)]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.xlsx';excel.build_report(result,path);book=excel.Book(path)
            self.assertIsNone(book.cell('Caregiver summary','D9').find(excel.tag('f')))
            self.assertEqual(book.value('Caregiver summary','B248'),'CC-test-239')
            self.assertEqual(book.value('Caregiver summary','C6'),240)

    def test_admin_menu_report_path_and_expired_session(self):
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({'6500000001'})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PassCase'),patch.object(jobs,'wake_worker'):
            base.handlers.handle_message('6500000001','admin login')
            self.assertIn('successful',base.handlers.handle_message('6500000001','Synthetic-PassCase'))
            self.assertIn('last 7 days',base.handlers.handle_message('6500000001','4'))
            self.assertIn('queued',base.handlers.handle_message('6500000001','7'))
            self.assertIn('Queued',base.handlers.handle_message('6500000001','report status'))
            self.rows("UPDATE reporting_admin_sessions SET expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second'")
            self.assertIn('expired',base.handlers.handle_message('6500000001','4'))

    def test_webhook_status_signature_and_duplicate_receipts(self):
        import hmac,json
        payload={'entry':[{'changes':[{'value':{'statuses':[{'id':'wamid.test','status':'delivered','timestamp':str(int(self.now.timestamp()))}]}}]}]}
        raw=json.dumps(payload).encode();signature='sha256='+hmac.new(b'synthetic-secret',raw,hashlib.sha256).hexdigest()
        with patch.dict(os.environ,{'WHATSAPP_APP_SECRET':'synthetic-secret'}),patch.object(jobs,'wake_worker'):
            client=base.web.app.test_client()
            self.assertEqual(client.post('/webhook',data=raw,content_type='application/json').status_code,403)
            for _ in range(2):self.assertEqual(client.post('/webhook',data=raw,content_type='application/json',headers={'X-Hub-Signature-256':signature}).status_code,200)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM reporting_statuses')[0][0],1)

    def test_send_records_provider_id_and_timeout_unknown(self):
        import requests
        response=Mock(ok=True);response.json.return_value={'messages':[{'id':'wamid.synthetic-send'}]}
        with patch.object(whatsapp,'ACCESS_TOKEN','synthetic-token'),patch.object(whatsapp,'PHONE_NUMBER_ID','synthetic-phone'),patch.object(whatsapp.requests,'post',return_value=response):
            self.assertEqual(whatsapp.send_message('6500000001','Synthetic reply'),'wamid.synthetic-send')
        self.assertEqual(self.rows('SELECT outcome,provider_id FROM reporting_outgoing'),[('accepted','wamid.synthetic-send')])
        with patch.object(whatsapp,'ACCESS_TOKEN','synthetic-token'),patch.object(whatsapp,'PHONE_NUMBER_ID','synthetic-phone'),patch.object(whatsapp.requests,'post',side_effect=requests.Timeout):
            with self.assertRaises(RuntimeError):whatsapp.send_message('6500000001','Synthetic reply')
        self.assertEqual(self.rows("SELECT COUNT(*) FROM reporting_outgoing WHERE outcome='unknown'")[0][0],1)

    def test_all_ai_calls_are_instrumented(self):
        import ast
        for filename in ['chatbot.py','handlers.py','profile_suggestions.py']:
            tree=ast.parse((base.ROOT/filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='create':
                    self.fail(f'Uninstrumented AI call in {filename}:{node.lineno}')

    def test_incompatible_reporting_column_preflight_fails_without_deleting_records(self):
        self.rows('ALTER TABLE reporting_ai ALTER COLUMN service_tier TYPE VARCHAR(40)')
        with self.assertRaises(Exception):self.rows((base.ROOT/'phase3_schema.sql').read_text())
        self.assertEqual(self.rows('SELECT COUNT(*) FROM users')[0][0],3)
        self.rows('ALTER TABLE reporting_ai ALTER COLUMN service_tier TYPE TEXT')

    def test_singapore_midnight_boundary_and_heatmap_denominator(self):
        self.grant()
        person=self.rows('SELECT report_id FROM reporting_people WHERE sender=%s',('synthetic-a',))[0][0]
        start=self.today-timedelta(days=6)
        from datetime import time
        boundary=datetime.combine(start,time.min,data.SGT)
        for key,stamp in [('before',boundary-timedelta(seconds=1)),('on',boundary),('after',boundary+timedelta(minutes=1))]:
            self.rows('INSERT INTO reporting_activity(message_hash,report_id,occurred_at) VALUES(%s,%s,%s)',(key,person,stamp))
        result=self.snapshot();self.assertEqual(result['periods'][1][1],1)
        self.assertEqual(result['heat'][start.weekday()][0],1)

    def test_empty_report_has_known_zero_counts_but_unknown_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.xlsx';excel.build_report(self.snapshot(),path);book=excel.Book(path)
            self.assertEqual(book.value('Caregiver summary','C6'),0)
            self.assertEqual(book.value('Messages & costs','G25'),0)
            self.assertEqual(book.value('Messages & costs','C43'),'')

    def test_native_chart_caches_and_seven_day_range_are_populated(self):
        from zipfile import ZipFile
        from xml.etree import ElementTree as E
        with patch.dict(os.environ,{'CARECONNECT_TEST_DATABASE':'true'}):
            first=fixtures.run('seed30')
            try:
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'chart-report.xlsx';excel.build_report(self.snapshot(),path)
                    with ZipFile(path) as archive:
                        charts=[n for n in archive.namelist() if '/charts/chart' in n and n.endswith('.xml')]
                        self.assertEqual(len(charts),7)
                        ns={'c':excel.CNS}
                        daily=E.fromstring(archive.read(charts[0]))
                        self.assertTrue(all(e.get('val')=='7' for e in daily.findall('.//c:ptCount',ns)))
                        self.assertTrue(all(e.text.endswith('137') for e in daily.findall('.//c:f',ns)))
                        self.assertEqual(len(daily.findall('.//c:numCache/c:pt',ns)),14)
                        for name in charts:
                            chart=E.fromstring(archive.read(name))
                            self.assertGreater(len(chart.findall('.//c:pt',ns)),0)
                            self.assertTrue(all(e.get('val')=='0' for e in chart.findall('.//c:valAx/c:scaling/c:min',ns)))
            finally:fixtures.run('cleanup',first['run_id'])

    def test_fixture_batches_30_then_20_and_scoped_cleanup(self):
        with self.assertRaises(PermissionError):fixtures.run('seed30')
        with patch.dict(os.environ,{'CARECONNECT_TEST_DATABASE':'true'}):
            first=fixtures.run('seed30')
            self.assertEqual(len(first['records']),30)
            self.assertEqual(first['expected7d']['caregivers_active'],7)
            result=self.snapshot()
            self.assertEqual(result['periods'][1][1],7)
            self.assertEqual(sum(v['requests'] for d,v in result['daily'].items() if d>=result['start']),7)
            second=fixtures.run('add20',first['run_id'])
            self.assertEqual(second['expected30d']['caregivers_active'],50)
            result=data.snapshot(self.today-timedelta(days=29),self.today,excluded={'6500000001'})
            self.assertEqual(result['periods'][1][1],50)
            self.assertEqual(sum(r[3] for r in result['ai']),62250)
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'fixture.xlsx';excel.build_report(result,path);book=excel.Book(path)
                self.assertEqual(book.value('Caregiver summary','C6'),50)
                self.assertEqual(book.value('Messages & costs','D20'),62250)
                self.assertEqual(book.value('Messages & costs','C10'),50)
            fixtures.run('cleanup',first['run_id'])
            self.assertEqual(self.rows('SELECT COUNT(*) FROM users')[0][0],3)
            self.assertEqual(self.rows('SELECT COUNT(*) FROM reporting_ai')[0][0],0)
            self.assertEqual(self.rows("SELECT COUNT(*) FROM reporting_settings WHERE key='synthetic_test_start'")[0][0],0)

    def test_retention_dry_run_and_apply_preserve_recent_records(self):
        import phase3_manage
        self.rows("INSERT INTO whatsapp_receipts(message_hash,status,received_at) VALUES('expired','completed',CURRENT_TIMESTAMP-INTERVAL '4 years'),('recent','completed',CURRENT_TIMESTAMP)")
        with patch.object(phase3_manage,'get_connection',base.connect),patch('builtins.print'),patch('sys.argv',['phase3_manage.py','retention']):phase3_manage.main()
        self.assertEqual(self.rows('SELECT COUNT(*) FROM whatsapp_receipts')[0][0],2)
        with patch.object(phase3_manage,'get_connection',base.connect),patch('builtins.print'),patch('sys.argv',['phase3_manage.py','retention','--apply']):phase3_manage.main()
        self.assertEqual(self.rows('SELECT message_hash FROM whatsapp_receipts'),[('recent',)])

    def test_automatic_retention_expires_records_once_and_preserves_accounts(self):
        import retention
        self.rows("DELETE FROM reporting_settings WHERE key='retention_last_success'")
        self.rows("INSERT INTO whatsapp_receipts(message_hash,status,received_at) VALUES('old','completed',CURRENT_TIMESTAMP-INTERVAL '3 years'-INTERVAL '1 day'),('young','completed',CURRENT_TIMESTAMP-INTERVAL '3 years'+INTERVAL '1 day')")
        self.approved_profile()
        self.rows("UPDATE caregiver_profile_fields SET updated_at=CURRENT_TIMESTAMP-INTERVAL '4 years'")
        people=self.rows('SELECT * FROM users ORDER BY sender')
        with patch.object(retention,'get_connection',base.connect):
            counts=retention.cleanup_if_due()
            self.assertEqual(counts['whatsapp_receipts'],1)
            self.assertEqual(counts['caregiver_profile_fields'],1)
            self.assertIsNone(retention.cleanup_if_due())
        self.assertEqual(self.rows('SELECT message_hash FROM whatsapp_receipts'),[('young',)])
        self.assertEqual(self.rows('SELECT * FROM users ORDER BY sender'),people)
        self.assertEqual(self.rows('SELECT status FROM caregiver_profiling_consent'),[('granted',)])

    def test_automatic_retention_failure_rolls_back_and_remains_due(self):
        import retention
        self.rows("DELETE FROM reporting_settings WHERE key='retention_last_success'")
        self.rows("INSERT INTO whatsapp_receipts(message_hash,status,received_at) VALUES('old','completed',CURRENT_TIMESTAMP-INTERVAL '4 years')")
        with patch.object(retention,'get_connection',base.connect),patch.object(retention,'RETENTION',{'whatsapp_receipts':'received_at','missing_retention_table':'created_at'}):
            with self.assertRaises(Exception):retention.cleanup_if_due()
        self.assertEqual(self.rows('SELECT COUNT(*) FROM whatsapp_receipts')[0][0],1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM reporting_settings WHERE key='retention_last_success'")[0][0],0)

    def test_automatic_retention_lock_and_restart_catchup(self):
        import retention
        self.rows("DELETE FROM reporting_settings WHERE key='retention_last_success'")
        connection=base.connect()
        try:
            with connection.cursor() as cur:cur.execute('SELECT pg_advisory_xact_lock(301,307)')
            with patch.object(retention,'get_connection',base.connect):
                self.assertIsNone(retention.cleanup_if_due())
                connection.rollback()
                self.assertIsNotNone(retention.cleanup_if_due())
                self.rows("UPDATE reporting_settings SET value=CURRENT_TIMESTAMP-INTERVAL '2 days' WHERE key='retention_last_success'")
                self.assertIsNotNone(retention.cleanup_if_due())
        finally:connection.close()

    def test_automatic_retention_disabled_and_failure_retry(self):
        import retention
        with patch.dict(os.environ,{'RETENTION_ENABLED':'false'}),patch.object(retention.threading,'Thread') as start:
            retention.wake_cleanup();start.assert_not_called()
        with patch.object(retention,'cleanup_if_due',side_effect=RuntimeError('synthetic')),patch.object(retention,'_next_check',0),patch.object(retention.time,'monotonic',return_value=100):
            retention._run();self.assertEqual(retention._next_check,160)

    def test_full_second_batch_covers_every_report_input_and_cleans_all_extra_records(self):
        baseline=data.snapshot(self.today-timedelta(days=29),self.today,excluded={'6500000001'})
        with patch.dict(os.environ,{'CARECONNECT_TEST_DATABASE':'true'}):
            first=fixtures.run('seed30')
            full=fixtures.run('add20',first['run_id'],full_cases=True)
            try:
                expected=full['expected30d'];previous=full['expected_previous30d']
                self.assertEqual(expected['caregivers_active'],50)
                self.assertEqual(expected['new_users'],36)
                self.assertEqual(expected['returning_users'],11)
                self.assertEqual(expected['unknown_first_seen_active'],3)
                self.assertEqual(expected['permitted_profile_rows'],47)
                self.assertEqual(expected['profile_accepted'],1);self.assertEqual(expected['profile_edited'],1);self.assertEqual(expected['profile_rejected'],1)
                report=data.snapshot(self.today-timedelta(days=29),self.today,excluded={'6500000001'})
                self.assertEqual(report['periods'][1][1],50)
                self.assertEqual(report['periods'][1][2]-baseline['periods'][1][2],36)
                self.assertEqual(report['periods'][1][3],11)
                self.assertEqual(report['periods'][0][1],previous['caregivers_active'])
                self.assertEqual(len(report['caregivers']),47)
                self.assertTrue(all(value>0 for row in report['heat'] for value in row))
                self.assertTrue(all(value>0 for row in report['buddy_heat'] for value in row))
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'coverage.xlsx';excel.build_report(report,path);book=excel.Book(path)
                    cells={('Dashboard','B8'):'caregivers_active',('Services','D8'):'ai_chat_entries',('Services','D9'):'resource_visits',('Services','D10'):'completed_searches',('Services','D11'):'matching_previews',('Services','D13'):'applications_submitted',('Services','D14'):'profile_accepted',('Services','D15'):'profile_edited',('Services','D16'):'profile_rejected',('Buddy programme','C20'):'requests_sent',('Buddy programme','C21'):'accepted',('Buddy programme','C22'):'declined',('Buddy programme','C23'):'pending',('Buddy programme','C29'):'searches_no_preview',('Caregiver summary','C6'):'permitted_profile_rows',('Caregiver summary','J6'):'summary_user_days',('Messages & costs','C8'):'received_messages',('Messages & costs','C9'):'outgoing_messages',('Messages & costs','C10'):'delivered_messages',('Messages & costs','C11'):'failed_messages',('Messages & costs','C12'):'read_messages',('Messages & costs','C13'):'unconfirmed_sends'}
                    for (sheet,address),key in cells.items():self.assertEqual(book.value(sheet,address),expected.get(key,0),(sheet,address,key))
                    for address,key in [('D12','buddy_application_started'),('D24','consent_granted'),('D25','consent_declined'),('D26','consent_withdrawn')]:self.assertEqual(book.value('Services',address),expected[key])
                    for address,key in [('C8','buddy_application_started'),('C9','applications_submitted'),('C10','application_approved'),('C11','application_rejected'),('C12','application_pending')]:self.assertEqual(book.value('Buddy programme',address),expected[key])
                    self.assertEqual(book.value('Buddy programme','C15'),1)
                    self.assertAlmostEqual(book.value('Buddy programme','C26'),17/50)
                    for i in range(4):self.assertEqual(book.value('Services',f'C{38+i}'),expected['resource_categories'][str(i+1)])
                    self.assertEqual(book.value('Services','C8'),previous['ai_chat_entries'])
                    for i,category in enumerate(['service','utility','marketing','authentication']):self.assertEqual(book.value('Messages & costs',f'C{30+i}'),expected['billable_categories'][category])
                    self.assertEqual(book.value('Messages & costs','C36'),0)
                    self.assertEqual(book.value('Messages & costs','G25'),'')
                    self.assertEqual(book.value('Messages & costs','C43'),'')
                    for i in range(8,60):
                        row=[book.value('AI usage',f'{column}{i}') for column in 'BCDEFGHI']
                        if not row[0]:continue
                        key=' | '.join(row[:3]);entry=expected['ai_groups'][key]
                        self.assertEqual(row[3:],[entry.get(k,0) for k in ['requests','input_tokens','cached_input_tokens','output_tokens','unknown_calls']])
                        for column,value in [('J',1),('K',0.1),('L',2)]:book.set('AI usage',f'{column}{i}',value)
                    book.memo.clear()
                    self.assertEqual(book.value('Messages & costs','G25'),'','Unknown calls must keep the total unavailable even with all rates entered')
            finally:fixtures.run('cleanup',first['run_id'])
        for table in ['reporting_ai','reporting_activity','reporting_facts','reporting_outgoing','reporting_statuses','whatsapp_receipts','match_requests','support_buddy_applications']:
            self.assertEqual(self.rows(f'SELECT COUNT(*) FROM {table}')[0][0],0,table)
        self.assertEqual(self.rows('SELECT COUNT(*) FROM users')[0][0],3)

    def test_known_billing_categories_remain_visible_when_another_delivery_is_unclassified(self):
        for i in range(2):self.rows("INSERT INTO reporting_outgoing(attempt_id,provider_id,kind,outcome) VALUES(%s,%s,'text','accepted')",(str(i),'billing-'+str(i)))
        self.rows("INSERT INTO reporting_statuses(provider_id,status,occurred_at,category,billable,pricing_model) VALUES('billing-0','delivered',CURRENT_TIMESTAMP,'utility',true,'PMP'),('billing-1','delivered',CURRENT_TIMESTAMP,NULL,NULL,NULL)")
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'billing.xlsx';excel.build_report(self.snapshot(),path);book=excel.Book(path)
            self.assertEqual(book.value('Messages & costs','C31'),1)
            self.assertEqual(book.value('Messages & costs','C36'),1)
            book.set('Controls','C15',0.05);book.memo.clear()
            self.assertEqual(book.value('Messages & costs','E31'),0.05)
            self.assertEqual(book.value('Messages & costs','E34'),'')

    def test_custom_31_day_comparison_preserves_all_62_daily_rows(self):
        start=self.today-timedelta(days=30);previous_last=start-timedelta(days=1)
        for stamp in [previous_last,self.today]:
            from datetime import time
            self.rows("INSERT INTO usage_events(sender,event_type,occurred_at) VALUES('synthetic-a','ai_chat_started',%s)",(datetime.combine(stamp,time(12),data.SGT),))
        report=data.snapshot(start,self.today,excluded={'6500000001'})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'custom31.xlsx';excel.build_report(report,path);book=excel.Book(path)
            self.assertEqual(book.value('Sample data','B43'),excel.serial(previous_last))
            self.assertEqual(book.value('Sample data','B44'),excel.serial(start))
            self.assertEqual(book.value('Sample data','B74'),excel.serial(self.today))
            self.assertEqual(book.value('Services','C8'),1)
            self.assertEqual(book.value('Services','D8'),1)

    def test_preflight_rolls_back_and_preserves_ids(self):
        import phase3_manage
        before=self.rows('SELECT report_id FROM reporting_people ORDER BY sender')
        with patch.object(phase3_manage,'get_connection',base.connect),patch('builtins.print'),patch('sys.argv',['phase3_manage.py','preflight']):phase3_manage.main()
        self.assertEqual(self.rows('SELECT report_id FROM reporting_people ORDER BY sender'),before)

if __name__=='__main__':unittest.main()
