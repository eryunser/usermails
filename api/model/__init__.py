from .user import User
from .email_account import EmailAccount
from .email import Email
from .draft import Draft

# This file makes the 'models' directory a Python package.
# Importing the models here ensures that SQLAlchemy's Base metadata
# is aware of all models when any part of the package is imported,
# which is crucial for resolving relationships between them.
