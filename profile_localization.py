"""Fixed Malay profile-page wording, with no model call or caregiver text."""
import re

MALAY_LANGUAGES = {'malay', 'bahasa melayu', 'bahasa malaysia'}
MALAY_PROFILE_LINES = {
    "Private profile — not shared with other caregivers. Send 'privacy details' to learn more.": "Profil peribadi — tidak dikongsi dengan penjaga lain. Taip 'privacy details' untuk maklumat lanjut.",
    '6. My Support Buddy profile / edit display name': '6. Profil Rakan Sokongan saya / edit nama paparan',

    "Type 'back' for the previous profile screen.": "Taip 'back' untuk kembali ke skrin profil sebelumnya.",
    'My caregiver profile 💜': 'Profil penjaga saya 💜',
    'Profile suggestions: Enabled': 'Cadangan profil: Diaktifkan',
    'Profile suggestions: Disabled (declined)': 'Cadangan profil: Dilumpuhkan (tidak dipersetujui)',
    'Profile suggestions: Disabled (withdrawn)': 'Cadangan profil: Dilumpuhkan (kebenaran ditarik balik)',
    'Profile suggestions: Not enabled': 'Cadangan profil: Belum diaktifkan',
    'Saved profile information:': 'Maklumat profil yang disimpan:',
    'No profile information is saved.': 'Tiada maklumat profil disimpan.',
    'Your profile is private and is not shared with other caregivers by this feature.': 'Profil anda adalah peribadi dan tidak dikongsi dengan penjaga lain melalui ciri ini.',
    '1. Review profile suggestions': '1. Semak cadangan profil',
    '2. Enable suggestions / read permission details': '2. Aktifkan cadangan / baca butiran kebenaran',
    '3. Withdraw permission and delete my profile': '3. Tarik balik kebenaran dan padam profil saya',
    '4. Return to main menu': '4. Kembali ke menu utama',
    '5. Continue AI Chat': '5. Teruskan Sembang AI',
    "Choose a number. Type 'menu' anytime for the main menu.": "Pilih nombor. Taip 'menu' pada bila-bila masa untuk kembali ke menu utama.",
    'Withdrawal cancelled. Your profile permission and saved information are unchanged.': 'Penarikan balik kebenaran dibatalkan. Kebenaran profil dan maklumat yang disimpan tidak berubah.',
    'Your permission for AI-assisted caregiver profiling has been withdrawn. 💜': 'Kebenaran anda untuk pemprofilan penjaga dengan bantuan AI telah ditarik balik. 💜',
    'Your saved caregiver profile information, suggestions and unfinished edits have been deleted.': 'Maklumat profil penjaga yang disimpan, cadangan dan suntingan yang belum selesai telah dipadamkan.',
    'Your AI chat history is separate and has not been deleted.': 'Sejarah sembang AI anda adalah berasingan dan tidak dipadamkan.',
    'Your edited profile information has been saved. 💜': 'Maklumat profil yang anda edit telah disimpan. 💜',
    'Your suggestion has been added to your caregiver profile. 💜': 'Cadangan anda telah ditambahkan pada profil penjaga anda. 💜',
    'Suggestion rejected. Nothing was added to your profile. 💜': 'Cadangan ditolak. Tiada apa-apa ditambahkan pada profil anda. 💜',
    'Please choose an option below.': 'Sila pilih salah satu pilihan di bawah.',
    'Profile suggestions are disabled. Any previously saved profiling information has been deleted.': 'Cadangan profil dilumpuhkan. Sebarang maklumat profil yang disimpan sebelum ini telah dipadamkan.',
    'Your permission for AI-assisted profile suggestions has been recorded. 💜': 'Kebenaran anda untuk cadangan profil dengan bantuan AI telah direkodkan. 💜',
    'Choose 5 to continue AI Chat. Only messages sent after you enabled permission are eligible. Return here and choose 1 when you want to review a suggestion.': 'Pilih 5 untuk meneruskan Sembang AI. Hanya mesej yang dihantar selepas anda memberikan kebenaran layak digunakan. Kembali ke sini dan pilih 1 apabila anda mahu menyemak cadangan.',
    'Your permission changed. Choose an option below to continue.': 'Kebenaran anda telah berubah. Pilih salah satu pilihan di bawah untuk meneruskan.',
    'There is not enough eligible information for a suggestion yet. Choose 5 to continue AI Chat, then return here to review.': 'Maklumat yang layak belum mencukupi untuk menghasilkan cadangan. Pilih 5 untuk meneruskan Sembang AI, kemudian kembali ke sini untuk menyemak cadangan.',
    'Profile suggestions are temporarily unavailable. Please try again later.': 'Cadangan profil tidak tersedia buat sementara waktu. Sila cuba lagi kemudian.',
    'No pending suggestion is available. Review a new suggestion from the options below.': 'Tiada cadangan yang menunggu semakan. Semak cadangan baharu melalui pilihan di bawah.',
    'Withdraw profile permission?': 'Tarik balik kebenaran profil?',
    'This deletes your saved profile, suggestions and unfinished edits. AI chat history is separate and will remain. You can continue using AI Chat.': 'Ini akan memadamkan profil yang disimpan, cadangan dan suntingan yang belum selesai. Sejarah sembang AI adalah berasingan dan akan kekal. Anda boleh terus menggunakan Sembang AI.',
    '1. Yes, withdraw permission and delete my profile': '1. Ya, tarik balik kebenaran dan padam profil saya',
    '1. Withdraw permission and delete my profile': '1. Tarik balik kebenaran dan padam profil saya',
    '2. Cancel and keep my profile': '2. Batal dan kekalkan profil saya',
    "Type 'menu' for the main menu.": "Taip 'menu' untuk menu utama.",
}
MALAY_FIELD_LABELS = {'Care recipient': 'Penerima jagaan', 'Support needs': 'Keperluan sokongan',
                      'Availability': 'Masa lapang', 'Caregiving situation': 'Situasi penjagaan'}


def malay_profile_template(template):
    """Translate only fully recognized fixed lines; preserve marker identities."""
    result = []
    for line in template.split('\n'):
        if not line:
            result.append(line)
        elif line in MALAY_PROFILE_LINES:
            result.append(MALAY_PROFILE_LINES[line])
        else:
            field = re.fullmatch(r'([^:]+): (__PROFILE_[A-Z_]+__)', line)
            if field and field[1] in MALAY_FIELD_LABELS:
                result.append(MALAY_FIELD_LABELS[field[1]] + ': ' + field[2])
            else:
                # Other profile screens keep the existing translation path.
                return None
    return '\n'.join(result)
