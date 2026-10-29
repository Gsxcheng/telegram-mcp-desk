class RPCError(Exception):
    pass


class PhoneNumberInvalidError(RPCError):
    pass


class PhoneNumberBannedError(RPCError):
    pass


class PhoneCodeInvalidError(RPCError):
    pass


class PhoneCodeExpiredError(RPCError):
    pass


class SessionPasswordNeededError(RPCError):
    pass


class PasswordHashInvalidError(RPCError):
    pass


class FloodWaitError(RPCError):
    def __init__(self, seconds=30):
        super().__init__(f"wait {seconds}")
        self.seconds = seconds
