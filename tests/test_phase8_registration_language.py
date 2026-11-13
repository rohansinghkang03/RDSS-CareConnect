"""Regression for offered languages versus reply language and unsaved switch requests."""
import test_phase2 as base
import test_phase4 as p4
from conversation_context import conversation,protect
from navigation_design import organize
import conversation_ai as ai

class RegistrationLanguageTests(p4.Phase4Tests):
    def form(self,step='languages'):
        base.database.start_support_buddy_draft('synthetic-a')
        base.database.update_support_buddy_draft('synthetic-a',full_name='Synthetic Applicant',rdss_member='Yes',display_name='Synthetic Buddy',languages='English',caregiver_experience='Less than 1 year',support_types='Someone to listen',availability='Evening',contact_methods='WhatsApp text',introduction=None)
        if step=='languages':base.database.update_support_buddy_draft('synthetic-a',caregiver_experience=None,support_types=None,availability=None,contact_methods=None,introduction=None)
        if step=='contact_methods':base.database.update_support_buddy_draft('synthetic-a',contact_methods=None,introduction=None)
        base.database.set_language_preference('synthetic-a','English')
        base.database.update_user('synthetic-a',state='buddy_registration_'+step)

    def test_english_and_melayu_are_form_answers_not_ui_language(self):
        self.form()
        base.handlers.handle_message('synthetic-a','English and Melayu')
        self.assertEqual(base.database.get_support_buddy_draft('synthetic-a')['languages'],'English|Malay')
        self.assertEqual(base.database.get_language_preference('synthetic-a'),'English')
        self.assertEqual(base.database.get_user('synthetic-a')['state'],'buddy_registration_experience')
        self.classifier.assert_not_called()

    def test_malay_option_answer_does_not_switch_ui_language(self):
        self.form('contact_methods')
        self.classifier.return_value=p4.decision('local',['1','2'],['Malay'])
        base.handlers.handle_message('synthetic-a','satu and dua')
        self.assertEqual(base.database.get_language_preference('synthetic-a'),'English')
        self.assertEqual(base.database.get_support_buddy_draft('synthetic-a')['contact_methods'],'WhatsApp text|Voice notes')
        self.assertEqual(base.database.get_user('synthetic-a')['state'],'buddy_registration_introduction')

    def test_exact_dean_switch_request_does_not_become_introduction(self):
        for text in ['okay can you reset back to english please',"i dont understand malay, can you translate to english","I don't understand Malay, can you translate to English?",'could you please change it back to English','please translate everything into English']:
            with self.subTest(text=text):
                self.form('introduction');base.database.set_language_preference('synthetic-a','Malay')
                reply=base.handlers.handle_message('synthetic-a',text)
                self.assertIn('Language updated',reply)
                self.assertEqual(base.database.get_language_preference('synthetic-a'),'English')
                self.assertEqual(base.database.get_user('synthetic-a')['state'],'buddy_registration_introduction')
                self.assertIsNone(base.database.get_support_buddy_draft('synthetic-a')['introduction'])
        self.classifier.assert_not_called()

    def test_language_help_does_not_overwrite_existing_edit(self):
        self.form('edit_introduction')
        base.database.update_support_buddy_draft('synthetic-a',introduction='My original introduction')
        base.handlers.handle_message('synthetic-a','okay can you reset back to english please')
        self.assertEqual(base.database.get_support_buddy_draft('synthetic-a')['introduction'],'My original introduction')
        self.assertEqual(base.database.get_user('synthetic-a')['state'],'buddy_registration_edit_introduction')

    def test_unknown_language_switch_stays_on_question_without_saving(self):
        self.form('introduction')
        reply=base.handlers.handle_message('synthetic-a','okay can you translate to French please')
        self.assertIn('answer has not been saved',reply)
        self.assertIsNone(base.database.get_support_buddy_draft('synthetic-a')['introduction'])
        self.assertEqual(base.database.get_user('synthetic-a')['state'],'buddy_registration_introduction')
        self.classifier.assert_not_called()

    def test_real_introduction_is_saved_exactly(self):
        self.form('introduction')
        text='I speak English and Melayu and enjoy listening to people.'
        base.handlers.handle_message('synthetic-a',text)
        self.assertEqual(base.database.get_support_buddy_draft('synthetic-a')['introduction'],text)

    def test_numeric_display_name_does_not_move_invitation_between_options(self):
        with conversation('English'):
            protect('1','Private Name')
            reply=organize('synthetic-a','Review your application\nDisplay name: 1\n\n1. Continue to consent\n2. Edit an answer\n3. Cancel application','buddy_registration_review')
        self.assertLess(reply.index("Choose a number, or tell me what you need."),reply.index('1. Continue'))
        self.assertIn('Display name: 1',reply)

    def test_offered_language_synonyms_and_edit_choices(self):
        from conversation_routing import registration_language_choices
        self.assertEqual(registration_language_choices('English dan Bahasa Melayu'),'1,3')
        self.assertEqual(registration_language_choices('Melayu & English'),'3,1')
        self.assertIsNone(registration_language_choices('please change to English'))
