#!/usr/bin/env python
"""Create or promote a user to admin role.
Usage: python /app/bin/create_admin.py --email admin@example.com --password Secret123!
"""
import sys
import argparse
sys.path.insert(0, '/app')

from vbwd.extensions import Session
from vbwd.models.user import User
from vbwd.models.enums import UserStatus, UserRole
import bcrypt

parser = argparse.ArgumentParser()
parser.add_argument('--email',    default='admin@vbwd.local')
parser.add_argument('--password', default='ChangeMe123!')
args = parser.parse_args()

session = Session()
try:
    user = session.query(User).filter_by(email=args.email).first()
    if user:
        changed = False
        if user.role != UserRole.SUPER_ADMIN:
            user.role = UserRole.SUPER_ADMIN
            changed = True
        if user.status != UserStatus.ACTIVE:
            user.status = UserStatus.ACTIVE
            changed = True
        if changed:
            session.commit()
            print(f'Updated: {user.email} -> ADMIN / ACTIVE')
        else:
            print(f'Already admin: {user.email}')
    else:
        h = bcrypt.hashpw(args.password.encode(), bcrypt.gensalt()).decode()
        user = User(email=args.email, password_hash=h,
                    status=UserStatus.ACTIVE, role=UserRole.SUPER_ADMIN)
        session.add(user)
        session.commit()
        print(f'Created admin: {user.email} (id={user.id})')
except Exception as e:
    session.rollback()
    print(f'Error: {e}')
    sys.exit(1)
finally:
    session.close()
