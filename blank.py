# A blank PlotEx scenario.
#   Andrew Plotkin <erkyrath@eblong.com>
#   This script is in the public domain.
#
# For a full description, see <http://eblong.com/zarf/plotex/>


from plotex import *

class Scenario(ScenarioClass):
    
    # The starting state: player has nothing.
    
    Start = State()

    # The actions: this scenario has none. Start writing some.
    


# This parses and carries out the command-line options, using the Scenario.
shell(Scenario)
