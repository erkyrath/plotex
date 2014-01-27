# RegTest: a really simple IF regression tester.
#   Version 1.3
#   Andrew Plotkin <erkyrath@eblong.com>
#   This script is in the public domain.
#
# For a full description, see <http://eblong.com/zarf/plotex/regtest.html>
#
# (This software is not connected to PlotEx; I'm just distributing them
# from the same folder.)

import sys
import os
import optparse
import select
import fnmatch
import subprocess
import re

gamefile = None
terppath = None
terpargs = []
remformat = False
precommands = []

testmap = {}
testls = []
totalerrors = 0

popt = optparse.OptionParser()

popt.add_option('-g', '--game',
                action='store', dest='gamefile',
                help='game to test')
popt.add_option('-i', '--interpreter', '--terp',
                action='store', dest='terppath',
                help='interpreter to execute')
popt.add_option('-l', '--list',
                action='store_true', dest='listonly',
                help='list all tests (or all matching tests)')
popt.add_option('-p', '--pre', '--precommand',
                action='append', dest='precommands',
                help='extra command to execute before (each) test')
popt.add_option('-r', '--rem',
                action='store_true', dest='remformat',
                help='the interpreter uses RemGlk (JSON) format')
popt.add_option('-v', '--verbose',
                action='store_true', dest='verbose',
                help='display the transcripts as they run')

(opts, args) = popt.parse_args()

if (not args):
    print 'usage: regtest.py TESTFILE [ TESTPATS... ]'
    sys.exit(1)

class RegTest:
    """RegTest represents one test in the test file. (That is, a block
    beginning with a single asterisk.)

    A test is one session of the game, from the beginning. (Not necessarily
    to the end.) After every game command, tests can be run.
    """
    def __init__(self, name):
        self.name = name
        self.gamefile = None   # use global gamefile
        self.terp = None       # global terppath, terpargs
        self.precmd = None
        self.cmds = []
    def __repr__(self):
        return '<RegTest %s>' % (self.name,)
    def addcmd(self, cmd):
        self.cmds.append(cmd)

class Command:
    """Command is one cycle of a RegTest -- a game input, followed by
    tests to run on the game's output.
    """
    def __init__(self, cmd):
        self.cmd = cmd
        self.checks = []
    def __repr__(self):
        return '<Command "%s">' % (self.cmd,)
    def addcheck(self, ln):
        inverse = False
        instatus = False
        # First peel off "!" and "{...}" prefixes
        while True:
            match = re.match('!|{[a-z]*}', ln)
            if not match:
                break
            ln = ln[match.end() : ].strip()
            val = match.group()
            if val == '!' or val == '{invert}':
                inverse = True
            elif val == '{status}':
                instatus = True
            else:
                raise Exception('Unknown test modifier: %s' % (val,))
        # Then the test itself, which may have many formats
        if (ln.startswith('/')):
            check = RegExpCheck(ln[1:].strip(), inverse=inverse, instatus=instatus)
        else:
            check = LiteralCheck(ln, inverse=inverse, instatus=instatus)
        self.checks.append(check)

class Check:
    """Represents a single test (applied to the output of a game command).

    This can be applied to the story window or the status window;
    it can apply direct or inverted. (The model is simplistic and assumes
    there is exactly one story window and at most one status window.)
    
    This is a virtual base class. Subclasses should override the subeval()
    method to examine a list of lines, and return None (on success) or a
    string (explaining the failure).
    """
    inverse = False
    instatus = False
    
    def eval(self, state):
        if self.instatus:
            lines = state.statuswin
        else:
            lines = state.storywin
        res = self.subeval(lines)
        if (not self.inverse):
            return res
        else:
            if res:
                return
            return 'inverse test should fail'
    def subeval(self, lines):
        return 'not implemented'

class RegExpCheck(Check):
    """A Check which looks for a regular expression match in the output.
    """
    def __init__(self, ln, inverse=False, instatus=False):
        self.inverse = inverse
        self.instatus = instatus
        self.ln = ln
    def __repr__(self):
        val = self.ln
        if len(val) > 32:
            val = val[:32] + '...'
        invflag = '!' if self.inverse else ''
        return '<RegExpCheck %s"%s">' % (invflag, val,)
    def subeval(self, lines):
        for ln in lines:
            if re.search(self.ln, ln):
                return
        return 'not found'
        
class LiteralCheck(Check):
    """A Check which looks for a literal string match in the output.
    """
    def __init__(self, ln, inverse=False, instatus=False):
        self.inverse = inverse
        self.instatus = instatus
        self.ln = ln
    def __repr__(self):
        val = self.ln
        if len(val) > 32:
            val = val[:32] + '...'
        invflag = '!' if self.inverse else ''
        return '<LiteralCheck %s"%s">' % (invflag, val,)
    def subeval(self, lines):
        for ln in lines:
            if self.ln in ln:
                return
        return 'not found'

class GameState:
    def __init__(self, infile, outfile):
        self.infile = infile
        self.outfile = outfile
        self.statuswin = []
        self.storywin = []

    def initialize(self):
        pass

    def perform_input(self, cmd):
        raise Exception('perform_input not implemented')
        
    def accept_output(self):
        raise Exception('accept_output not implemented')

class GameStateCheap(GameState):

    def perform_input(self, cmd):
        self.infile.write(cmd+'\n')
        self.infile.flush()

    def accept_output(self):
        self.storywin = []
        output = []
        while (select.select([self.outfile],[],[])[0] != []):
            ch = self.outfile.read(1)
            if ch == '':
                break
            output.append(ch)
            if (output[-2:] == ['\n', '>']):
                break
        dat = ''.join(output)
        res = dat.split('\n')
        if (opts.verbose):
            for ln in res:
                if (ln == '>'):
                    continue
                print ln
        self.storywin = res
    
class GameStateRemGlk(GameState):

    @staticmethod
    def extract_text(line):
        # Extract the text from a line object, ignoring styles.
        con = line.get('content')
        if not con:
            return ''
        dat = [ val.get('text') for val in con ]
        return ''.join(dat)
    
    def initialize(self):
        import json
        update = { 'type':'init', 'gen':0,
                   'metrics': { 'width':80, 'height':40 },
                   }
        cmd = json.dumps(update)
        self.infile.write(cmd+'\n')
        self.infile.flush()
        self.generation = 0
        self.windows = {}
        self.lineinputwin = None
        self.charinputwin = None
        
    def perform_input(self, cmd):
        import json
        if not self.lineinputwin:
            raise Exception('Game is not expecting line input')
        update = { 'type':'line', 'gen':self.generation,
                   'window':self.lineinputwin, 'value':cmd
                   }
        cmd = json.dumps(update)
        self.infile.write(cmd+'\n')
        self.infile.flush()
        
    def accept_output(self):
        import json
        output = []
        update = None
        while (select.select([self.outfile],[],[])[0] != []):
            ch = self.outfile.read(1)
            if ch == '':
                dat = ''.join(output)
                update = json.loads(dat)
                break
            output.append(ch)
            if (output[-1] == '}'):
                dat = ''.join(output)
                try:
                    update = json.loads(dat)
                    break
                except:
                    pass

        self.generation = update.get('gen')

        windows = update.get('windows')
        if windows is not None:
            self.windows = {}
            for win in windows:
                id = win.get('id')
                self.windows[id] = win
            grids = [ win for win in self.windows.values() if win.get('type') == 'grid' ]
            if len(grids) > 1:
                raise Exception('Cannot handle more than one grid window')
            if not grids:
                self.statuswin = []
            else:
                win = grids[0]
                height = win.get('gridheight', 0)
                if height < len(self.statuswin):
                    self.statuswin = self.statuswin[0:height]
                while height > len(self.statuswin):
                    self.statuswin.append('')

        contents = update.get('content')
        if contents is not None:
            for content in contents:
                id = content.get('id')
                win = self.windows.get(id)
                if not win:
                    raise Exception('No such window')
                if win.get('type') == 'buffer':
                    self.storywin = []
                    text = content.get('text')
                    if text:
                        for line in text:
                            dat = self.extract_text(line)
                            if line.get('append') and len(self.storywin):
                                self.storywin[-1] += dat
                            else:
                                self.storywin.append(dat)
                    print '### storywin:', self.storywin
                elif win.get('type') == 'grid':
                    lines = content.get('lines')
                    for line in lines:
                        linenum = line.get('line')
                        dat = self.extract_text(line)
                        if linenum >= 0 and linenum < len(self.statuswin):
                            self.statuswin[linenum] = dat
                    print '### statuswin:', self.statuswin

        inputs = update.get('input')
        if inputs is not None:
            self.lineinputwin = None
            self.charinputwin = None
            for input in inputs:
                if input.get('type') == 'line':
                    if self.lineinputwin:
                        raise Exception('Multiple windows accepting line input')
                    self.lineinputwin = input.get('id')
                if input.get('type') == 'char':
                    if self.charinputwin:
                        raise Exception('Multiple windows accepting char input')
                    self.charinputwin = input.get('id')


def parse_tests(filename):
    """Parse the test file. This fills out the testls array, and the
    other globals which will be used during testing.
    """
    global gamefile, terppath, terpargs, remformat
    
    fl = open(filename)
    curtest = None
    curcmd = None

    while True:
        ln = fl.readline()
        if (not ln):
            break
        ln = ln.strip()
        if (not ln or ln.startswith('#')):
            continue

        if (ln.startswith('**')):
            ln = ln[2:].strip()
            pos = ln.find(':')
            if (pos < 0):
                continue
            key = ln[:pos].strip()
            val = ln[pos+1:].strip()
            if not curtest:
                if (key == 'pre' or key == 'precommand'):
                    precommands.append(Command(val))
                elif (key == 'game'):
                    gamefile = val
                elif (key == 'interpreter'):
                    subls = val.split()
                    terppath = subls[0]
                    terpargs = subls[1:]
                elif (key == 'remformat'):
                    remformat = (val.lower() > 'og')
                else:
                    raise Exception('Unknown option: ** ' + key)
            else:
                if (key == 'game'):
                    curtest.gamefile = val
                elif (key == 'interpreter'):
                    subls = val.split()
                    curtest.terp = (subls[0], subls[1:])
                else:
                    raise Exception('Unknown option: ** ' + key + ' in * ' + curtest.name)
            continue
        
        if (ln.startswith('*')):
            ln = ln[1:].strip()
            if (ln in testmap):
                raise Exception('Test name used twice: ' + ln)
            curtest = RegTest(ln)
            testls.append(curtest)
            testmap[curtest.name] = curtest
            curcmd = Command('(init)')
            curtest.precmd = curcmd
            continue

        if (ln.startswith('>')):
            ln = ln[1:].strip()
            curcmd = Command(ln)
            curtest.addcmd(curcmd)
            continue

        curcmd.addcheck(ln)

    fl.close()


def run(test):
    global totalerrors

    testgamefile = gamefile
    if (test.gamefile):
        testgamefile = test.gamefile
    testterppath, testterpargs = (terppath, terpargs)
    if (test.terp):
        testterppath, testterpargs = test.terp
    
    print '*', test.name
    args = [ testterppath ] + testterpargs + [ testgamefile ]
    proc = subprocess.Popen(args,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    if (not remformat):
        gamestate = GameStateCheap(proc.stdin, proc.stdout)
    else:
        gamestate = GameStateRemGlk(proc.stdin, proc.stdout)

    try:
        gamestate.initialize()
        gamestate.accept_output()
        if (test.precmd):
            for check in test.precmd.checks:
                res = check.eval(gamestate)
                if (res):
                    totalerrors += 1
                    val = '*** ' if opts.verbose else ''
                    print '%s%s: %s' % (val, check, res)
    
        for cmd in (precommands + test.cmds):
            if (opts.verbose):
                print '> *%s*' % (cmd.cmd,)
            gamestate.perform_input(cmd.cmd)
            gamestate.accept_output()
            for check in cmd.checks:
                res = check.eval(gamestate)
                if (res):
                    totalerrors += 1
                    val = '*** ' if opts.verbose else ''
                    print '%s%s: %s' % (val, check, res)

    except Exception, ex:
        totalerrors += 1
        val = '*** ' if opts.verbose else ''
        print '%s%s: %s' % (val, ex.__class__.__name__, ex)

    gamestate = None
    proc.stdin.close()
    proc.stdout.close()
    proc.kill()
    proc.poll()
    
    
parse_tests(args[0])

if (len(args) <= 1):
    testnames = ['*']
else:
    testnames = args[1:]

if (opts.gamefile):
    gamefile = opts.gamefile
if (not gamefile):
    print 'No game file specified'
    sys.exit(-1)

if (opts.terppath):
    terppath = opts.terppath
if (not terppath):
    print 'No interpreter path specified'
    sys.exit(-1)
if (opts.remformat):
    remformat = True

if (opts.precommands):
    for cmd in opts.precommands:
        precommands.append(Command(cmd))
    
testcount = 0
for test in testls:
    for pat in testnames:
        use = False
        if (fnmatch.fnmatch(test.name, pat)):
            use = True
            break
    if (use):
        testcount += 1
        if (opts.listonly):
            print test.name
        else:
            run(test)

if (not testcount):
    print 'No tests performed!'
if (totalerrors):
    print
    print 'FAILED: %d errors' % (totalerrors,)
