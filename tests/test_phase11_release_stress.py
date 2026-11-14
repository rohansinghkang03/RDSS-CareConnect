"""Role journeys, adversarial inputs and concurrent operations on isolated data only."""
import unittest,concurrent.futures
from unittest.mock import patch
import test_phase2 as base
import test_phase5_match_chat as p5
import test_phase10_basic_profile as p10
import basic_profile as bp
import buddy_directory as directory
import connection_requests as cr
import match_chat_store as store

class ReleaseStressTests(unittest.TestCase):
    rows=p10.BasicProfileTests.rows
    profile=p10.BasicProfileTests.profile
    setUpClass=classmethod(base.Phase2Tests.setUpClass.__func__)
    tearDownClass=classmethod(base.Phase2Tests.tearDownClass.__func__)
    migrate=staticmethod(base.Phase2Tests.migrate)
    setUp=p10.BasicProfileTests.setUp
    def prepare_request(self):
        directory.show(p5.CARE,fresh=True);directory.select(p5.CARE,1)
        cr.begin(p5.CARE);cr.save(p5.CARE,'message','A synthetic listening request.');cr.review(p5.CARE)
    def test_personal_greeting_preserves_all_options_and_private_name(self):
        reply=base.handlers.handle_message(p5.CARE,'menu')
        self.assertIn('Hello Synthetic Caregiver!',reply)
        for i in range(1,9):self.assertIn(str(i)+'.',reply)
        self.assertNotIn('Private real name',reply)
    def test_complete_application_verification_and_approval_use_separate_real_name(self):
        self.profile(p5.OTHER,'Public Nickname','Malay|English')
        base.database.update_user(p5.OTHER,state='main_menu')
        reply=base.handlers.handle_message(p5.OTHER,'4')
        self.assertIn('full name',reply.lower())
        for answer in ['Private Verification Name','2','3','1,2','3','1','I enjoy listening to fellow caregivers.']:
            reply=base.handlers.handle_message(p5.OTHER,answer)
        self.assertIn('Public Nickname',reply);self.assertIn('Private Verification Name',reply)
        self.assertIn('Continue to consent',reply)
        base.handlers.handle_message(p5.OTHER,'1');base.handlers.handle_message(p5.OTHER,'1')
        app=base.database.get_support_buddy_application(p5.OTHER)
        self.assertEqual(app['status'],'pending');self.assertEqual(app['display_name'],'Public Nickname')
        self.assertEqual(app['full_name'],'Private Verification Name');self.assertEqual(app['languages'],'Malay|English')
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({p5.OUT})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PIN'):
            base.handlers.handle_message(p5.OUT,'admin login');base.handlers.handle_message(p5.OUT,'Synthetic-PIN')
            base.handlers.handle_message(p5.OUT,'1');reply=base.handlers.handle_message(p5.OUT,'1')
            self.assertNotIn('1. Approve',reply)
            base.handlers.handle_message(p5.OUT,'3');base.handlers.handle_message(p5.OUT,'Synthetic Administrator')
            reply=base.handlers.handle_message(p5.OUT,'1');self.assertIn('1. Approve',reply)
            base.handlers.handle_message(p5.OUT,'1')
        self.assertEqual(base.database.get_support_buddy_application(p5.OTHER)['status'],'approved')
        listing=directory.show(p5.CARE,fresh=True)
        self.assertIn('Public Nickname',listing);self.assertNotIn('Private Verification Name',listing)
    def test_both_sides_see_names_and_chat_after_single_acceptance(self):
        self.prepare_request();base.database.create_selected_match_request(p5.CARE)
        rid=self.rows('SELECT id FROM match_requests')[0][0]
        incoming=base.handlers.handle_message(p5.BUD,'requests')
        self.assertIn('Synthetic Caregiver',incoming);self.assertIn('synthetic listening request',incoming)
        base.handlers.handle_message(p5.BUD,'accept '+str(rid))
        for sender,expected in [(p5.CARE,'Synthetic Buddy'),(p5.BUD,'Synthetic Caregiver')]:
            reply=base.handlers.handle_message(sender,'chat '+str(rid)+'.')
            self.assertIn(expected,reply);self.assertNotIn('Private real name',reply)
            self.assertEqual(store.inspect(sender,rid)['state'],'ready')
        self.profile(p5.CARE,'Updated Caregiver','English|Malay')
        self.assertEqual(store.inspect(p5.BUD,rid)['partner_label'],'Updated Caregiver')
    def test_duplicate_confirmation_and_acceptance_stress_are_idempotent(self):
        self.prepare_request()
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results=list(pool.map(lambda _:base.database.create_selected_match_request(p5.CARE),range(48)))
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests')[0][0],1)
        rid=self.rows('SELECT id FROM match_requests')[0][0]
        cr.show_accept_notice(p5.BUD,rid)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            results=list(pool.map(lambda _:base.database.respond_to_buddy_request(p5.BUD,rid,'accepted'),range(48)))
        self.assertEqual(self.rows("SELECT count(*) FROM match_requests WHERE status='accepted'")[0][0],1)
        self.assertEqual(self.rows('SELECT count(*) FROM match_chat_permissions')[0][0],2)
    def test_rejection_and_withdrawal_do_not_release_numbers(self):
        self.prepare_request();base.database.create_selected_match_request(p5.CARE)
        rid=self.rows('SELECT id FROM match_requests')[0][0]
        base.handlers.handle_message(p5.BUD,'decline '+str(rid))
        with self.assertRaises(PermissionError):store.authorize_delivery(p5.CARE,rid)
        self.assertEqual(base.handlers.find_matches(base.database.get_user(p5.CARE)),[])
    def test_adversarial_names_languages_and_unknown_choices_do_not_corrupt_data(self):
        original=bp.get(p5.CARE)
        bp.begin(p5.CARE)
        for message in ['1.','6599990000','user@example.com','https://example.com','x'*1000]:
            base.handlers.handle_message(p5.CARE,message)
            self.assertEqual(bp.get(p5.CARE),original)
            self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_name')
        base.handlers.handle_message(p5.CARE,'help')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_name')
        self.assertEqual(bp.get(p5.CARE),original)
    def test_language_switches_preserve_new_form_and_directory_steps(self):
        bp.begin(p5.CARE);base.handlers.handle_message(p5.CARE,'Synthetic Caregiver')
        for language in ['Malay','English','Mandarin','Tamil']:
            base.handlers.handle_message(p5.CARE,'please reply in '+language)
            self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_languages')
            self.assertEqual(bp.get(p5.CARE)['chat_languages'],'English|Malay')
        directory.show(p5.CARE,fresh=True);directory.select(p5.CARE,1)
        base.handlers.handle_message(p5.CARE,'please reply in English')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'directory_detail')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
    def test_withdrawal_directions_point_to_ai_privacy_inside_shared_profile(self):
        text=base.handlers.profiling_consent_text()
        self.assertIn('then 4 (AI profile and privacy settings), then 3',text)
        base.handlers.handle_message(p5.CARE,'profile');base.handlers.handle_message(p5.CARE,'4')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'profile_menu')
        base.handlers.handle_message(p5.CARE,'3')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'profile_withdraw_confirm')

    def test_clean_slate_removes_user_data_and_languages_but_preserves_settings(self):
        from tools.clean_slate import clean
        c=base.connect()
        try:
            with c:
                tables=clean(c)
                self.assertIn('users',tables);self.assertIn('basic_profiles',tables)
                with c.cursor() as q:
                    q.execute('SELECT count(*) FROM reporting_settings');self.assertGreater(q.fetchone()[0],0)
        finally:c.close()
        self.assertEqual(self.rows('SELECT * FROM users'),[])
        # Admin authority is configured separately; deleting user rows cannot remove it.
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({p5.OUT})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PIN'):
            reply=base.handlers.handle_message(p5.OUT,'admin login')
            self.assertIn('PIN',reply)
            reply=base.handlers.handle_message(p5.OUT,'Synthetic-PIN')
            self.assertIn('Admin login successful',reply)

    def test_first_account_save_returns_to_personal_main_menu(self):
        self.rows('DELETE FROM basic_profiles WHERE sender=%s',(p5.CARE,))
        base.handlers.handle_message(p5.CARE,'profile')
        base.handlers.handle_message(p5.CARE,'Friendly Nickname')
        base.handlers.handle_message(p5.CARE,'1,3')
        reply=base.handlers.handle_message(p5.CARE,'1')
        self.assertIn('Hello Friendly Nickname!',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'main_menu')
