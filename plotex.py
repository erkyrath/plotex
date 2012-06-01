# PlotEx: a tool for exploring puzzle plot constraints
#   Version 1.0.2
#   Andrew Plotkin <erkyrath@eblong.com>
#   This script is in the public domain.
#
# For a full description, see <http://eblong.com/zarf/plotex/>

# This is the Python 2 version. For the Python 3 version, see plotex3.py.
# If you have Python 3 installed, you'll have to copy plotex3.py over
# plotex.py, or else change the "import plotex" lines in the examples to
# "import plotex3".

import sys
import optparse

class TrackMetaClass(type):
    '''TrackMetaClass does some Python magic to catalog the members of a
    class as it's being defined. We use this to catalog a scenario and set
    it up properly. (Thanks to Zack Weinberg and Aahz for magic support.)
    '''

    def __init__(cls, name, bases, dict):
        super(TrackMetaClass, cls).__init__(name, bases, dict)
        states = {}
        actions = {}
        tests = {}
        
        for (key, val) in dict.items():
            if (key.startswith('_')):
                continue
            if (isinstance(val, Action)):
                val.name = key
                actions[key] = val
            if (isinstance(val, State)):
                val.name = key
                states[key] = val
            if (isinstance(val, Test)):
                val.name = key
                tests[key] = val

        types = merge_typelists_of(actions.values() + states.values() + tests.values())
            
        senses = {}
        for key in types:
            if (key is None):
                # The Once action sometimes lacks a key. In those cases, it will
                # generate a negative sense boolean.
                continue
            senses[key] = (not key.startswith('_'))

        cls._statemap = states
        cls._actionmap = actions
        cls._testmap = tests
        cls._typemap = types
        cls._sensemap = senses
        
        for val in states.values():
            val.scenario = cls
        for val in actions.values():
            val.set_scenario(cls)
        for val in tests.values():
            val.set_scenario(cls)

def merge_typelists_of(ls):
    '''Given a list of objects (actions and states), pull the type map
    out of each one and return the union of all the maps. If they're not
    all consistent, raise an exception.
    '''
    typedic = {}
    for obj in ls:
        for (key, val) in obj.typelist.items():
            oldval = typedic.get(key)
            if (oldval is None):
                typedic[key] = val
                continue
            if (val != oldval):
                raise Exception('Inconsistent types for key "%s"' % (key,))
    return typedic
    
def infer_typelist(dic):
    '''Given a dictionary of qualities (as you'd see it in a State or
    Set definition), create a type map describing them. Each quality
    must be a number (int), string (str), boolean (bool), or sequence
    (set).
    '''
    res = {}
    for (key, val) in dic.items():
        typ = type(val)
        if (typ in (int, long)):
            res[key] = int
        elif (typ in (str, unicode)):
            res[key] = str
        elif (typ is bool):
            res[key] = bool
        elif (typ in (tuple, list, set, frozenset)):
            res[key] = set
        else:
            raise Exception('Value must be int, str, set, or bool: %s' % repr(val))
    return res

def parse_states(scenario, optls):
    '''Given a list of strings (as given on the command line), parse them
    as states. Arguments can be separate strings or comma-separated.
    Unrecognized states throw exceptions.
    '''
    res = set()
    for val in optls:
        ls = [ key.strip() for key in val.split(',') ]
        for key in ls:
            state = scenario._statemap.get(key)
            if (not state):
                raise Exception('No such state: "%s"' % (key,))
            res.add(state)
    return res

def parse_actions(scenario, optls):
    '''Given a list of strings (as given on the command line), parse them
    as actions. Arguments can be separate strings or comma-separated.
    Unrecognized actions throw exceptions.
    '''
    res = set()
    for val in optls:
        ls = [ key.strip() for key in val.split(',') ]
        for key in ls:
            action = scenario._actionmap.get(key)
            if (not action):
                raise Exception('No such action: "%s"' % (key,))
            res.add(action)
    return res

def parse_tests(scenario, optls):
    '''Given a list of strings (as given on the command line), parse them
    as tests. Arguments can be separate strings or comma-separated.
    Unrecognized tests throw exceptions.
    '''
    res = set()
    for val in optls:
        ls = [ key.strip() for key in val.split(',') ]
        for key in ls:
            test = scenario._testmap.get(key)
            if (not test):
                raise Exception('No such test: "%s"' % (key,))
            res.add(test)
    return res

class Graph:
    '''Graph: The context structure for doing a run. You set up a graph
    with some starting states, then tell it to run with some actions.
    The graph object can also display its results neatly.
    '''
    def __init__(self, scenario, states):
        self.scenario = scenario
        self.startstates = states
        self.states = {}
        self.allstates = []
        self.generations = []
        
    def run(self, actions, limit=10000):
        newstates = []
        for newstate in self.startstates:
            newstates.append(newstate)
            self.allstates.append(newstate)
            self.states[newstate] = GraphNode(newstate)
            
        while (newstates):
            if (len(self.states) >= limit):
                print 'WARNING: more than', limit, 'states! Stopping.'
                break
            oldstate = newstates.pop(0)
            for action in actions:
                oldnode = self.states[oldstate]
                newstate = action(oldstate)
                if (not newstate):
                    continue
                if (oldstate == newstate or newstate in oldnode.ancestors):
                    continue
                if (newstate <= oldstate):
                    continue

                newnode = self.states.get(newstate)
                if (newnode):
                    newnode.ancestors = newnode.ancestors.union(oldnode.ancestors)
                else:
                    newnode = GraphNode(newstate, oldnode.ancestors.union([newstate]))
                    newnode.history = oldnode.history + (action,)
                    newstates.append(newstate)
                    self.allstates.append(newstate)
                    self.states[newstate] = newnode

                oldnode.children.append( (action, newstate) )
                newnode.parents.append( (action, oldstate) )
            

    def has(self, state):
        return self.states.has_key(state)
    
    def display(self, showmed=False, showin=False, showout=False, showcount=False, filters=[], histories=[]):
        outls = []
        for state in self.allstates:
            node = self.states[state]
            if (not showmed):
                if (node.children):
                    continue
            filtered = False
            for filter in filters:
                if (not state.dic.has_key(filter)):
                    filtered = True
            if (filtered):
                continue
            for histac in histories:
                if (histac not in node.history):
                    filtered = True
            if (filtered):
                continue
            outls.append(state)

        trumped = None
        if (len(outls) <= 20):
            trumped = set()
            for state1 in outls:
                if (state1 in trumped):
                    continue
                for state2 in outls:
                    if (state2 in trumped):
                        continue
                    if (state1 == state2):
                        continue
                    if (state2 < state1):
                        trumped.add(state2)

        if (not showcount):
            for state in outls:
                node = self.states[state]
                val = ''
                if (trumped is not None and state not in trumped):
                    val = '*'
                print val+str(state)
                acs = [ ac.name for ac in node.history]
                print '  (%d): %s' % (len(node.history), ', '.join(acs),)
                #print '  ### ancs:', list(node.ancestors)
                if (showin):
                    subls = [ '<= %s : %s' % (substate, ac.name) for (ac, substate) in node.parents ]
                    for val in subls:
                        print '    %s' % (val,)
                if (showout):
                    subls = [ '=> %s : %s' % (ac.name, substate) for (ac, substate) in node.children ]
                    for val in subls:
                        print '    %s' % (val,)
                print
                
        if (showmed):
            summary = '%d total states' % (len(outls),)
        else:
            summary = '%d terminal states' % (len(outls),)
        if (trumped):
            val = len(outls) - len(trumped)
            summary += ' (%d preferred)' % (val,)
        if (filters):
            summary += ' with "' + '", "'.join(filters) + '"'
        if (histories):
            subls = [ ac.name for ac in histories ]
            subls.sort()
            summary += ' with ' + ', '.join(subls)
        print summary, 'reached'

class GraphNode:
    '''GraphNode: Context information for a single state in a Graph.
    (We never store information in the State itself -- that's immutable.)
    '''
    def __init__(self, state, ancestors=None):
        self.state = state
        if (ancestors is None):
            ancestors = frozenset([state])
        self.ancestors = ancestors
        self.parents = []
        self.children = []
        self.history = ()
            
class State:
    '''State: One state in the plot diagram. A state is set up with a
    bunch of qualities.

    The most interesting thing you can do with states is compare them.
    State1 < state2 if state1's qualities are a subset of state2's.
    This is a partial ordering; it is not necessarily true that
    (x < y or x == y or x > y). Sometimes two states are just different.
    '''
    name = None
    scenario = None
    def __init__(self, **dic):
        self.typelist = infer_typelist(dic)
        self.hashcache = None
        if (not dic):
            self.dic = {}
            return
        self.dic = dic
        self.canonize()
    def __repr__(self):
        keyls = self.dic.keys()
        keyls.sort(key=lambda x:x.upper())
        ls = []
        for key in keyls:
            val = self.dic[key]
            if (isinstance(val, frozenset)):
                val = list(val)
                val.sort()
                val = '[' + ','.join(str(subval) for subval in val) + ']'
            if (val is True):
                ls.append('%s' % (key,))
            else:
                ls.append('%s=%s' % (key, val))
        joined = ' '.join(ls)
        if (self.name):
            return '<"%s": %s>' % (self.name, joined)
        else:
            return '<%s>' % (joined,)
    def __eq__(self, other):
        return (self.dic == other.dic)
    def __ne__(self, other):
        return (self.dic != other.dic)
    def __gt__(self, other):
        return (self != other) and self.contains(other)
    def __ge__(self, other):
        return self.contains(other)
    def __lt__(self, other):
        return (self != other) and other.contains(self)
    def __le__(self, other):
        return other.contains(self)
    def __hash__(self):
        if (self.hashcache is None):
            ls = [ pair for pair in self.dic.items() ]
            ls.sort()
            self.hashcache = hash(tuple(ls))
        return self.hashcache
    def canonize(self):
        ls = [ key for (key, val) in self.dic.items() if not val ]
        for key in ls:
            self.dic.pop(key)
        ls = [ key for (key, val) in self.dic.items() if type(val) in (tuple, list) ]
        for key in ls:
            orig = self.dic[key]
            self.dic[key] = frozenset(orig)
    def copy(self):
        res = State()
        res.scenario = self.scenario
        res.dic = dict(self.dic)
        return res
    def contains(self, other):
        '''X.contains(Y) is the basic comparison -- X is a subset of (or
        equal to) Y.
        '''
        for (key, oval) in other.dic.items():
            if (not self.scenario._sensemap[key]):
                continue
            if (not self.atleast(key, oval)):
                return False
        for (key, ival) in self.dic.items():
            if (self.scenario._sensemap[key]):
                continue
            if (not other.atleast(key, ival)):
                return False
        return True
    def atleast(self, key, val):
        '''X.atleast(key, val) tests whether the key quality is val or better.
        (This does *not* account for negative-sense keys, so don't call it
        on them.)
        '''
        if (not val):
            return True
        ival = self.dic.get(key)
        if (ival is None):
            return False
        typ = self.scenario._typemap[key]
        if (typ is int):
            if (ival < val):
                return False
        elif (typ is set):
            if (not ival.issuperset(frozenset(val))):
                return False
        else:
            if (ival != val):
                return False
        return True
    def atmost(self, key, val):
        '''X.atmost(key, val) tests whether the key quality is val or worse.
        (Call this for negative-sense keys.)
        '''
        ival = self.dic.get(key)
        if (not val and not ival):
            return True
        if (not val):
            return False
        if (ival is None):
            return True
        typ = self.scenario._typemap[key]
        if (typ is int):
            if (ival > val):
                return False
        elif (typ is set):
            if (not ival.issubset(frozenset(val))):
                return False
        else:
            if (ival != val):
                return False
        return True

class Test:
    name = '???'
    scenario = None
    def __init__(self, **dic):
        self.startstatelist = []
        val = dic.pop('start', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.startstatelist.append(val)
            else:
                for state in val:
                    self.startstatelist.append(state)
         
        self.blockactions = set()
        val = dic.pop('block', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.blockactions.add(val)
            else:
                for ac in val:
                    self.blockactions.add(ac)

        self.includeactions = []
        val = dic.pop('includes', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.includeactions.append(val)
            else:
                for ac in val:
                    self.includeactions.append(ac)
                
        self.excludeactions = []
        val = dic.pop('excludes', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.excludeactions.append(val)
            else:
                for ac in val:
                    self.excludeactions.append(ac)
                
        self.canactions = []
        val = dic.pop('can', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.canactions.append(val)
            else:
                for ac in val:
                    self.canactions.append(ac)
                
        self.cannotactions = []
        val = dic.pop('cannot', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.cannotactions.append(val)
            else:
                for ac in val:
                    self.cannotactions.append(ac)

        self.getqualities = []
        val = dic.pop('gets', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.getqualities.append(val)
            else:
                for ac in val:
                    self.getqualities.append(ac)

        self.getnotqualities = []
        val = dic.pop('getsnot', None)
        if (val is not None):
            if (type(val) not in (list, tuple)):
                self.getnotqualities.append(val)
            else:
                for ac in val:
                    self.getnotqualities.append(ac)
        if (dic):
            raise TypeError('Test() got unknown argument: %s' % (', '.join(dic.keys()),))

        ls = list(self.blockactions) + self.startstatelist + self.canactions + self.cannotactions
        self.typelist = merge_typelists_of(ls)

    def __repr__(self):
        return '<Test "%s">' % (self.name,)
    def set_scenario(self, scen):
        self.scenario = scen
        for state in self.startstatelist:
            state.scenario = scen
        for ac in self.canactions + self.cannotactions:
            ac.set_scenario(scen)
         
    def startstates(self):
        if (not self.startstatelist):
            state = self.scenario._statemap['Start']
            return [state]
        return self.startstatelist
         
    def actions(self):
        actions = [ action for action in self.scenario._actionmap.values() if action not in self.blockactions ]
        return actions
         
    def verify(self, graph):
        states = graph.states.keys()
        for qual in self.getqualities:
            states = [ state for state in states if state.dic.has_key(qual) ]
            if (not states):
                return False
        for ac in self.canactions:
            states = [ state for state in states if ac(state) ]
            if (not states):
                return False
        for ac in self.includeactions:
            states = [ state for state in states if (ac in graph.states[state].history) ]
            if (not states):
                return False
        for qual in self.getnotqualities:
            ls = [ state for state in states if state.dic.has_key(qual) ]
            if (ls):
                return False
        for ac in self.cannotactions:
            ls = [ state for state in states if ac(state) ]
            if (ls):
                return False
        for ac in self.excludeactions:
            ls = [ state for state in states if (ac in graph.states[state].history) ]
            if (ls):
                return False
        return True
      
class Action:
    '''Action: An abstract action in a scenario. Calling Action(State)
    will return a new State, or None if the Action isn't possible in that
    state.
    '''
    name = '???'
    scenario = None
    unnamedcount = 0
    def __repr__(self):
        return '<Action "%s">' % (self.name,)
    def __call__(self, state):
        raise NotImplementedError('Action type not implemented')
    def subactions(self):
        return None
    def set_scenario(self, scen):
        self.scenario = scen
        ls = self.subactions()
        if ls:
            for ac in ls:
                ac.set_scenario(scen)
    def new_state(self, dic):
        '''If an Action has to generate a new State, it calls this factory
        method. This ensures that the State's scenario field is set
        correctly.
        '''
        res = State(**dic)
        res.scenario = self.scenario
        return res

class Set(Action):
    def __init__(self, **dic):
        self.typelist = infer_typelist(dic)
        self.params = dic
    def __call__(self, state):
        dic = dict(state.dic)
        for (key, val) in self.params.items():
            dic[key] = val
        return self.new_state(dic)

class Reset(Action):
    def __init__(self, **dic):
        self.typelist = infer_typelist(dic)
        self.params = dic
    def __call__(self, state):
        dic = {}
        for (key, val) in self.params.items():
            dic[key] = val
        return self.new_state(dic)

class Has(Action):
    def __init__(self, **dic):
        self.typelist = infer_typelist(dic)
        self.params = dic
    def __call__(self, state):
        for (key, val) in self.params.items():
            if (self.scenario._sensemap[key]):
                if (not state.atleast(key, val)):
                    return
            else:
                if (not state.atmost(key, val)):
                    return
        return state

class HasAny(Action):
    def __init__(self, **dic):
        self.typelist = infer_typelist(dic)
        self.params = dic
    def __call__(self, state):
        for (key, val) in self.params.items():
            if (self.scenario._sensemap[key]):
                if (state.atleast(key, val)):
                    return state
            else:
                if (state.atmost(key, val)):
                    return state
        return

class Lose(Action):
    def __init__(self, *keys):
        self.typelist = {}
        self.keys = keys
    def __call__(self, state):
        dic = dict(state.dic)
        for key in self.keys:
            if (not dic.has_key(key)):
                return
        for key in self.keys:
            dic.pop(key)
        return self.new_state(dic)

class Once(Action):
    def __init__(self, key=None):
        if (isinstance(key, Action)):
            self.typelist = merge_typelists_of([key])
            self.action = key
            self.key = None
        else:
            self.typelist = { key: bool }
            self.action = None
            self.key = key
    def subactions(self):
        if (self.action):
            return [self.action]
    def set_scenario(self, scen):
        Action.set_scenario(self, scen)
        if (self.key is None):
            if (self.name == '???'):
                Action.unnamedcount = Action.unnamedcount + 1
                self.key = '_did_action_%d' % (Action.unnamedcount,)
            else:
                self.key = '_did_%s' % (self.name.lower())
            scen._typemap[self.key] = bool
            scen._sensemap[self.key] = False
    def __call__(self, state):
        dic = dict(state.dic)
        if (not self.scenario._sensemap[self.key]):
            if (dic.has_key(self.key)):
                return
            dic[self.key] = True
        else:
            if (not dic.has_key(self.key)):
                return
            dic[self.key] = False
        newstate = self.new_state(dic)
        if (not self.action):
            return newstate
        else:
            return self.action(newstate)
        
class Increment(Action):
    def __init__(self, key, limit=None):
        self.typelist = { key: int }
        self.key = key
        self.limit = limit
    def __call__(self, state):
        dic = dict(state.dic)
        val = dic.get(self.key, 0)
        if (self.limit is not None and val >= self.limit):
            return
        dic[self.key] = val+1
        return self.new_state(dic)

class Decrement(Action):
    def __init__(self, key, limit=0):
        self.typelist = { key: int }
        self.key = key
        self.limit = limit
    def __call__(self, state):
        dic = dict(state.dic)
        val = dic.get(self.key, 0)
        if (self.limit is not None and val <= self.limit):
            return
        dic[self.key] = val-1
        return self.new_state(dic)

class Include(Action):
    def __init__(self, key, *vals):
        self.typelist = { key: set }
        self.key = key
        self.values = frozenset(vals)
    def __call__(self, state):
        dic = dict(state.dic)
        val = dic.get(self.key, frozenset())
        dic[self.key] = val.union(self.values)
        return self.new_state(dic)

class Exclude(Action):
    def __init__(self, key, *vals):
        self.typelist = { key: set }
        self.key = key
        self.values = frozenset(vals)
    def __call__(self, state):
        dic = dict(state.dic)
        val = dic.get(self.key, frozenset())
        if (not val.issuperset(self.values)):
            return
        dic[self.key] = val.difference(self.values)
        return self.new_state(dic)

class Count(Action):
    def __init__(self, key, count):
        self.typelist = { key: set }
        self.key = key
        self.count = count
    def __call__(self, state):
        val = state.dic.get(self.key, frozenset())
        if (len(val) < self.count):
            return
        return state

class HasDifferent(Action):
    def __init__(self, key, *vals):
        self.typelist = { key: str }
        self.key = key
        self.values = frozenset(vals)
    def __call__(self, state):
        val = state.dic.get(self.key)
        if (val is None):
            return
        if (val in self.values):
            return
        return state

class Chain(Action):
    def __init__(self, *actions):
        self.typelist = merge_typelists_of(actions)
        self.actions = actions
    def subactions(self):
        return self.actions
    def __call__(self, state):
        for action in self.actions:
            state = action(state)
            if not state:
                return
        return state
    
class Choice(Action):
    def __init__(self, *actions):
        self.typelist = merge_typelists_of(actions)
        self.actions = actions
    def subactions(self):
        return self.actions
    def __call__(self, state):
        for action in self.actions:
            newstate = action(state)
            if newstate:
                return newstate
        return
    
def shell(scenario):
    '''This is the top-level function; it processes the command-line options,
    sets up the graph, and does the run.

    Call this, passing your scenario class as the argument.
    '''
    popt = optparse.OptionParser()

    popt.add_option('-s', '--start',
                    action='append', dest='startstates', metavar='STATES',
                    default=[],
                    help='state(s) to begin at (default: Start)')
    popt.add_option('--block',
                    action='append', dest='blockactions', metavar='ACTIONS',
                    default=[],
                    help='actions to forbid for this run')
    popt.add_option('--withhold',
                    action='append', dest='withholdactions', metavar='ACTIONS',
                    default=[],
                    help='actions to hold until last')
    popt.add_option('-t', '--test',
                    action='append', dest='runtests', metavar='TESTS',
                    default=[],
                    help='test(s) to run')
    popt.add_option('-T', '--alltest', '--alltests',
                    action='store_true', dest='runalltests',
                    help='run all tests')
    popt.add_option('--genlimit',
                    action='store', type=int, dest='genlimit', default=10000,
                    help='maximum number of states to generate')
    popt.add_option('-m', '--showmed',
                    action='store_true', dest='showmed',
                    help='display all intermediate states')
    popt.add_option('--showin',
                    action='store_true', dest='showin',
                    help='display actions into each state')
    popt.add_option('--showout',
                    action='store_true', dest='showout',
                    help='display actions out of each state')
    popt.add_option('-a', '--showall',
                    action='store_true', dest='showall',
                    help='combines --showmed --showin --showout')
    popt.add_option('-c', '--count',
                    action='store_true', dest='showcount',
                    help='display only the number of states found')
    popt.add_option('-f', '--filter',
                    action='append', dest='filters', metavar='QUALITIES',
                    default=[],
                    help='display only states containing this quality')
    popt.add_option('-H', '--history',
                    action='append', dest='histories', metavar='ACTIONS',
                    default=[],
                    help='display only states that passed through this action')

    (opts, args) = popt.parse_args()

    if (opts.showall):
        opts.showmed = True
        opts.showin = True
        opts.showout = True
    
    if (not opts.startstates):
        opts.startstates.append('Start')
    startstates = parse_states(scenario, opts.startstates)

    blockactions = parse_actions(scenario, opts.blockactions)

    runtests = parse_tests(scenario, opts.runtests)
    if (opts.runalltests):
        runtests = scenario._testmap.values()

    if (runtests):
        runtests = list(runtests)
        runtests.sort(key=lambda ac:ac.name)
        errors = 0
        for test in runtests:
            actions = test.actions()
            actions.sort(key=lambda ac:ac.name)
            graph = Graph(scenario, test.startstates())
            graph.run(actions, limit=opts.genlimit)
            if test.verify(graph):
                print '%s: pass' % (test.name,)
            else:
                errors = errors+1
                print '%s: FAIL' % (test.name,)
        if (errors):
            print '%d errors!' % (errors,)
        return
             
    withholdactions = None
    if (opts.withholdactions):
        withholdactions = parse_actions(scenario, opts.withholdactions)
        blockactions = blockactions.union(withholdactions)

    actions = [ action for action in scenario._actionmap.values() if action not in blockactions ]
    actions.sort(key=lambda ac:ac.name)
    graph = Graph(scenario, startstates)
    graph.run(actions, limit=opts.genlimit)
    if (withholdactions):
        ls = list(graph.allstates)
        ls.reverse()
        betterls = []
        for state in ls:
            for newstate in betterls:
                if (newstate > state):
                    break
            else:
                betterls.append(state)
        betterls.reverse()
        for action in withholdactions:
            actions.append(action)
        graph = Graph(scenario, betterls)
        graph.run(actions, limit=opts.genlimit)

    filters = []
    for val in opts.filters:
        for subval in val.split(','):
            filters.append(subval.strip())
    histories = []
    if (opts.histories):
        histories = parse_actions(scenario, opts.histories)
    graph.display(opts.showmed, opts.showin, opts.showout, opts.showcount, filters, histories)

class ScenarioClass:
    __metaclass__ = TrackMetaClass

class TestScenario(ScenarioClass):

    # Our actions
    FindSword = Set(sword=True)
    FindLamp = Set(lamp=True)
    EnterCave = Chain(Has(lamp=True), Set(underground=True))
    FeedSelf = Lose('food')
    FeedCyclops = Chain(Has(underground=True), Lose('food'), Set(kitchen=True))
    FeedOrc = Chain(Lose('food'), Set(pants=True))
    KitchenCook = Chain(Has(kitchen=True), Set(food=True))

    # Our (sole) starting state
    Start = State(food=True)

    # Tests to verify the scenario
    Test1 = Test(start=Start, gets='pants')
    Test2 = Test(can=Has(pants=True))
    Test3 = Test(cannot=Has(wand=True))
    Test4 = Test(block=KitchenCook, cannot=Has(pants=True, kitchen=True))
    Test5 = Test(start=State(), getsnot='pants')
    Test6 = Test(includes=KitchenCook)
    Test7 = Test(block=FeedCyclops, excludes=KitchenCook)

if __name__ == '__main__':
    shell(TestScenario)
