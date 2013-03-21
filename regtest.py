# RegTest: a really simple IF regression tester.
#   Version 1.2
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
popt.add_option('-v', '--verbose',
                action='store_true', dest='verbose',
                help='display the transcripts as they run')

(opts, args) = popt.parse_args()

if (not args):
    print 'usage: regtest.py TESTFILE [ TESTPATS... ]'
    sys.exit(1)

class RegTest:
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
    def __init__(self, cmd):
        self.cmd = cmd
        self.checks = []
    def __repr__(self):
        return '<Command "%s">' % (self.cmd,)
    def addcheck(self, ln):
        inverse = False
        if (ln.startswith('!')):
            inverse = True
            ln = ln[1:].strip()
        if (ln.startswith('/')):
            check = RegExpCheck(ln[1:].strip(), inverse)
        else:
            check = LiteralCheck(ln, inverse)
        self.checks.append(check)

class Check:
    def eval(self, lines):
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
    def __init__(self, ln, inverse=False):
        self.inverse = inverse
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
    def __init__(self, ln, inverse=False):
        self.inverse = inverse
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
        
def parse_tests(filename):
    global gamefile, terppath, terpargs
    
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

def read_to_prompt(fl):
    output = []
    while (select.select([fl],[],[])[0] != []):
        ch = fl.read(1)
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
    return res
    
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

    ls = read_to_prompt(proc.stdout)
    if (test.precmd):
        for check in test.precmd.checks:
            res = check.eval(ls)
            if (res):
                totalerrors += 1
                val = '*** ' if opts.verbose else ''
                print '%s%s: %s' % (val, check, res)

    for cmd in (precommands + test.cmds):
        if (opts.verbose):
            print '> *%s*' % (cmd.cmd,)
        proc.stdin.write(cmd.cmd+'\n')
        proc.stdin.flush()
        ls = read_to_prompt(proc.stdout)
        for check in cmd.checks:
            res = check.eval(ls)
            if (res):
                totalerrors += 1
                val = '*** ' if opts.verbose else ''
                print '%s%s: %s' % (val, check, res)

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
