"""New connection experience: isolated PostgreSQL, no real messages or profile changes."""
import os
import unittest
from unittest.mock import patch
import test_phase2 as base
import test_phase3 as p3
import test_phase5_match_chat as p5
import test_phase4 as p4
import connection_requests as cr
import buddy_profile as bp
import match_chat_store as store
import notifications as notices

class LocalConnectionUpdates(unittest.TestCase):
    rows=p3.Phase3Tests.rows
    setUpClass=classmethod(base.Phase2Tests.setUpClass.__func__)
    tearDownClass=classmethod(base.Phase2Tests.tearDownClass.__func__)
    migrate=staticmethod(base.Phase2Tests.migrate)
    def setUp(self):
        p5.MatchChatTests.setUp(self)
        self.rows((base.ROOT/'connection_request_v2_schema.sql').read_text())
        self.rows('DELETE FROM match_requests')
        flag=patch.dict(os.environ,{'CONNECTION_REQUEST_V2_ENABLED':'true','NOTIFICATIONS_ENABLED':'false'});flag.start();self.addCleanup(flag.stop)
        with base.database.get_connection() as c:cr.set_upfront(c,p5.BUD,self.buddy,True)
        base.database.update_user(p5.CARE,support_type='Someone to listen',availability='Evening')
    def preview(self):
        user=base.database.get_user(p5.CARE);match=base.handlers.find_matches(user)[0]
        return base.handlers.show_match_choice(p5.CARE,match,user)
    def reviewed(self,name='Test Caregiver',message='A listening ear in the evenings would help.'):
        self.preview();base.handlers.handle_message(p5.CARE,'1')
        base.handlers.handle_message(p5.CARE,name)
        return base.handlers.handle_message(p5.CARE,message)
    def sent(self):
        self.reviewed();base.handlers.handle_message(p5.CARE,'1')
        return self.rows('SELECT id FROM match_requests ORDER BY id DESC LIMIT 1')[0][0]

    def test_single_decision_each_side_unlocks_chat_only_after_acceptance(self):
        review=self.reviewed()
        self.assertIn('Test Caregiver',review);self.assertIn('AI profiling',review)
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
        base.handlers.handle_message(p5.CARE,'1')
        rid=self.rows('SELECT id FROM match_requests')[0][0]
        with self.assertRaises(PermissionError):store.authorize_delivery(p5.CARE,rid)
        inbox=base.handlers.handle_message(p5.BUD,'requests')
        self.assertIn('From: Test Caregiver',inbox);self.assertIn('listening ear',inbox)
        self.assertIn('Accepting request #'+str(rid),inbox)
        reply=base.handlers.handle_message(p5.BUD,'accept '+str(rid))
        from match_chat import ChatReply
        self.assertIsInstance(reply,ChatReply)
        self.assertNotIn('1. I agree to share',reply)
        self.assertEqual(store.inspect(p5.CARE,rid)['state'],'ready')
        self.assertEqual(self.rows('SELECT sender,decision FROM match_chat_permissions ORDER BY sender'),[(p5.CARE,'granted'),(p5.BUD,'granted')])
        self.assertEqual(base.analytics.get_profiling_consent(p5.CARE),'not_given')

    def test_no_model_inference_or_draft_can_send_without_review(self):
        self.preview()
        with self.assertRaises(PermissionError):base.database.create_selected_match_request(p5.CARE)
        self.reviewed()
        self.classifier.return_value=p4.decision('local',['1'])
        reply=base.handlers.handle_message(p5.CARE,'yes that seems okay')
        self.assertIn('number shown',reply);self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
        self.assertEqual(self.rows('SELECT * FROM match_chat_permissions'),[])

    def test_review_change_expiry_and_pair_change_fail_closed(self):
        self.reviewed()
        self.rows("UPDATE connection_request_drafts SET message='Changed after review'")
        with self.assertRaises(PermissionError):base.database.create_selected_match_request(p5.CARE)
        cr.review(p5.CARE);self.rows("UPDATE connection_request_drafts SET reviewed_at=CURRENT_TIMESTAMP-INTERVAL '31 minutes'")
        with self.assertRaises(PermissionError):base.database.create_selected_match_request(p5.CARE)
        cr.review(p5.CARE);self.rows('UPDATE match_previews SET buddy_sender=%s',(p5.OUT,))
        self.assertEqual(base.database.create_selected_match_request(p5.CARE)[0],'unavailable')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])

    def test_sharing_contact_details_is_screened_before_confirmation(self):
        self.preview();cr.begin(p5.CARE)
        for field,value in [('chosen_name','6591234567'),('chosen_name','1'),('message','Call +65 9123 4567'),('message','email me at test@example.com')]:
            with self.assertRaises(ValueError):cr.save(p5.CARE,field,value)
        self.assertEqual(self.rows('SELECT * FROM connection_request_details'),[])

    def test_recipient_cannot_accept_without_fresh_notice_or_upfront_consent(self):
        rid=self.sent()
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')[0],'notice_required')
        cr.show_accept_notice(p5.BUD,rid)
        self.rows("UPDATE connection_accept_notices SET shown_at=CURRENT_TIMESTAMP-INTERVAL '31 minutes'")
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')[0],'notice_required')
        cr.show_accept_notice(p5.BUD,rid)
        with base.database.get_connection() as c:cr.set_upfront(c,p5.BUD,self.buddy,False)
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')[0],'buddy_consent_required')
        self.assertEqual(self.rows('SELECT status FROM match_requests'),[('pending',)])

    def test_detail_change_or_reassigned_pair_invalidates_acceptance_notice(self):
        rid=self.sent();cr.show_accept_notice(p5.BUD,rid)
        self.rows("UPDATE connection_request_details SET message='Altered after showing notice' WHERE request_id=%s",(rid,))
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')[0],'notice_required')
        self.assertIsNone(cr.details_for_buddy(p5.OUT,rid))
        self.assertEqual(base.database.respond_to_buddy_request(p5.OUT,rid,'accepted')[0],'not_found')

    def test_declining_does_not_grant_buddy_number_permission(self):
        rid=self.sent()
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'declined')[0],'updated')
        self.assertEqual(self.rows('SELECT sender FROM match_chat_permissions'),[(p5.CARE,)])
        with self.assertRaises(PermissionError):store.authorize_delivery(p5.CARE,rid)

    def test_introduction_never_enters_translation_and_exact_private_text_survives(self):
        self.reviewed(name='Chosen Private Nick',message='My exact personal introduction.')
        base.database.set_language_preference(p5.BUD,'Tamil');base.handlers.handle_message(p5.CARE,'1')
        seen=[]
        with patch.object(base.chat,'safe_adapt_message',side_effect=lambda text,*a,**kw:seen.append(text) or text):
            reply=base.handlers.handle_message(p5.BUD,'requests')
        self.assertIn('Chosen Private Nick',reply);self.assertIn('My exact personal introduction.',reply)
        self.assertTrue(all('Chosen Private Nick' not in text and 'My exact personal introduction.' not in text and p5.CARE not in text for text in seen))

    def test_display_name_edit_changes_only_public_name_after_confirming(self):
        before=self.rows('SELECT full_name,status,consent,verified_at,review_version FROM support_buddy_applications WHERE sender=%s',(p5.BUD,))
        base.handlers.handle_message(p5.BUD,'buddy profile');base.handlers.handle_message(p5.BUD,'1')
        reply=base.handlers.handle_message(p5.BUD,'Corrected Test Buddy')
        self.assertIn('Confirm and save',reply)
        self.assertEqual(self.rows('SELECT display_name FROM support_buddy_applications WHERE sender=%s',(p5.BUD,)),[('Synthetic Buddy',)])
        base.handlers.handle_message(p5.BUD,'1')
        self.assertEqual(self.rows('SELECT display_name FROM support_buddy_applications WHERE sender=%s',(p5.BUD,)),[('Corrected Test Buddy',)])
        self.assertEqual(before,self.rows('SELECT full_name,status,consent,verified_at,review_version FROM support_buddy_applications WHERE sender=%s',(p5.BUD,)))
        self.assertEqual(self.rows('SELECT count(*) FROM buddy_profile_edits'),[(1,)])
        self.assertIsNone(bp.handle(p5.OUT,'Corrected Test Buddy','main_menu'))

    def test_display_name_edit_rejects_numbers_and_does_not_overwrite_concurrent_change(self):
        with self.assertRaises(ValueError):bp.prepare_name(p5.BUD,'1')
        bp.prepare_name(p5.BUD,'New Test Nick')
        self.rows("UPDATE support_buddy_applications SET display_name='Changed Elsewhere' WHERE sender=%s",(p5.BUD,))
        with self.assertRaises(PermissionError):bp.commit_name(p5.BUD)
        self.assertEqual(self.rows('SELECT display_name FROM support_buddy_applications WHERE sender=%s',(p5.BUD,)),[('Changed Elsewhere',)])
        with self.assertRaises(PermissionError):bp.commit_name(p5.OUT)

    def test_existing_accepted_connection_is_reused_without_new_request(self):
        rid=self.sent();cr.show_accept_notice(p5.BUD,rid);base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')
        reply=self.preview()
        self.assertIn("already connected",reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'match_existing_'+str(rid))
        from match_chat import ChatReply
        self.assertIsInstance(base.handlers.handle_message(p5.CARE,'1'),ChatReply)
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests'),[(1,)])

    def test_previous_suggestions_reopen_without_preference_changes(self):
        self.rows("INSERT INTO support_buddy_applications(sender,display_name,support_types,availability,status,consent,submitted_at,verification_required) VALUES(%s,'Earlier Test Buddy','Someone to listen','Evening','approved',1,CURRENT_TIMESTAMP,0)",(p5.OTHER,))
        self.preview();base.handlers.handle_message(p5.CARE,'anyone else?')
        reply=base.handlers.handle_message(p5.CARE,'previous suggestions')
        self.assertIn('Synthetic Buddy',reply);self.assertIn('Earlier Test Buddy',reply)
        reply=base.handlers.handle_message(p5.CARE,'1')
        self.assertIn('Synthetic Buddy',reply)
        self.assertEqual(base.database.get_user(p5.CARE)['availability'],'Evening')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])

    def test_legacy_accepted_request_sharing_question_opens_actual_choices(self):
        with patch.dict(os.environ,{'CONNECTION_REQUEST_V2_ENABLED':'false'}):
            base.database.save_match_preview(p5.CARE,{'buddy_id':self.buddy,'sender':p5.BUD,'name':'Synthetic Buddy','percentage':100},base.database.get_user(p5.CARE))
            _,row=base.database.create_selected_match_request(p5.CARE)
            base.database.respond_to_buddy_request(p5.BUD,row['id'],'accepted')
            reply=base.handlers.handle_message(p5.CARE,'how do i agree to share my whatsapp message')
        self.assertIn('1. I agree to share my WhatsApp number',reply)
        self.assertEqual(self.rows('SELECT * FROM match_chat_permissions'),[])

    def test_inbox_commands_have_correct_navigation_and_no_duplicate_sender(self):
        rid=self.sent();reply=base.handlers.handle_message(p5.BUD,'requests')
        self.assertEqual(reply.count('From: Test Caregiver'),1)
        self.assertNotIn('Previous application step',reply)
        self.assertIn("Type 'accept "+str(rid)+"' to accept this request.",reply)
        base.handlers.handle_message(p5.BUD,'request '+str(rid))
        self.assertEqual(base.database.get_user(p5.BUD)['state'],'buddy_request_'+str(rid))
        base.handlers.handle_message(p5.BUD,'back')
        self.assertEqual(base.database.get_user(p5.BUD)['state'],'buddy_requests')

    def test_repeated_sending_and_accepting_do_not_duplicate(self):
        rid=self.sent();cr.show_accept_notice(p5.BUD,rid)
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')[0],'updated')
        self.assertEqual(base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')[0],'already_resolved')
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests'),[(1,)])
        self.assertEqual(self.rows('SELECT count(*) FROM connection_request_details'),[(1,)])

    def test_buddy_withdrawal_revokes_future_buddy_links(self):
        rid=self.sent();cr.show_accept_notice(p5.BUD,rid);base.database.respond_to_buddy_request(p5.BUD,rid,'accepted')
        with base.database.get_connection() as c:cr.set_upfront(c,p5.BUD,self.buddy,False)
        with self.assertRaises(PermissionError):store.authorize_delivery(p5.CARE,rid)
        with base.database.get_connection() as c:cr.set_upfront(c,p5.BUD,self.buddy,True)
        with self.assertRaises(PermissionError):store.authorize_delivery(p5.CARE,rid)

    def test_new_admin_application_phrase_is_read_only(self):
        import admin_assist
        self.assertEqual(admin_assist.resolve('are there any new applications'),('applications',None))
        self.assertIsNone(admin_assist.resolve('approve all new applications'))

    def test_schema_repeats_without_changing_records(self):
        rid=self.sent();before=self.rows('SELECT id,status FROM match_requests ORDER BY id')
        self.rows((base.ROOT/'connection_request_v2_schema.sql').read_text())
        self.assertEqual(before,self.rows('SELECT id,status FROM match_requests ORDER BY id'))

    def test_named_verification_required_for_all_pending_applications(self):
        self.rows("UPDATE support_buddy_applications SET status='pending',consent_at=CURRENT_TIMESTAMP,consent_text='Synthetic consent',verification_required=0,verified_at=NULL,verified_by=NULL WHERE id=%s",(self.buddy,))
        app=base.database.get_admin_application(self.buddy)
        with self.assertRaises(ValueError):base.database.review_support_buddy_application(self.buddy,'approve','',p5.CARE,app['review_version'])
        with self.assertRaises(ValueError):base.database.review_support_buddy_application(self.buddy,'verify','',p5.CARE,app['review_version'])
        screen=base.handlers.admin_application_detail(self.buddy)
        self.assertNotIn('1. Approve',screen);self.assertIn('3. Mark verification complete',screen)
        import admin_verification as av
        av.begin(p5.CARE,app)
        av.handle(p5.CARE,'Synthetic Administrator','admin_verify_name_'+str(self.buddy))
        self.assertIsNone(base.database.get_admin_application(self.buddy)['verified_at'])
        reply=av.handle(p5.CARE,'1','admin_verify_confirm_'+str(self.buddy))
        self.assertIn('Verified by: Synthetic Administrator',reply);self.assertIn('1. Approve',reply)
        updated=base.database.get_admin_application(self.buddy)
        self.assertEqual(updated['verified_by'],p5.CARE)
        self.assertEqual(updated['verified_by_name'],'Synthetic Administrator')
        event=self.rows("SELECT actor,notes FROM admin_review_events WHERE application_id=%s ORDER BY id DESC LIMIT 1",(self.buddy,))[0]
        self.assertEqual(event[0],p5.CARE);self.assertIn('Synthetic Administrator',event[1])
        base.database.review_support_buddy_application(self.buddy,'approve','',p5.CARE,updated['review_version'])
        self.assertEqual(base.database.get_admin_application(self.buddy)['status'],'approved')

    def test_verification_cancel_expiry_and_concurrent_edit_preserve_decision(self):
        import admin_verification as av
        self.rows("UPDATE support_buddy_applications SET status='pending',verified_at=NULL WHERE id=%s",(self.buddy,))
        app=base.database.get_admin_application(self.buddy)
        av.begin(p5.CARE,app);av.handle(p5.CARE,'Synthetic Administrator','admin_verify_name_'+str(self.buddy))
        self.rows('UPDATE support_buddy_applications SET review_version=review_version+1 WHERE id=%s',(self.buddy,))
        reply=av.handle(p5.CARE,'1','admin_verify_confirm_'+str(self.buddy));self.assertIn('changed',reply)
        self.assertIsNone(base.database.get_admin_application(self.buddy)['verified_at'])
        av.begin(p5.CARE,base.database.get_admin_application(self.buddy))
        self.rows("UPDATE admin_verification_drafts SET created_at=CURRENT_TIMESTAMP-INTERVAL '31 minutes'")
        self.assertIn('expired',av.handle(p5.CARE,'Synthetic Administrator','admin_verify_name_'+str(self.buddy)))
        av.begin(p5.CARE,base.database.get_admin_application(self.buddy))
        self.assertIn('cancelled',av.handle(p5.CARE,'back','admin_verify_name_'+str(self.buddy)))
        self.assertEqual(self.rows('SELECT * FROM admin_verification_drafts'),[])
        for name in ['123456','Test 123','x','Name\nInjected']:
            with self.assertRaises(ValueError):av.validate_name(name)

    def test_verification_name_never_reaches_ai_and_requires_current_admin_session(self):
        import admin_verification as av
        import reporting_auth
        self.rows("UPDATE support_buddy_applications SET status='pending',verified_at=NULL WHERE id=%s",(self.buddy,))
        av.begin(p5.CARE,base.database.get_admin_application(self.buddy))
        state='admin_verify_name_'+str(self.buddy)
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({p5.CARE})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PIN'),patch.dict(os.environ,{'REPORTING_ENABLED':'true'}),patch.object(reporting_auth,'session_valid',return_value=False):
            reply=base.handlers.handle_message(p5.CARE,'Synthetic Administrator')
        self.assertIn('expired',reply)
        self.assertIsNone(self.rows('SELECT verifier_name FROM admin_verification_drafts WHERE sender=%s',(p5.CARE,))[0][0])
        base.database.update_user(p5.CARE,state=state)
        self.classifier.reset_mock()
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({p5.CARE})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PIN'),patch.dict(os.environ,{'REPORTING_ENABLED':'true'}),patch.object(reporting_auth,'session_valid',return_value=True):
            reply=base.handlers.handle_message(p5.CARE,'Synthetic Administrator')
        self.assertIn('Confirm verification',reply);self.classifier.assert_not_called()
        self.assertIsNone(base.database.get_admin_application(self.buddy)['verified_at'])

    def test_commands_allow_terminal_punctuation_without_changing_private_text(self):
        import conversation_routing as routing
        for value in ['Chat 71.','chat 71,','chat 71!','chat 71。']:
            prepared,reply=routing.prepare(p5.CARE,value,base.database.get_user(p5.CARE))
            self.assertEqual(prepared,'chat 71');self.assertIsNone(reply)
        base.database.update_user(p5.CARE,state='match_request_message')
        user=base.database.get_user(p5.CARE)
        prepared,reply=routing.prepare(p5.CARE,'I feel tired, especially at night.',user)
        self.assertEqual(prepared,'I feel tired, especially at night.')

    def test_notification_primary_action_is_above_secondary_navigation(self):
        from navigation_design import organize
        from notification_messages import render
        reply=organize(p5.BUD,render('connection_request'),'main_menu')
        self.assertTrue(reply.startswith("Type 'requests'"))
        self.assertLess(reply.index("Type 'requests'"),reply.index('You can type these other commands too:'))

    def test_match_yes_reminder_is_short_and_keeps_explicit_choice(self):
        self.preview()
        reply=base.handlers.handle_message(p5.CARE,'yes')
        self.assertIn('Synthetic Buddy',reply)
        self.assertIn('1. Continue',reply);self.assertIn('2. Show someone else',reply)
        self.assertNotIn('Support: ',reply)
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])

    def test_compact_footer_and_contextual_help_preserve_current_step(self):
        self.preview()
        reply=base.handlers.handle_message(p5.CARE,'help')
        self.assertIn("'previous suggestions'",reply);self.assertIn("'menu'",reply)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'confirm_match')
        self.assertEqual(self.rows('SELECT * FROM match_requests'),[])
        short=base.handlers.handle_message(p5.CARE,'yes')
        section=short.split('You can type these other commands too:')[1]
        self.assertEqual(len(section.strip().splitlines()),3)
        self.assertIn("'help'",section)
        self.classifier.assert_not_called()

    def test_introduction_preview_keeps_complete_draft_available_without_saving_changes(self):
        base.database.start_support_buddy_draft(p5.CARE)
        value='A synthetic introduction. '*18
        base.database.update_support_buddy_draft(p5.CARE,introduction=value)
        base.database.update_user(p5.CARE,state='buddy_registration_review')
        review=base.handlers.registration_review(p5.CARE)
        self.assertIn('full introduction',review);self.assertNotIn(value,review)
        reply=base.handlers.handle_message(p5.CARE,'full introduction')
        self.assertIn(value,reply)
        self.assertEqual(base.database.get_support_buddy_draft(p5.CARE)['introduction'],value)
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'buddy_registration_review')
        self.classifier.assert_not_called()

    def test_admin_decisions_precede_details_and_full_introduction_requires_admin_session(self):
        value='A synthetic introduction. '*18
        self.rows("UPDATE support_buddy_applications SET introduction=%s,status='pending',verified_at=NULL WHERE id=%s",(value,self.buddy))
        detail=base.handlers.admin_application_detail(self.buddy)
        self.assertLess(detail.index('Verification:'),detail.index('Name:'))
        self.assertLess(detail.index('3. Mark verification complete'),detail.index('Languages:'))
        self.assertNotIn(value,detail)
        base.database.update_user(p5.CARE,state='admin_review_'+str(self.buddy))
        import reporting_auth
        with patch.object(base.handlers,'ADMIN_PHONE_NUMBERS',frozenset({p5.CARE})),patch.object(base.handlers,'ADMIN_PIN','Synthetic-PIN'),patch.dict(os.environ,{'REPORTING_ENABLED':'true'}),patch.object(reporting_auth,'session_valid',return_value=False):
            reply=base.handlers.handle_message(p5.CARE,'full introduction')
        self.assertNotIn(value,reply);self.assertIn('expired',reply)

    def test_profile_privacy_details_are_on_demand_without_changing_consent(self):
        reply=base.handlers.handle_message(p5.CARE,'profile')
        self.assertIn('privacy details',reply)
        consent=base.analytics.get_profiling_consent(p5.CARE)
        detail=base.handlers.handle_message(p5.CARE,'privacy details')
        self.assertIn('AI chat history is separate',detail)
        self.assertEqual(consent,base.analytics.get_profiling_consent(p5.CARE))
        self.assertEqual(base.database.get_user(p5.CARE)['state'],'profile_menu')
