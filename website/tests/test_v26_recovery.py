from unittest.mock import patch
import pytest
import account_service as accounts
import database as store
from test_league import client, post, seed_admin

PASSWORD='RecoveryPassword123!'

@pytest.mark.parametrize('username,email',[
    ('','member@example.com'),('other_member','member@example.com'),
    ('recovery_member','other@example.com'),('recovery_member','invalid'),
])
def test_recovery_requires_both_matching_details(client,username,email):
    store.create_account('recovery_member',PASSWORD,'player','member@example.com')
    assert accounts.issue_reset(username,email) is None
    with store.read_db() as db:
        assert db.execute('SELECT COUNT(*) FROM password_resets').fetchone()[0]==0
    with patch('account_service.send_recovery') as sender:
        response=post(client,'/forgot-password',username=username,email=email)
        assert 'If the username and email match an active account' in response.text
        sender.assert_called_once_with(username,email)


def test_matching_username_and_email_issue_reset_case_insensitively(client):
    store.create_account('recovery_member',PASSWORD,'player','member@example.com')
    raw=accounts.issue_reset(' RECOVERY_MEMBER ','MEMBER@EXAMPLE.COM')
    assert raw
    accounts.reset_password(raw,'ReplacementPassword123!')
    assert post(client,'/login',username='recovery_member',password='ReplacementPassword123!').status_code==200


def test_deactivated_login_explains_reactivation_after_password_check(client):
    uid=store.create_account('recovery_member',PASSWORD,'player','member@example.com')
    seed_admin()
    with store.read_db() as db:
        admin=db.execute("SELECT id FROM users WHERE role='admin'").fetchone()[0]
    accounts.set_account_active(uid,False,actor_id=admin)
    response=post(client,'/login',username='recovery_member',password=PASSWORD)
    assert 'The account has been deactivated. Please contact the administrator to reactivate it.' in response.text
    assert client.get('/account/settings',headers={'Accept':'application/json'}).status_code==401
    wrong=post(client,'/login',username='recovery_member',password='WrongPassword123!')
    assert 'Incorrect username or password.' in wrong.text
    assert 'The account has been deactivated.' not in wrong.text
    assert accounts.issue_reset('recovery_member','member@example.com') is None
