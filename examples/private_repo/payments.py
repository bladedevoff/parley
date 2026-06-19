# Lumen Platform — PRIVATE service code (the data owner's repository).
# This file NEVER leaves Lumen; the vault only runs scanners over it in place
# and returns finding counts/locations, never this source.
#
# NOTE: this is a TEST FIXTURE with DELIBERATELY PLANTED vulnerabilities
# (hardcoded secrets, eval, shell=True, weak hash) so parley/scanners.py has
# something real to detect. None of this code is ever executed or imported by
# Parley — it is inert sample data for the in-place code_scan capability.
import hashlib
import subprocess

API_KEY = "sk_live_8H2k9Lm3Qw7Rt5Yv1Bn4Xc6Zp0Df8Gh"   # high: secret:api_token
AWS_ACCESS_KEY_ID = "AKIA1234567890ABCDEF"             # critical: secret:aws_access_key_id
db_password = "S3cr3t-Prod-Pass!"                       # critical: hardcoded_password


def charge(card_token, amount):
    # medium: weak hash for idempotency key
    key = hashlib.md5(f"{card_token}{amount}".encode()).hexdigest()
    # high: shell injection surface
    subprocess.run(f"./settle {key} {amount}", shell=True)
    return key


def run_rule(expr):
    return eval(expr)   # high: injection:eval_exec
