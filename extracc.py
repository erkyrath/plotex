# This module demonstrates how to build a custom Check class for regtest.py.
# The Check defined here tries to match an entire line of the output.
# That is, a check line
#
#   ++ You see a ghost.
#
# ...will only succeed if that string appears as a complete line in the
# current command of the test run. This is not a useful test in the real
# world, but it demonstrates the class structure.

from __main__ import Check

class WholeLineCheck(Check):
    
    @classmethod
    def buildcheck(cla, ln, args):
        # Match a check line that begins with "++". If it does, return
        # an instance of this class. Otherwise, return None.
        if (ln.startswith('++')):
            return WholeLineCheck(ln[2:].strip(), **args)

    def subeval(self, lines):
        # Run the check. The lines argument is an array of complete lines
        # from the current command of the test run. Return None if the
        # test succeeds, or a failure string.
        for ln in lines:
            if self.ln == ln:
                return
        return 'not matched'
