import re
import time

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import commerce, commerce_models as m
from tests.test_commerce import env


def test_registration_returns_to_invitation_without_auto_accept(env):
    token = 'invitation-token-for-test-1234567890'
    path = '/invite/' + token
    with env() as db:
        db.add(m.Invitation(merchant_id=1, email='invitee@example.test', token_hash=commerce.digest(token),
                            invited_by=1, expires=int(time.time()) + 3600))
        db.commit()
    browser = TestClient(commerce.app)
    invite = browser.get(path)
    assert '/register?next=' in invite.text
    page = browser.get('/register', params={'next': path})
    assert f'name="next" value="{path}"' in page.text
    csrf = browser.cookies.get('kora_form')
    result = browser.post('/register', data={'csrf': csrf, 'email': 'invitee@example.test',
        'name': 'New teammate', 'password': 'A-secure-password-2026', 'next': path}, follow_redirects=False)
    assert result.status_code == 303 and result.headers['location'] == path
    page = browser.get(path)
    assert 'Accept invitation' in page.text
    with env() as db:
        assert not db.scalar(select(m.Invitation)).accepted
        user = db.scalar(select(m.User).where(m.User.email == 'invitee@example.test'))
        assert not db.scalar(select(m.Membership).where(m.Membership.user_id == user.id))
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    assert browser.post(path, data={'csrf': csrf}, follow_redirects=False).status_code == 303
    with env() as db:
        assert db.scalar(select(m.Invitation)).accepted


def test_auth_rejects_external_return_paths():
    for path in ('https://evil.example', '//evil.example', '/invite/../logout', '/app/1'):
        assert commerce.invitation_return(path) == ''
