"""Votes reliés aux membres et élections au bureau : le gagnant prend le poste à la clôture (le président se change par vote)."""
import html
import os
import re
import sys

S, P = sys.argv[1], sys.argv[2]
os.environ['DATABASE_URL'] = 'sqlite:///' + os.path.join(S, 'el.db').replace(os.sep, '/')
sys.path.insert(0, P)
os.chdir(P)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import app as m  # noqa: E402

app, db = m.app, m.db
app.config.update(WTF_CSRF_ENABLED=False, TESTING=True, UPLOAD_FOLDER=os.path.join(S, 'uploads'))
from models import Tontine, Member, User, Poll, PollVote  # noqa: E402
from tenancy import tenant_bypass  # noqa: E402

failed = []


def check(cond, msg):
    print(('OK   ' if cond else 'FAIL ') + msg)
    if not cond:
        failed.append(msg)


def text(r):
    h = re.sub(r'(?s)<(script|style)\b.*?</\1>', ' ', r.get_data(as_text=True))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', h)))


pres = app.test_client()
pres.post('/inscription', data={'name': 'Tontine Vote', 'slug': 'vote', 'first_name': 'Hélène', 'last_name': 'Ngo',
                                'email': 'h@vote.cm', 'phone': '699000001', 'username': 'helene',
                                'password': 'Mbalmayo2026', 'password_confirm': 'Mbalmayo2026'})
names = ['Marie', 'Awa', 'Kofi', 'Paul']
for i, first in enumerate(names):
    pres.post('/members/add', data={'first_name': first, 'last_name': 'Test', 'email': f'{first.lower()}@vote.cm',
                                    'phone': f'69911122{i}', 'username': first.lower(), 'role': 'MEMBRE',
                                    'password': 'Passw0rd1', 'confirm_password': 'Passw0rd1'})
with app.app_context(), tenant_bypass():
    tid = Tontine.query.filter_by(slug='vote').one().id
    ids = {x.first_name: x.id for x in Member.query.filter_by(tontine_id=tid).all()}
clients = {}
for n in names:
    c = app.test_client()
    c.post('/login', data={'tontine': 'vote', 'username': n.lower(), 'password': 'Passw0rd1'})
    clients[n] = c
clients['Hélène'] = pres


def role(username):
    with app.app_context(), tenant_bypass():
        return User.query.filter_by(tontine_id=tid, username=username).one().role


def elect(role_code, candidates, title=''):
    r = pres.post('/votes/add', data={'kind': 'ELECTION', 'election_role': role_code, 'title': title,
                                      'candidates': [str(ids[c]) for c in candidates]}, follow_redirects=True)
    with app.app_context(), tenant_bypass():
        poll = Poll.query.filter_by(tontine_id=tid).order_by(Poll.id.desc()).first()
        return r, poll.id, {o.label.split()[0]: o.id for o in poll.options}


def vote(who, poll_id, option_id):
    return clients[who].post(f'/votes/{poll_id}/vote', data={'option_id': option_id}, follow_redirects=True)


# ---------------------------------------------------------------- création
h = text(pres.get('/votes/add'))
check('Une élection au bureau' in h and 'Poste à élire' in h and 'Marie Test' in h, "formulaire : type « élection », poste et candidats (les membres)")
r = pres.post('/votes/add', data={'kind': 'ELECTION', 'election_role': 'PRESIDENT', 'candidates': [str(ids['Marie'])]},
              follow_redirects=True)
check('au moins deux candidats' in text(r), 'élection avec un seul candidat refusée')
r = pres.post('/votes/add', data={'kind': 'ELECTION', 'election_role': 'ROI', 'candidates': [str(ids['Marie']), str(ids['Awa'])]},
              follow_redirects=True)
check('Choisissez le poste' in text(r), 'poste inconnu refusé')
r, pid, opt = elect('PRESIDENT', ['Marie', 'Awa'])
check("le gagnant devient président(e)" in text(r) and 'Élection : Président(e)' in text(r), 'élection du président ouverte (titre automatique)')
with app.app_context(), tenant_bypass():
    poll = db.session.get(Poll, pid)
    check(poll.is_election and all(o.candidate_member_id for o in poll.options), 'chaque choix est relié à la fiche du candidat')

# ---------------------------------------------------------------- vote : un membre actif = une voix
vote('Marie', pid, opt['Marie'])
vote('Kofi', pid, opt['Marie'])
vote('Awa', pid, opt['Awa'])
r = vote('Kofi', pid, opt['Awa'])
check('déjà voté' in text(r), 'un membre ne peut pas voter deux fois')
with app.app_context(), tenant_bypass():
    votes = {v.member.first_name: v.option.label for v in PollVote.query.filter_by(poll_id=pid).all()}
    check(votes == {'Marie': 'Marie Test', 'Kofi': 'Marie Test', 'Awa': 'Awa Test'}, f'chaque vote est relié au membre qui a voté {votes}')
pres.post(f'/members/{ids["Paul"]}/delete')
r = clients['Paul'].post(f'/votes/{pid}/vote', data={'option_id': opt['Awa']})
with app.app_context(), tenant_bypass():
    check(PollVote.query.filter_by(poll_id=pid).count() == 3, 'un membre retiré ne vote pas')
check(role('helene') == 'PRESIDENT' and role('marie') == 'MEMBRE', 'tant que le vote est ouvert, rien ne change')
check(clients['Marie'].post(f'/votes/{pid}/close').status_code in (302, 403) and role('marie') == 'MEMBRE',
      'un simple membre ne peut pas clore l\'élection')

# ---------------------------------------------------------------- clôture : le gagnant devient président
r = pres.post(f'/votes/{pid}/close', follow_redirects=True)
check('Marie Test est élu(e) président(e) avec 2 voix sur 3' in text(r) and 'Hélène Ngo redevient simple membre' in text(r),
      'clôture : Marie élue présidente (2 voix sur 3), Hélène redevient simple membre')
check(role('marie') == 'PRESIDENT' and role('helene') == 'MEMBRE', 'les rôles sont changés automatiquement')
check(clients['Marie'].get('/parametres').status_code == 200, 'Marie, nouvelle présidente, a accès aux Paramètres')
check(pres.get('/parametres').status_code != 200, "Hélène n'a plus les droits du président")
check('Résultat : Marie Test est élu(e)' in text(clients['Kofi'].get(f'/votes/{pid}')), 'tout le monde voit le résultat sur la page du vote')

# ---------------------------------------------------------------- égalité : rien ne change
marie = clients['Marie']
r = marie.post('/votes/add', data={'kind': 'ELECTION', 'election_role': 'TRESORIER',
                                   'candidates': [str(ids['Awa']), str(ids['Kofi'])]}, follow_redirects=True)
with app.app_context(), tenant_bypass():
    poll = Poll.query.filter_by(tontine_id=tid).order_by(Poll.id.desc()).first()
    tid2, o2 = poll.id, {o.label.split()[0]: o.id for o in poll.options}
vote('Awa', tid2, o2['Awa'])
vote('Kofi', tid2, o2['Kofi'])
r = marie.post(f'/votes/{tid2}/close', follow_redirects=True)
check('Égalité entre Awa Test et Kofi Test' in text(r) and role('awa') == 'MEMBRE' and role('kofi') == 'MEMBRE',
      'égalité : personne n\'est élu, il faut revoter')

# ---------------------------------------------------------------- élu à un autre poste : l'ancien poste est libéré
marie.post(f'/members/{ids["Kofi"]}/change-role', data={'role': 'TRESORIER'})
marie.post('/votes/add', data={'kind': 'ELECTION', 'election_role': 'SECRETAIRE',
                               'candidates': [str(ids['Kofi']), str(ids['Awa'])]})
with app.app_context(), tenant_bypass():
    poll = Poll.query.filter_by(tontine_id=tid).order_by(Poll.id.desc()).first()
    sid, o3 = poll.id, {o.label.split()[0]: o.id for o in poll.options}
vote('Kofi', sid, o3['Kofi'])
r = marie.post(f'/votes/{sid}/close', follow_redirects=True)
check(role('kofi') == 'SECRETAIRE' and 'Son ancien poste (Trésorier(ère)) est maintenant libre' in text(r),
      'Kofi (trésorier) élu secrétaire : le poste de trésorier est signalé libre')

# ---------------------------------------------------------------- le président ne se change plus à la main
r = marie.post(f'/members/{ids["Awa"]}/change-role', data={'role': 'PRESIDENT'}, follow_redirects=True)
check('se change par un vote' in text(r) and role('awa') == 'MEMBRE', 'nommer un président à la main : refusé, il faut une élection')
h = marie.get(f'/members/{ids["Awa"]}').get_data(as_text=True)
check('<option value="PRESIDENT"' not in h, 'la liste « Rôle dans le bureau » ne propose plus « Président »')
h = text(marie.get(f'/members/{ids["Marie"]}'))
check('organiser une élection' in h, 'sur la fiche de la présidente : lien pour organiser une élection')

# ---------------------------------------------------------------- vote simple : inchangé
r = marie.post('/votes/add', data={'kind': 'QUESTION', 'title': 'Augmenter la cotisation ?', 'options': 'Pour\nContre'},
               follow_redirects=True)
check('Le vote a été ouvert aux membres' in text(r), 'un vote « question » (Pour / Contre) fonctionne toujours')

print('\nRESULTAT :', 'ECHEC (%d)' % len(failed) if failed else 'TOUT OK')
for f in failed:
    print('  -', f)
