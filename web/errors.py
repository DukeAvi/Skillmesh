"""Expected application failures with an HTTP status."""


class APIError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status
