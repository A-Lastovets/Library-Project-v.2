# Import all models here
# This way when we import Base to alembic env.py all models are also will be imported
# and changes applied to migration script

from app.dependencies.database import Base
from .wishlist import Wishlist

# example
# from app.models.users import Users
