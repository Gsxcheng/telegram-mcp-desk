class Channel:
    def __init__(self, broadcast, username=None):
        self.broadcast = broadcast
        self.username = username


class Chat:
    username = None


class User:
    def __init__(self, bot=False, username=None, first_name="", last_name=""):
        self.bot = bot
        self.username = username
        self.first_name = first_name
        self.last_name = last_name


class SentCodeTypeApp:
    pass
