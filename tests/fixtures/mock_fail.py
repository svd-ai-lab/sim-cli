"""Mock script that fails."""
import sys

print("something went wrong", file=sys.stderr)
sys.exit(1)
