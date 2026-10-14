"""Account recovery, identity editing, deactivation, and logout revocation."""
from datetime import timedelta
from unittest.mock import patch
import re

import pytest
from fastapi.testclient import TestClient
import account_service as accounts
import database as store
from main import app
from test_league import client,post,token,seed_admin

PASSWORD='MemberPassword123!'


def member(name='account_member',role='player',email='member@example.com'):
    return store.create_account(name,PASSWORD,role,email)


@pytest.mark.parametrize('username',['аlice','Ａlice','José','ab','123456','a b'])
def test_ascii_username_validation_rejects_confusables(client,username):
    with pytest.raises(ValueError):
        store.create_account(username,PASSWORD,'player','valid@example.com')


@pytest.mark.parametrize('email',['','no-at','a@localhost','a..b@example.com','a@-host.com','a\n@example.com'])
def test_registration_requires_valid_email(client,email):
    csrf=token(client)
    response=client.post('/register',data={'csrf':csrf,'username':'email_member','role':'player','password':PASSWORD,'email':email})
    assert 'Enter a valid email address.' in response.text
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0


def test_email_unique_normalized_and_registration_does_not_send_verification(client):
    with patch('account_service.send_recovery',side_effect=AssertionError('No verification email')):
        post(client,'/register',username='unique_email',role='player',password=PASSWORD,email='User@Example.COM')
    with store.read_db() as db:
        assert db.execute('SELECT email FROM users').fetchone()[0]=='user@example.com'
    with pytest.raises(ValueError,match='email address is already taken'):
        member('another_email',email='USER@example.com')


def test_profile_edit_validation_lock_and_administrator_override(client):
    uid=member();seed_admin()
    accounts.update_profile(uid,'Maria Silva','Portugal','123456')
    post(client,'/login',username='account_member',password=PASSWORD)
    response=post(client,'/account/settings',name='Maria Silva',country='Portugal',fide_id='123456',email='member@example.com')
    assert 'Account settings saved.' in response.text
    with store.transaction() as db:
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    accounts.update_profile(uid,'Maria Edited','Portugal','123456',actor_id=admin,fide_id_locked=True)
    with pytest.raises(ValueError,match='locked'):
        accounts.update_profile(uid,'Maria Silva','Portugal','234567')
    with pytest.raises(ValueError,match='6 to 8'):
        accounts.update_profile(uid,'Maria Silva','Portugal','１２３４５６')
    accounts.update_profile(uid,'Admin Edit','Portugal','23456789',actor_id=admin,fide_id_locked=True)
    assert accounts.account(uid)['fide_id']=='23456789'
    assert '23456789' in client.get('/account/settings').text


def test_email_change_requires_password_and_invalidates_old_recovery(client):
    uid=member();raw=accounts.issue_reset('account_member','member@example.com')
    with pytest.raises(ValueError,match='current password'):
        accounts.update_profile(uid,'Member Name','','',email='new@example.com',current_password='wrong')
    accounts.update_profile(uid,'Member Name','','',email='new@example.com',current_password=PASSWORD)
    with pytest.raises(ValueError,match='invalid or expired'):
        accounts.reset_password(raw,'NewPassword123!')
    assert accounts.account(uid)['email']=='new@example.com'


def test_recovery_single_use_expiry_hashing_and_session_revocation(client,monkeypatch):
    uid=member();post(client,'/login',username='account_member',password=PASSWORD)
    old_cookie=client.cookies.get('session')
    raw=accounts.issue_reset('account_member','member@example.com')
    with store.read_db() as db:
        row=db.execute('SELECT * FROM password_resets').fetchone()
        assert raw not in str(dict(row))
    accounts.reset_password(raw,'RecoveredPassword123!')
    with pytest.raises(ValueError,match='invalid or expired'):
        accounts.reset_password(raw,'RecoveredAgain123!')
    client.cookies.clear()
    client.cookies.set('session',old_cookie)
    assert client.get('/account/settings',headers={'Accept':'application/json'}).status_code==401
    assert post(client,'/login',username='account_member',password='RecoveredPassword123!').status_code==200
    raw=accounts.issue_reset('account_member','member@example.com')
    later=store.now_utc()+timedelta(hours=2)
    monkeypatch.setattr(store,'now_utc',lambda:later)
    with pytest.raises(ValueError,match='invalid or expired'):
        accounts.reset_password(raw,'ExpiredPassword123!')


def test_logout_invalidates_copied_cookie(client):
    member();post(client,'/login',username='account_member',password=PASSWORD)
    stolen=client.cookies.get('session')
    post(client,'/logout')
    client.cookies.clear()
    client.cookies.set('session',stolen)
    assert client.get('/account/settings',headers={'Accept':'application/json'}).status_code==401


def test_deactivation_blocks_login_reset_and_reactivation_requires_admin(client):
    uid=member();seed_admin()
    admin=next_user('commissioner')
    with pytest.raises(ValueError,match='administrators'):
        accounts.set_account_active(uid,True,actor_id=uid)
    accounts.set_account_active(uid,False,actor_id=uid,password=PASSWORD)
    assert accounts.issue_reset('account_member','member@example.com') is None
    assert 'The account has been deactivated. Please contact the administrator to reactivate it.' in post(client,'/login',username='account_member',password=PASSWORD).text
    accounts.set_account_active(uid,True,actor_id=admin)
    assert 'Welcome back' not in post(client,'/login',username='account_member',password=PASSWORD).text
    with pytest.raises(ValueError,match='last active administrator'):
        accounts.set_account_active(admin,False,actor_id=admin,password='adminpass123!')


def next_user(username):
    with store.read_db() as db:
        return db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()[0]


def test_smtp_recovery_uses_tls_and_fragment_token(client,monkeypatch):
    member()
    for key,value in {'CHESS_SMTP_HOST':'smtp.example.com','CHESS_SMTP_FROM':'liga@example.com','CHESS_PUBLIC_URL':'https://club.test'}.items():
        monkeypatch.setenv(key,value)
    with patch('account_service.smtplib.SMTP') as smtp:
        accounts.send_recovery('account_member','member@example.com')
        transport=smtp.return_value
        assert transport.starttls.called
        message=transport.send_message.call_args.args[0]
        assert '/reset-password#token=' in message.get_content()
        assert '/reset-password?token=' not in message.get_content()


def test_recovery_request_generic_and_all_admin_pages_authorized(client):
    with patch('account_service.send_recovery') as sender:
        result=post(client,'/forgot-password',email='unknown@example.com')
        assert 'If the username and email match an active account' in result.text
        sender.assert_called_once_with('', 'unknown@example.com')
    for url in ['/admin/accounts','/admin/seasons','/admin/teams','/admin/roles','/admin/players']:
        assert client.get(url,headers={'Accept':'application/json'}).status_code==401
    seed_admin();post(client,'/login',username='commissioner',password='adminpass123!')
    for url in ['/admin/accounts','/admin/seasons','/admin/teams','/admin/roles','/admin/players']:
        assert client.get(url).status_code==200
    assert 'Activate a player' in client.get('/admin/players').text
    assert 'Role activation requests' not in client.get('/admin/teams').text.split('</nav>',2)[-1] # section is separate
