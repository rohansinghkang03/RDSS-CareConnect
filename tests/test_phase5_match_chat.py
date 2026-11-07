"""Private match handoff: synthetic PostgreSQL and mocked WhatsApp only."""
import concurrent.futures
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import test_phase2 as base
import test_phase3 as p3
import test_phase4 as p4
import match_chat as chat
import match_chat_store as store
import match_chat_delivery as delivery
import whatsapp

CARE='6500000101';BUD='6500000102';OUT='6500000103';OTHER='6500000104'

class MatchChatTests(unittest.TestCase):
    rows=p3.Phase3Tests.rows
    setUpClass=classmethod(base.Phase2Tests.setUpClass.__func__)
    tearDownClass=classmethod(base.Phase2Tests.tearDownClass.__func__)
    migrate=staticmethod(base.Phase2Tests.migrate)

    def setUp(self):
        p4.Phase4Tests.setUp(self)
        self.rows((base.ROOT/'match_chat_schema.sql').read_text())
        self.rows('TRUNCATE match_chat_permissions,match_chat_prompts,match_chat_deliveries')
        enabled=patch.dict(os.environ,{'MATCH_CHAT_ENABLED':'true','MATCH_CHAT_TEST_NUMBERS':''})
        enabled.start();self.addCleanup(enabled.stop)
        connection=patch.object(store,'get_connection',base.connect);connection.start();self.addCleanup(connection.stop)
        for sender in [CARE,BUD,OUT,OTHER]:
            base.database.create_user(sender);base.database.set_language_preference(sender,'English')
        self.buddy=self.rows('''INSERT INTO support_buddy_applications
          (sender,full_name,display_name,support_types,availability,languages,status,consent,submitted_at,verification_required)
          VALUES(%s,'Private real name','Synthetic Buddy','Someone to listen','Evening','English','approved',1,CURRENT_TIMESTAMP,0) RETURNING id''',(BUD,))[0][0]
        self.request=self.rows('''INSERT INTO match_requests(requester,buddy_id,buddy_sender,caregiver_name,match_percentage,status,support_type,availability,created_at)
          VALUES(%s,%s,%s,'Synthetic Buddy',100,'accepted','Someone to listen','Evening',CURRENT_TIMESTAMP) RETURNING id''',(CARE,self.buddy,BUD))[0][0]

    def grant(self,sender):
        store.prepare_prompt(sender,self.request);store.decide(sender,self.request,'granted')
    def mutual(self):
        self.grant(CARE);self.grant(BUD)
    def ready_reply(self,sender=CARE):
        self.mutual()
        return base.handlers.handle_message(sender,'chat '+str(self.request))

    def test_match_tiers_prefer_exact_then_support_then_time(self):
        import matching
        user={'sender':CARE,'support_type':'Someone to listen','availability':'Evening'}
        buddies=[{'id':1,'sender':BUD,'name':'Time Buddy','support_types':'Practical advice','availability':'Evening'},
                 {'id':2,'sender':OTHER,'name':'Support Buddy','support_types':'Someone to listen','availability':'Morning'},
                 {'id':3,'sender':OUT,'name':'Exact Buddy','support_types':'Someone to listen','availability':'Flexible'},
                 {'id':4,'sender':CARE,'name':'Self','support_types':'Someone to listen','availability':'Evening'},
                 {'id':5,'sender':'6500000105','name':'Neither','support_types':'Practical advice','availability':'Morning'}]
        with patch.object(matching,'get_approved_support_buddies',return_value=buddies),patch.object(matching,'get_latest_match_request',return_value=None):
            matches=matching.find_matches(user)
        self.assertEqual([m['tier'] for m in matches],['exact','support','time'])
        self.assertEqual(matches[1]['offered_times'],['Morning'])
        with patch.object(matching,'get_approved_support_buddies',return_value=buddies),patch.object(matching,'get_latest_match_request',return_value={'buddy_id':3,'status':'declined'}):
            self.assertEqual([m['tier'] for m in matching.find_matches(user)],['support','time'])

    def test_alternatives_offer_both_routes_without_sending_and_confirm_one(self):
        base.database.update_user(CARE,state='match_alternatives',support_type='Someone to listen',availability='Morning')
        self.rows("UPDATE support_buddy_applications SET availability='Evening' WHERE id=%s",(self.buddy,))
        self.rows("INSERT INTO support_buddy_applications(sender,display_name,support_types,availability,status,consent,submitted_at,verification_required) VALUES(%s,'Different Support','Practical advice','Morning','approved',1,CURRENT_TIMESTAMP,0)",(OTHER,))
        before=self.rows('SELECT count(*) FROM match_requests')[0][0]
        reply=base.handlers.show_match_alternatives(CARE)
        self.assertIn('1. Keep my support',reply);self.assertIn('2. Keep my preferred timing',reply)
        preview=base.handlers.handle_message(CARE,'2')
        self.assertIn('Practical advice',preview);self.assertIn('not a promise',preview)
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests')[0][0],before)
        self.assertEqual(self.rows('SELECT buddy_sender FROM match_previews WHERE requester=%s',(CARE,)),[(OTHER,)])
        base.handlers.handle_message(CARE,'1')
        self.assertEqual(self.rows('SELECT count(*) FROM match_requests')[0][0],before+1)

    def test_feature_disabled_fails_closed_without_accessing_store(self):
        with patch.dict(os.environ,{'MATCH_CHAT_ENABLED':'false'}),patch.object(store,'get_connection',side_effect=AssertionError('Disabled feature queried database')):
            self.assertEqual(store.inspect(CARE,self.request)['state'],'disabled')
            with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)

    def test_only_both_current_permissions_release_counterpart_number(self):
        self.assertEqual(store.inspect(CARE,self.request)['state'],'consent')
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        self.grant(CARE)
        self.assertEqual(store.inspect(CARE,self.request)['state'],'waiting')
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        self.grant(BUD)
        _,url=store.authorize_delivery(CARE,self.request);self.assertEqual(url,'https://wa.me/'+BUD)
        _,url=store.authorize_delivery(BUD,self.request);self.assertEqual(url,'https://wa.me/'+CARE)

    def test_user_must_see_current_notice_and_cannot_use_expired_prompt(self):
        with self.assertRaises(PermissionError):store.decide(CARE,self.request,'granted')
        store.prepare_prompt(CARE,self.request)
        self.rows("UPDATE match_chat_prompts SET shown_at=CURRENT_TIMESTAMP-INTERVAL '31 minutes'")
        with self.assertRaises(PermissionError):store.decide(CARE,self.request,'granted')

    def test_stranger_cannot_view_approve_revoke_or_release(self):
        self.mutual()
        for operation in [lambda:store.inspect(OUT,self.request),lambda:store.decide(OUT,self.request,'granted'),
                          lambda:store.decide(OUT,self.request,'revoked'),lambda:store.authorize_delivery(OUT,self.request)]:
            with self.assertRaises(PermissionError):operation()

    def test_pending_declined_legacy_and_self_requests_never_release(self):
        self.mutual()
        for status in ['pending','declined']:
            self.rows('UPDATE match_requests SET status=%s',(status,))
            with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        self.rows("UPDATE match_requests SET status='accepted',buddy_id=NULL,buddy_sender=NULL")
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        self.rows('UPDATE match_requests SET buddy_id=%s,buddy_sender=%s,requester=%s',(self.buddy,BUD,BUD))
        with self.assertRaises(PermissionError):store.authorize_delivery(BUD,self.request)

    def test_buddy_approval_verification_and_public_consent_are_rechecked(self):
        self.mutual()
        for change in ["status='rejected'","consent=0","verification_required=1,verified_at=NULL"]:
            self.rows('UPDATE support_buddy_applications SET '+change)
            with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
            self.rows("UPDATE support_buddy_applications SET status='approved',consent=1,verification_required=0")

    def test_expired_or_old_version_permissions_are_not_reused(self):
        self.mutual()
        self.rows("UPDATE match_chat_permissions SET consent_version='obsolete'")
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        self.rows("UPDATE match_chat_permissions SET consent_version=%s,updated_at=CURRENT_TIMESTAMP-INTERVAL '4 years'",(store.VERSION,))
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)

    def test_reassigned_match_invalidates_prompt_and_old_pair_permissions(self):
        store.prepare_prompt(CARE,self.request)
        self.rows('UPDATE support_buddy_applications SET sender=%s WHERE id=%s',(OTHER,self.buddy))
        self.rows('UPDATE match_requests SET buddy_sender=%s WHERE id=%s',(OTHER,self.request))
        with self.assertRaises(PermissionError):store.decide(CARE,self.request,'granted')
        store.prepare_prompt(CARE,self.request);store.decide(CARE,self.request,'granted')
        store.prepare_prompt(OTHER,self.request);store.decide(OTHER,self.request,'granted')
        self.rows('UPDATE support_buddy_applications SET sender=%s WHERE id=%s',(BUD,self.buddy))
        self.rows('UPDATE match_requests SET buddy_sender=%s WHERE id=%s',(BUD,self.request))
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)

    def test_revocation_before_send_blocks_link_and_works_when_buddy_ineligible(self):
        reply=self.ready_reply()
        self.rows("UPDATE support_buddy_applications SET status='rejected'")
        store.decide(BUD,self.request,'revoked')
        self.rows("UPDATE support_buddy_applications SET status='approved'")
        with patch.object(whatsapp,'send_message',return_value='safe-notice') as text,patch.object(whatsapp,'send_chat_url_button') as button:
            delivery.send(CARE,reply);button.assert_not_called()
            self.assertNotIn('wa.me',str(text.call_args))

    def test_revocation_remains_possible_when_feature_is_switched_off(self):
        self.mutual()
        with patch.dict(os.environ,{'MATCH_CHAT_ENABLED':'false'}):
            reply=base.handlers.handle_message(CARE,'stop chat '+str(self.request))
        self.assertIn('permission withdrawn',reply)
        self.assertEqual(store.inspect(CARE,self.request)['state'],'consent')

    def test_profile_permission_is_independent_from_contact_sharing(self):
        base.analytics.grant_profiling_consent(CARE)
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        self.mutual();base.analytics.withdraw_profiling_consent(CARE)
        self.assertEqual(store.inspect(CARE,self.request)['state'],'ready')
        store.decide(CARE,self.request,'revoked')
        self.assertEqual(base.analytics.get_profiling_consent(CARE),'withdrawn')

    def test_full_request_accept_notice_and_mutual_choice_produce_button_envelope(self):
        self.rows("UPDATE match_requests SET status='pending'")
        accepted=base.handlers.handle_message(BUD,'accept '+str(self.request))
        self.assertIn('separate permission',accepted)
        self.assertNotIsInstance(accepted,chat.ChatReply)
        waiting=base.handlers.handle_message(BUD,'1');self.assertIn('has not yet',waiting)
        notice=base.handlers.handle_message(CARE,'status');self.assertIn('WhatsApp number',notice)
        ready=base.handlers.handle_message(CARE,'1');self.assertIsInstance(ready,chat.ChatReply)
        self.assertEqual(ready.request_id,self.request)
        self.assertNotIn(BUD,ready);self.assertNotIn('wa.me',ready)
        self.assertEqual(self.rows('SELECT * FROM caregiver_sharing_decisions'),[])

    def test_inferred_agreement_and_help_cannot_grant_contact_permission(self):
        base.handlers.handle_message(CARE,'chat '+str(self.request))
        self.classifier.return_value=p4.decision('local',['1'])
        reply=base.handlers.handle_message(CARE,'sure sounds okay I guess')
        self.assertIn('confirm using the number',reply)
        self.assertEqual(self.rows('SELECT * FROM match_chat_permissions'),[])
        base.handlers.handle_message(CARE,'help')
        self.assertEqual(self.rows('SELECT * FROM match_chat_permissions'),[])

    def test_translator_never_sees_phone_urls_or_private_full_name(self):
        self.mutual();base.database.set_language_preference(CARE,'Tamil')
        seen=[];base.chat.safe_adapt_message.side_effect=lambda message,*a,**kw:seen.append(message) or message
        reply=base.handlers.handle_message(CARE,'chat '+str(self.request))
        self.assertIsInstance(reply,chat.ChatReply)
        self.assertTrue(seen)
        self.assertTrue(all(BUD not in text and CARE not in text and 'wa.me' not in text and 'Private real name' not in text for text in seen))

    def test_button_payload_uses_official_cta_url_shape(self):
        reply=self.ready_reply()
        response=SimpleNamespace(ok=True,json=lambda:{'messages':[{'id':'synthetic-provider-id'}]})
        with patch.object(whatsapp,'ACCESS_TOKEN','synthetic-token'),patch.object(whatsapp,'PHONE_NUMBER_ID','synthetic-phone-id'),patch.object(whatsapp.requests,'post',return_value=response) as post:
            delivery.send(CARE,reply)
        payload=post.call_args.kwargs['json']
        self.assertEqual(payload['to'],CARE);self.assertEqual(payload['type'],'interactive')
        self.assertEqual(payload['interactive']['type'],'cta_url')
        self.assertEqual(payload['interactive']['action']['parameters']['url'],'https://wa.me/'+BUD)
        self.assertLessEqual(len(payload['interactive']['action']['parameters']['display_text']),20)
        self.assertNotIn(BUD,payload['interactive']['body']['text'])
        self.assertEqual(self.rows("SELECT kind,outcome,provider_id FROM reporting_outgoing WHERE provider_id='synthetic-provider-id'"),
                         [('interactive','accepted','synthetic-provider-id')])

    def test_rejected_button_has_one_authorised_clickable_link_fallback(self):
        reply=self.ready_reply()
        with patch.object(whatsapp,'send_chat_url_button',side_effect=whatsapp.WhatsAppRejected(400,131009)) as button,patch.object(whatsapp,'send_message',return_value='fallback-id') as text:
            self.assertEqual(delivery.send(CARE,reply),'fallback-id')
        button.assert_called_once();text.assert_called_once()
        self.assertIn('https://wa.me/'+BUD,text.call_args.args[1])
        self.assertEqual(self.rows('SELECT outcome FROM match_chat_deliveries ORDER BY created_at'),[('failed',),('accepted',)])

    def test_withdrawal_during_long_explanation_blocks_button(self):
        self.mutual();reply=chat.ChatReply('Explanatory text '*100,self.request,'Chat')
        def text(sender,body):
            if len(body)>1024:store.decide(BUD,self.request,'revoked')
            self.assertNotIn('https://wa.me/',body)
            return 'text-id'
        with patch.object(whatsapp,'send_message',side_effect=text),patch.object(whatsapp,'send_chat_url_button') as button:
            delivery.send(CARE,reply)
        button.assert_not_called()
        self.assertEqual(self.rows('SELECT * FROM match_chat_deliveries'),[])

    def test_withdrawal_after_rejected_button_blocks_fallback(self):
        reply=self.ready_reply()
        def rejected(*args):
            store.decide(BUD,self.request,'revoked')
            raise whatsapp.WhatsAppRejected(400,131009)
        with patch.object(whatsapp,'send_chat_url_button',side_effect=rejected),patch.object(whatsapp,'send_message',return_value='notice') as text:
            delivery.send(CARE,reply)
        self.assertNotIn('https://wa.me/',text.call_args.args[1])
        self.assertEqual(self.rows('SELECT outcome FROM match_chat_deliveries'),[('failed',)])

    def test_unknown_or_auth_failure_never_triggers_automatic_link_resend(self):
        reply=self.ready_reply()
        for error in [RuntimeError('unknown provider outcome'),whatsapp.WhatsAppRejected(401,190),whatsapp.WhatsAppRejected(429,4)]:
            with patch.object(whatsapp,'send_chat_url_button',side_effect=error),patch.object(whatsapp,'send_message') as text:
                with self.assertRaises(RuntimeError):delivery.send(CARE,reply)
                text.assert_not_called()

    def test_number_cannot_be_changed_by_button_text_or_url_injection(self):
        for url in ['https://evil.invalid/'+BUD,'https://wa.me/+6500000102','https://wa.me/'+BUD+'?text=private','javascript:alert(1)']:
            with self.assertRaises(ValueError):whatsapp.send_chat_url_button(CARE,'Body','Chat',url)

    def test_optional_controlled_test_scope_requires_both_numbers(self):
        self.mutual()
        with patch.dict(os.environ,{'MATCH_CHAT_TEST_NUMBERS':CARE}):
            with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)
        with patch.dict(os.environ,{'MATCH_CHAT_TEST_NUMBERS':CARE+','+BUD}):
            self.assertEqual(store.inspect(CARE,self.request)['state'],'ready')

    def test_parallel_permissions_and_release_checks_have_no_deadlock(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.grant,[CARE,BUD]))
        self.assertEqual(store.inspect(CARE,self.request)['state'],'ready')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            urls=list(pool.map(lambda _:store.authorize_delivery(CARE,self.request)[1],range(12)))
        self.assertEqual(set(urls),{'https://wa.me/'+BUD})

    def test_network_delivery_holds_no_database_row_lock_and_later_revocation_blocks(self):
        reply=self.ready_reply()
        def provider(*args):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(store.decide,BUD,self.request,'revoked').result(timeout=3)
            return 'already-released-id'
        with patch.object(whatsapp,'send_chat_url_button',side_effect=provider):delivery.send(CARE,reply)
        with self.assertRaises(PermissionError):store.authorize_delivery(CARE,self.request)

    def test_migration_repeat_and_retention_preserve_accounts(self):
        import retention
        self.mutual();store.authorize_delivery(CARE,self.request)
        before=self.rows('SELECT sender FROM users ORDER BY sender')
        self.rows((base.ROOT/'match_chat_schema.sql').read_text())
        self.rows("UPDATE match_chat_permissions SET updated_at=CURRENT_TIMESTAMP-INTERVAL '4 years'")
        self.rows("DELETE FROM reporting_settings WHERE key='retention_last_success'")
        with patch.object(retention,'get_connection',base.connect):result=retention.cleanup_if_due()
        self.assertEqual(result['match_chat_permissions'],2)
        self.assertEqual(before,self.rows('SELECT sender FROM users ORDER BY sender'))
