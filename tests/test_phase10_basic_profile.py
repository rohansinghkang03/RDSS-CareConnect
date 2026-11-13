"""Shared profiles and stable language-compatible lists; synthetic PostgreSQL only."""
import os,unittest
from unittest.mock import patch
import test_phase2 as base
import test_phase5_match_chat as p5
from test_phase9_local_connection_updates import LocalConnectionUpdates
import basic_profile as bp
import buddy_directory as directory

class BasicProfileTests(unittest.TestCase):
    rows=LocalConnectionUpdates.rows
    setUpClass=classmethod(base.Phase2Tests.setUpClass.__func__)
    tearDownClass=classmethod(base.Phase2Tests.tearDownClass.__func__)
    migrate=staticmethod(base.Phase2Tests.migrate)
    def setUp(self):
        LocalConnectionUpdates.setUp(self)
        self.rows((base.ROOT/'basic_profile_schema.sql').read_text())
        flag=patch.dict(os.environ,{'BASIC_PROFILE_ENABLED':'true'});flag.start();self.addCleanup(flag.stop)
        self.profile(p5.CARE,'Synthetic Caregiver','English|Malay')
        self.profile(p5.BUD,'Synthetic Buddy','Malay')
    def profile(self,sender,name,languages):
        self.rows('INSERT INTO basic_profiles(sender,display_name,chat_languages) VALUES(%s,%s,%s) ON CONFLICT(sender) DO UPDATE SET display_name=EXCLUDED.display_name,chat_languages=EXCLUDED.chat_languages',(sender,name,languages))
    def test_onboarding_other_languages_requires_explicit_save_and_does_not_change_ui(self):
        self.rows('DELETE FROM basic_profiles WHERE sender=%s',(p5.CARE,))
        reply=base.handlers.handle_message(p5.CARE,'profile');self.assertIn('call you',reply)
        base.handlers.handle_message(p5.CARE,'A New Nickname')
        reply=base.handlers.handle_message(p5.CARE,'5');self.assertIn('Please specify which languages, and type all of them',reply)
        reply=base.handlers.handle_message(p5.CARE,'English, Melayu, Hindi');self.assertIn('English, Malay, Hindi',reply)
        self.assertIsNone(bp.get(p5.CARE))
        base.handlers.handle_message(p5.CARE,'yes');self.assertIsNone(bp.get(p5.CARE))
        base.handlers.handle_message(p5.CARE,'1')
        self.assertEqual(bp.get(p5.CARE)['display_name'],'A New Nickname')
        self.assertEqual(bp.get(p5.CARE)['chat_languages'],'English|Malay|Hindi')
        self.assertEqual(base.database.get_language_preference(p5.CARE),'English')
        self.classifier.assert_not_called()
    def test_shared_name_and_languages_update_application_without_changing_approval(self):
        before=base.database.get_admin_application(self.buddy)
        bp.begin(p5.BUD);base.handlers.handle_message(p5.BUD,'Updated Buddy')
        base.handlers.handle_message(p5.BUD,'1,3');base.handlers.handle_message(p5.BUD,'1')
        app=base.database.get_admin_application(self.buddy)
        self.assertEqual(app['display_name'],'Updated Buddy');self.assertEqual(app['languages'],'English|Malay')
        for field in ['status','full_name','verified_at','verified_by','review_version','consent','consent_text']:self.assertEqual(app[field],before[field])
        self.assertEqual(base.handlers.find_matches(base.database.get_user(p5.CARE))[0]['name'],'Updated Buddy')
    def test_language_is_required_but_support_and_time_can_both_differ(self):
        self.profile(p5.CARE,'Caregiver','Malay')
        self.rows("UPDATE support_buddy_applications SET support_types='Casual conversation',availability='Morning' WHERE id=%s",(self.buddy,))
        matches=base.handlers.find_matches(base.database.get_user(p5.CARE))
        self.assertEqual(len(matches),1);self.assertEqual(matches[0]['tier'],'other')
        self.profile(p5.CARE,'Caregiver','English')
        self.assertEqual(base.handlers.find_matches(base.database.get_user(p5.CARE)),[])
        self.assertIn('No eligible buddies share',directory.show(p5.CARE,fresh=True))
    def test_list_selection_and_request_prefill_never_send_without_confirmation(self):
        reply=directory.show(p5.CARE,fresh=True);self.assertIn('Speaks Malay',reply)
        self.assertIn('Usually available',reply);self.assertIn('Prefers:',reply)
        reply=base.handlers.handle_message(p5.CARE,'1');self.assertIn('Prepare a connection request',reply)
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
        base.handlers.handle_message(p5.CARE,'1')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'match_request_message')
        self.assertEqual(self.rows('SELECT chosen_name FROM connection_request_drafts WHERE sender=%s',(p5.CARE,))[0][0],'Synthetic Caregiver')
        base.handlers.handle_message(p5.CARE,'skip');base.handlers.handle_message(p5.CARE,'1')
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests')[0][0],1)
        reply=directory.show(p5.CARE,fresh=True);self.assertIn('Request pending',reply)
        reply=base.handlers.handle_message(p5.CARE,'1');self.assertIn('still pending',reply)
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests')[0][0],1)
    def test_stable_pagination_reconsideration_and_public_name_choice(self):
        for i in range(7):
            sender='65000100'+str(10+i);base.database.create_user(sender);self.profile(sender,'Buddy '+chr(65+i),'Malay')
            self.rows("INSERT INTO support_buddy_applications(sender,display_name,languages,support_types,availability,status,consent,submitted_at,verification_required) VALUES(%s,'Old name','English','Someone to listen','Evening','approved',1,CURRENT_TIMESTAMP,0)",(sender,))
        first=directory.show(p5.CARE,fresh=True);ids=directory.session(p5.CARE)['buddy_ids']
        second=base.handlers.handle_message(p5.CARE,'more');self.assertIn('Page 2',second)
        self.assertEqual(directory.session(p5.CARE)['buddy_ids'],ids)
        again=base.handlers.handle_message(p5.CARE,'previous');self.assertIn('Page 1',again)
        detail=base.handlers.handle_message(p5.CARE,'I changed my mind, I want to speak with Synthetic Buddy')
        self.assertIn('Prepare a connection request',detail)
        base.handlers.handle_message(p5.CARE,'back')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'buddy_directory')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
    def test_changed_languages_block_stale_preview_and_schema_repeats(self):
        directory.show(p5.CARE,fresh=True);directory.select(p5.CARE,1)
        import connection_requests as cr
        cr.begin(p5.CARE);cr.save(p5.CARE,'message','A listening ear please.');cr.review(p5.CARE)
        self.profile(p5.BUD,'Synthetic Buddy','Tamil')
        with self.assertRaises(PermissionError):base.database.create_selected_match_request(p5.CARE)
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
        before=bp.get(p5.CARE)
        self.rows((base.ROOT/'basic_profile_schema.sql').read_text());self.assertEqual(bp.get(p5.CARE),before)
    def test_basic_profile_not_ai_profile_and_no_application_needed(self):
        self.assertEqual(base.analytics.get_profiling_consent(p5.CARE),'not_given')
        self.assertEqual(base.database.get_support_buddy_application(p5.CARE),None)
        reply=base.handlers.handle_message(p5.CARE,'profile');self.assertIn('My Support Buddy profile',reply)
        reply=base.handlers.handle_message(p5.CARE,'3');self.assertIn('Apply to become a Support Buddy',reply)
        self.assertEqual(base.analytics.get_profiling_consent(p5.CARE),'not_given')

    def test_language_answer_and_explicit_ui_switch_are_separate(self):
        bp.begin(p5.CARE);base.handlers.handle_message(p5.CARE,'Caregiver')
        reply=base.handlers.handle_message(p5.CARE,'please change to Malay')
        self.assertIn('Language updated',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_languages')
        self.assertEqual(bp.draft(p5.CARE)['chat_languages'],'English|Malay')
        base.handlers.handle_message(p5.CARE,'English and Melayu')
        self.assertEqual(base.database.get_language_preference(p5.CARE),'Malay')
        self.assertEqual(bp.draft(p5.CARE)['chat_languages'],'English|Malay')
        self.assertEqual(bp.language_set('Singlish Malay'),'English|Malay')
    def test_profile_and_matching_navigation_are_not_trapped_by_ai_profile(self):
        base.database.update_user(p5.CARE,state='profile_review')
        reply=base.handlers.handle_message(p5.CARE,'find support buddy')
        self.assertIn('Find a Support Buddy',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_preferences')
    def test_abandoned_admin_pin_screen_does_not_treat_greeting_as_pin(self):
        base.database.update_user(p5.CARE,state='admin_pin')
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({p5.CARE})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PIN'):
            reply=base.handlers.handle_message(p5.CARE,'hello')
        self.assertIn('expired',reply);self.assertNotIn('Incorrect PIN',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'main_menu')
    def test_directory_foreign_and_expired_selection_cannot_send(self):
        directory.show(p5.CARE,fresh=True)
        reply=directory.select(p5.BUD,1)
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
        self.rows("UPDATE buddy_list_sessions SET updated_at=CURRENT_TIMESTAMP-INTERVAL '31 minutes'")
        reply=directory.select(p5.CARE,1)
        self.assertIn('Reply with a number',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'buddy_directory')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])

    def test_ai_can_assist_with_choices_but_never_saves_profile_on_inference(self):
        import test_phase4 as p4
        base.database.update_user(p5.CARE,state='basic_support')
        self.classifier.return_value=p4.decision('local',['1'])
        base.handlers.handle_message(p5.CARE,'I just want someone to listen')
        self.assertEqual(base.database.get_user(p5.CARE)['support_type'],'Someone to listen')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_time')
        bp.begin(p5.CARE)
        base.handlers.handle_message(p5.CARE,'what does this mean?')
        self.assertEqual(bp.draft(p5.CARE)['display_name'],'Synthetic Caregiver')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_name')
    def test_shared_name_cannot_be_overridden_only_for_a_request(self):
        directory.show(p5.CARE,fresh=True);directory.select(p5.CARE,1)
        base.handlers.handle_message(p5.CARE,'1');base.handlers.handle_message(p5.CARE,'skip')
        base.handlers.handle_message(p5.CARE,'2')
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'basic_name')
        self.assertEqual(bp.draft(p5.CARE)['destination'],'request')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
