"""Regression cases from the user's actual WhatsApp feedback, synthetic only."""
import os
from unittest.mock import patch
import test_phase2 as base
import test_phase5_match_chat as p5
import admin_assist
from conversation_context import conversation,protect
from navigation_design import organize
import match_browsing as browsing

class FeedbackTests(p5.MatchChatTests):
    def admin(self,state='admin_menu'):
        base.database.update_user(p5.OUT,state=state)
        a=patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',{p5.OUT});a.start();self.addCleanup(a.stop)
        b=patch.object(base.handlers,'ADMIN_PIN','testpin');b.start();self.addCleanup(b.stop)
        c=patch('reporting_auth.session_valid',return_value=True);c.start();self.addCleanup(c.stop)

    def test_exact_reported_admin_phrases_and_monthly_clarification(self):
        self.admin()
        with patch('reporting_jobs.request_report',return_value='Report queued') as report:
            reply=base.handlers.handle_message(p5.OUT,'may i have the statistics from the last 30 days')
            self.assertIn('Report queued',reply);self.assertEqual(report.call_args.args[1],'30')
            reply=base.handlers.handle_message(p5.OUT,'may i view monthly statistics')
            self.assertIn('calendar month',reply);self.assertEqual(report.call_count,1)
            self.assertEqual(base.database.get_user(p5.OUT)['state'],'admin_report_period')
            base.handlers.handle_message(p5.OUT,'30');self.assertEqual(report.call_count,2)

    def test_notification_paraphrases_are_explicit_and_own_account_only(self):
        for message,expected in [('on notifications','on'),('turn on notifications','on'),('please switch my alerts off','off'),('enable notifications','on'),('disable alerts','off')]:
            self.assertEqual(admin_assist.resolve(message),('notifications_'+expected,None))
        for message in ["don't turn notifications on",'disable notifications on','what are notifications','turn notifications on for John']:
            self.assertIsNone(admin_assist.resolve(message))
        self.admin()
        with patch('notifications.command',return_value='Alerts are on') as command:
            self.assertIn('Alerts are on',base.handlers.handle_message(p5.OUT,'on notifications'))
            command.assert_called_once_with(p5.OUT,'notifications on')

    def test_pin_screen_has_only_cancel_commands_and_no_admin_menu_claim(self):
        self.admin('main_menu')
        reply=base.handlers.handle_message(p5.OUT,'admin login')
        body,section=reply.split('You can type these other commands too:')
        self.assertIn('Enter your admin PIN',body)
        self.assertNotIn('admin menu',body.lower());self.assertNotIn('admin logout',reply)
        self.assertIn("'back' — Cancel login",section);self.assertIn("'menu' — Cancel login",section)

    def test_command_cleanup_preserves_private_values_but_not_duplicate_hints(self):
        value="My exact words: Type 'menu' when you're ready."
        with conversation('English'):
            protect("'menu'",value)
            text=organize(p5.CARE,value+"\n\nType 'back' or 'menu' for the main menu.\nReply with a number. Type 'menu' to return here.",'main_menu')
        self.assertIn(value,text)
        body,section=text.split('You can type these other commands too:')
        self.assertNotIn('Reply with a number',body);self.assertNotIn("Type 'back' or",body)
        self.assertLess(section.index("'back'"),section.index("'menu'"))
        self.assertEqual(section.count("'menu'"),1)

    def test_fixed_malay_navigation_is_merged_before_final_translation(self):
        with conversation('Malay'):
            protect("'menu'")
            reply=organize(p5.CARE,"Profil penjaga saya 💜\n\n1. Semak cadangan\n2. Aktifkan cadangan\n\nPilih satu nombor. Taip 'menu' untuk menu utama.\nTaip 'back' untuk kembali.",'profile_menu')
        body,section=reply.split('You can type these other commands too:')
        self.assertNotIn('Taip',body);self.assertNotIn('Pilih satu nombor',body)
        self.assertEqual(section.count("'menu'"),1)

    def test_actual_admin_menu_and_summary_have_one_command_section(self):
        self.admin()
        for message in ['menu','summary']:
            reply=base.handlers.handle_message(p5.OUT,message)
            self.assertEqual(reply.count('You can type these other commands too:'),1)
            body,section=reply.split('You can type these other commands too:')
            self.assertNotIn("Type '",body);self.assertNotIn('Reply with a number',body)
            self.assertIn("Choose a number, or tell me what you need.",body)
            self.assertLess(section.index("'back'"),section.index("'menu'"))

    def test_restricted_action_explains_manual_control_without_changing_data(self):
        self.admin();before=self.rows('SELECT id,status FROM support_buddy_applications ORDER BY id')
        for message in ['approve all applications','delete all applications','reject this application']:
            reply=base.handlers.handle_message(p5.OUT,message)
            self.assertIn('human control',reply)
            if not message.startswith('delete'):self.assertIn('numbered action',reply)
        self.assertEqual(before,self.rows('SELECT id,status FROM support_buddy_applications ORDER BY id'))

    def test_verification_display_omits_not_required_and_keeps_existing_policy(self):
        self.rows("UPDATE support_buddy_applications SET admin_notes='Synthetic private note' WHERE id=%s",(self.buddy,))
        reply=base.handlers.admin_application_detail(self.buddy)
        self.assertNotIn('Verification: Not required',reply)
        self.assertLess(reply.index('1. Approve'),reply.index('Private note:'))
        self.rows('UPDATE support_buddy_applications SET verification_required=1,verified_at=NULL WHERE id=%s',(self.buddy,))
        self.assertIn('Pending verification',base.handlers.admin_application_detail(self.buddy))
        self.rows('UPDATE support_buddy_applications SET verified_at=CURRENT_TIMESTAMP WHERE id=%s',(self.buddy,))
        self.assertIn('Verified by an administrator on',base.handlers.admin_application_detail(self.buddy))

    def test_anyone_else_durably_skips_preview_and_no_request_is_sent(self):
        base.database.update_user(p5.CARE,state='ai_onboarding_confirm',support_type='Someone to listen',availability='Evening')
        self.rows("INSERT INTO support_buddy_applications(sender,display_name,support_types,availability,status,consent,submitted_at,verification_required) VALUES(%s,'Next Buddy','Someone to listen','Evening','approved',1,CURRENT_TIMESTAMP,0)",(p5.OTHER,))
        before=self.rows('SELECT count(*) FROM match_requests')
        first=base.handlers.show_match_choice(p5.CARE,base.handlers.find_matches(base.database.get_user(p5.CARE))[0],base.database.get_user(p5.CARE))
        self.assertIn('Synthetic Buddy',first)
        reply=base.handlers.handle_message(p5.CARE,'anyone else?')
        self.assertIn('Next Buddy',reply);self.assertEqual(before,self.rows('SELECT count(*) FROM match_requests'))
        preview=browsing.preview(p5.CARE);self.assertEqual(preview['buddy_sender'],p5.OTHER)
        reply=base.handlers.handle_message(p5.CARE,'2')
        self.assertNotIn('Would you like to send them a connection request?',reply)
        self.assertEqual(len(browsing.history(p5.CARE,base.database.get_user(p5.CARE))[0]),2)
        self.assertEqual(before,self.rows('SELECT count(*) FROM match_requests'))

    def test_other_tier_is_offered_without_silently_sending(self):
        base.database.update_user(p5.CARE,state='ai_onboarding_confirm',support_type='Casual conversation',availability='Evening')
        self.rows("INSERT INTO support_buddy_applications(sender,display_name,support_types,availability,status,consent,submitted_at,verification_required) VALUES(%s,'Weekend Buddy','Casual conversation','Weekends','approved',1,CURRENT_TIMESTAMP,0)",(p5.OTHER,))
        user=base.database.get_user(p5.CARE);time=next(m for m in base.handlers.find_matches(user) if m['tier']=='time')
        base.handlers.show_match_choice(p5.CARE,time,user)
        reply=base.handlers.handle_message(p5.CARE,'anyone else?')
        self.assertIn('Keep my support preference',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'match_alternatives')
        reply=base.handlers.handle_message(p5.CARE,'1')
        self.assertIn('Weekend Buddy',reply);self.assertIn('Weekends',reply)
        self.assertEqual(browsing.preview(p5.CARE)['buddy_sender'],p5.OTHER)

    def test_new_search_clears_seen_previews_and_foreign_history_is_untouched(self):
        user=base.database.get_user(p5.CARE);candidate=base.handlers.find_matches(dict(user,support_type='Someone to listen',availability='Evening'))[0]
        base.handlers.show_match_choice(p5.CARE,candidate,dict(user,support_type='Someone to listen',availability='Evening'))
        self.assertTrue(self.rows('SELECT * FROM match_search_sessions WHERE sender=%s',(p5.CARE,)))
        base.database.update_user(p5.CARE,state='main_menu')
        base.handlers.handle_message(p5.CARE,'1')
        self.assertEqual(self.rows('SELECT * FROM match_search_sessions WHERE sender=%s',(p5.CARE,)),[])
        self.assertIsNone(browsing.preview(p5.CARE))

    def test_old_preview_without_history_is_skipped_after_upgrade(self):
        base.database.update_user(p5.CARE,support_type='Someone to listen',availability='Evening')
        user=base.database.get_user(p5.CARE);base.handlers.show_match_choice(p5.CARE,base.handlers.find_matches(user)[0],user)
        self.rows('DELETE FROM match_search_sessions WHERE sender=%s',(p5.CARE,))
        reply=base.handlers.handle_message(p5.CARE,'anyone else?')
        self.assertNotIn('Would you like to send them a connection request?',reply)
        self.assertTrue(browsing.history(p5.CARE,user)[0])

    def test_admin_back_returns_to_application_list_and_note_back_saves_nothing(self):
        self.admin('admin_review_'+str(self.buddy))
        with patch.object(base.handlers,'admin_application_list',return_value='Application list'):
            self.assertIn('Application list',base.handlers.handle_message(p5.OUT,'back'))
        base.database.update_user(p5.OUT,state='admin_note_'+str(self.buddy))
        before=self.rows('SELECT admin_notes FROM support_buddy_applications WHERE id=%s',(self.buddy,))
        base.handlers.handle_message(p5.OUT,'back')
        self.assertEqual(base.database.get_user(p5.OUT)['state'],'admin_review_'+str(self.buddy))
        self.assertEqual(before,self.rows('SELECT admin_notes FROM support_buddy_applications WHERE id=%s',(self.buddy,)))
