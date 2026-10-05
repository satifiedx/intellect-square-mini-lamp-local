from amqtt.plugins.base import BaseAuthPlugin

CREDS: dict = {}


class CapturePlugin(BaseAuthPlugin):
    async def authenticate(self, *, session):
        if session and session.username:
            CREDS["user"] = session.username
            CREDS["password"] = session.password
        return True
