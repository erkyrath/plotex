#!/usr/bin/env python3

# IF-o-Matic: run IF games, record HTML screenshots.
#   Version 0.7
#   Andrew Plotkin <erkyrath@eblong.com>
#   This script is in the public domain.

# To use:
#
#   python3 ifomatic.py GAME
#
# This launches the game and writes the initial display state to
# ifomat-data/games/IFID/screen.html (where IFID is the game's IFID).
#
# You must have the babel command-line tool in your path. You must also
# have an appropriate interpreter compiled with the RemGlk library in
# your path. Currently the script assumes these are called "glulxer" and
# "fizmo-rem", which are idiosyncratic names I use -- sorry.
#
# The --image option will convert each screen.html file to a screen.png
# file. This requires the phantomjs tool (http://phantomjs.org/) in your
# path.
#
# In its current state, this tool renders text correctly but ignores
# graphics.
#
# (This software is not connected to PlotEx; I'm just distributing them
# from the same folder.)

### standardize on open-source fonts
### handle graphics using unblorbed data

# We use the print() function for Python 2/3 compatibility
from __future__ import print_function

# We use the Py2 unichr() function. In Py3 there is no such function,
# but we define a back-polyfill. (I'm lazy.)
try:
    unichr(32)
except NameError:
    unichr = chr

# In Py2, we'll need a bit of extra decoding.
py2_readline = False
try:
    unicode
    py2_readline = True
except:
    pass

import sys
import os, os.path
import optparse
import subprocess
import select
import re
import datetime
import json
import xml.dom.minidom
import zipfile
import time

popt = optparse.OptionParser(usage='ifomatic.py [options] files or ifids ...')

popt.add_option('--dir',
                action='store', dest='dir',
                default='ifomat-data',
                help='data directory (default: ifomat-data)')
popt.add_option('--html',
                action='store', dest='htmlfile',
                default='ifomat-data/template.html',
                help='HTML template to use')
popt.add_option('--width',
                action='store', type=int, dest='winwidth',
                default=800,
                help='window width in pixels (default: 800)')
popt.add_option('--height',
                action='store', type=int, dest='winheight',
                default=600,
                help='window height in pixels (default: 600)')
popt.add_option('--zterp',
                action='store', dest='zterp',
                default='fizmo-rem',
                help='RemGlk Z-code interpreter')
popt.add_option('--gterp',
                action='store', dest='gterp',
                default='glulxer',
                help='RemGlk Glulx interpreter')
popt.add_option('--babel',
                action='store', dest='babel',
                default='babel',
                help='Babel tool')
popt.add_option('--blorbtool',
                action='store', dest='blorbtool',
                default='blorbtool.py',
                help='blorbtool.py script')
popt.add_option('--timeout',
                dest='timeout_secs', type=float, default=1.0,
                help='timeout interval (default: 1.0 sec)')
popt.add_option('--image',
                action='store_true', dest='image',
                help='write out screen.png file in addition to screen.html')
popt.add_option('--staged',
                action='store_true', dest='staged',
                help='write out a screen-N.html file for each command input')
popt.add_option('-v', '--verbose',
                action='count', dest='verbose', default=0,
                help='display the transcripts as they run')

(opts, args) = popt.parse_args()

class Command:
    """Command is one cycle of a RegTest -- a game input, followed by
    tests to run on the game's output.
    """
    glk_key_names = {
        'left':0xfffffffe, 'right':0xfffffffd, 'up':0xfffffffc,
        'down':0xfffffffb, 'return':0xfffffffa, 'delete':0xfffffff9,
        'escape':0xfffffff8, 'tab':0xfffffff7, 'pageup':0xfffffff6,
        'pagedown':0xfffffff5, 'home':0xfffffff4, 'end':0xfffffff3,
        'func1':0xffffffef, 'func2':0xffffffee, 'func3':0xffffffed,
        'func4':0xffffffec, 'func5':0xffffffeb, 'func6':0xffffffea,
        'func7':0xffffffe9, 'func8':0xffffffe8, 'func9':0xffffffe7,
        'func10':0xffffffe6, 'func11':0xffffffe5, 'func12':0xffffffe4,
    }
    
    def __init__(self, cmd, type='line'):
        self.type = type
        if self.type == 'line':
            self.cmd = cmd
        elif self.type == 'char':
            self.cmd = None
            if len(cmd) == 0:
                self.cmd = '\n'
            elif len(cmd) == 1:
                self.cmd = cmd
            elif cmd.lower() in Command.glk_key_names:
                self.cmd = cmd.lower()
            elif cmd.lower() == 'space':
                self.cmd = ' '
            elif cmd.lower().startswith('0x'):
                self.cmd = unichr(int(cmd[2:], 16))
            else:
                try:
                    self.cmd = unichr(int(cmd))
                except:
                    pass
            if self.cmd is None:
                raise Exception('Unable to interpret char "%s"' % (cmd,))
        elif self.type == 'timer':
            self.cmd = None
        elif self.type == 'hyperlink':
            try:
                cmd = int(cmd)
            except:
                pass
            self.cmd = cmd
        elif self.type == 'refresh':
            self.cmd = None
        elif self.type == 'arrange':
            self.cmd = None
            self.width = None
            self.height = None
            try:
                ls = cmd.split()
                self.width = int(ls[0])
                self.height = int(ls[1])
            except:
                pass
        elif self.type == 'include':
            self.cmd = cmd
        elif self.type == 'fileref_prompt':
            self.cmd = cmd
        elif self.type == 'debug':
            self.cmd = cmd
        else:
            raise Exception('Unknown command type: %s' % (type,))
        self.checks = []
    def __repr__(self):
        return '<Command "%s">' % (self.cmd,)

class GlkWindow:
    def __init__(self, id, type, rock):
        self.id = id
        self.type = type
        self.rock = rock

        self.buflines = None
        self.gridheight = None
        self.gridwidth = None
        self.gridlines = None
        if self.type == 'grid':
            self.gridheight = 0
            self.gridwidth = 0
            self.gridlines = []
        if self.type == 'buffer':
            self.buflines = []
        self.input = None
        self.terminators = {}
        self.reqhyperlink = False
        self.reqmouse = False

    def __repr__(self):
        return '<GlkWindow %d (%s, rock=%d)>' % (self.id, self.type, self.rock)

class GlkWindowInput:
    def __init__(self, arg):
        self.id = arg.get('id')
        self.type = arg.get('type')
        self.gen = arg.get('gen')
        if self.type == 'line':
            self.maxlen = arg.get('maxlen', 1)
            ### initial, terminators
        if self.type == 'grid':
            pass ### xpos, ypos
        
class GlkBufferLine:
    def __init__(self):
        self.ls = []
        self.flowbreak = False

    def __repr__(self):
        return repr(self.ls)

    def append(self, val):
        self.ls.append(val)

class GlkSpecialSpan:
    def __init__(self, arg):
        self.type = arg['special']
        if self.type == 'image':
            self.image = int(arg['image'])
            self.alignment = arg.get('alignment')
            self.alttext = arg.get('alttext')
            val = arg.get('width')
            if val is not None:
                self.width = int(val)
            val = arg.get('height')
            if val is not None:
                self.height = int(val)

    def __repr__(self):
        return '<GlkSpecialSpan %s>' % (self.type,)

class ResourceMap:
    def __init__(self, dir):
        self.dir = dir
        self.map = {}
        
        if not dir:
            return
        mappath = os.path.join(dir, 'resourcemap.json')
        if not os.path.exists(mappath):
            return

        ### Unfortunately at this point we have to decode JS data
        ### (not JSON-compatible). I haven't written that yet.

    def get(self, num):
        return map.get(num)
    
class GameState:
    """The GameState class wraps the connection to the interpreter subprocess
    (the pipe in and out streams). It's responsible for sending commands
    to the interpreter, and receiving the game output back.

    Currently this class is set up to manage exactly one each of story,
    status, and graphics windows. (A missing window is treated as blank.)
    This is not very general -- we should understand the notion of multiple
    windows -- but it's adequate for now.

    This is a virtual base class. Subclasses should customize the
    initialize, perform_input, and accept_output methods.
    """
    def __init__(self, infile, outfile, tracefile=None):
        self.infile = infile
        self.outfile = outfile
        self.tracefile = tracefile

    def initialize(self):
        pass

    def perform_input(self, cmd):
        raise Exception('perform_input not implemented')
        
    def accept_output(self):
        raise Exception('accept_output not implemented')

class GameStateRemGlk(GameState):
    """Wrapper for a RemGlk-based interpreter. This can in theory handle
    any I/O supported by Glk. But the current implementation is limited
    to line and char input, and no more than one status (grid) and one
    graphics window. Multiple story (buffer) windows are accepted, but
    their output for a given turn is agglomerated.
    """

    @staticmethod
    def extract_text(line):
        # Extract the text from a line object, ignoring styles.
        con = line.get('content')
        if not con:
            return ''
        dat = [ val.get('text', '') for val in con ]
        return ''.join(dat)
    
    @staticmethod
    def extract_raw(line):
        # Extract the content array from a line object.
        con = line.get('content')
        if not con:
            return []
        return con

    def initialize(self, blorbdir):
        self.resourcemap = ResourceMap(blorbdir)
        
        self.winwidth = opts.winwidth
        self.winheight = opts.winheight
        update = { 'type':'init', 'gen':0,
                   'metrics': self.create_metrics(),
                   'support': [ 'timer', 'hyperlinks', 'graphics', 'graphicswin' ],
                   }
        cmd = json.dumps(update)
        self.infile.write((cmd+'\n').encode())
        self.infile.flush()
        self.generation = 0
        self.windowdic = {}
        
    def create_metrics(self):
        res = {
            'width':self.winwidth, 'height':self.winheight,
            'gridcharwidth':8.5, 'gridcharheight':16,
            'buffercharwidth':7, 'buffercharheight':16,
            'gridmarginx':19, 'gridmarginy':12,
            'buffermarginx':35, 'buffermarginy':12,
        }
        return res
    
    def perform_input(self, cmd):
        if cmd.type == 'line':
            ls = [ winid for (winid, win) in self.windowdic.items()
                   if win.input and win.input.type == 'line' ]
            if not ls:
                raise Exception('No window is awaiting line input')
            update = { 'type':'line', 'gen':self.generation,
                       'window':min(ls), 'value':cmd.cmd
                       }
        elif cmd.type == 'char':
            ls = [ winid for (winid, win) in self.windowdic.items()
                   if win.input and win.input.type == 'char' ]
            if not ls:
                raise Exception('No window is awaiting char input')
            val = cmd.cmd
            if val == '\n':
                val = 'return'
            update = { 'type':'char', 'gen':self.generation,
                       'window':min(ls), 'value':val
                       }
        elif cmd.type == 'hyperlink':
            update = { 'type':'hyperlink', 'gen':self.generation,
                       'window':'###', 'value':cmd.cmd
                       }
        elif cmd.type == 'timer':
            update = { 'type':'timer', 'gen':self.generation }
        elif cmd.type == 'arrange':
            self.winwidth = cmd.width
            self.winheight = cmd.height
            update = { 'type':'arrange', 'gen':self.generation,
                       'metrics': self.create_metrics()
                       }
        elif cmd.type == 'refresh':
            update = { 'type':'refresh', 'gen':0 }
        elif cmd.type == 'fileref_prompt':
            if self.specialinput != 'fileref_prompt': ###?
                raise Exception('Game is not expecting a fileref_prompt')
            update = { 'type':'specialresponse', 'gen':self.generation,
                       'response':'fileref_prompt', 'value':cmd.cmd
                       }
        elif cmd.type == 'debug':
            update = { 'type':'debuginput', 'gen':self.generation,
                       'value':cmd.cmd
                       }
        else:
            raise Exception('Command type not recognized: %s' % (cmd.type))
        if opts.verbose >= 2:
            ObjPrint.pprint(update)
            print()
        if self.tracefile:
            json.dump(update, self.tracefile, indent=2, sort_keys=True)
            self.tracefile.write('\n\n')
        cmd = json.dumps(update)
        self.infile.write((cmd+'\n').encode())
        self.infile.flush()
        
    def accept_output(self):
        output = bytearray()
        update = None

        timeout_time = time.time() + opts.timeout_secs

        # Read until a complete JSON object comes through the pipe (or
        # we time out).
        # We sneakily rely on the fact that RemGlk always uses dicts
        # as the JSON object, so it always ends with "}".
        while (select.select([self.outfile],[],[],opts.timeout_secs)[0] != []):
            ch = self.outfile.read(1)
            if ch == b'':
                # End of stream. Hopefully we have a valid object.
                dat = output.decode('utf-8')
                update = json.loads(dat)
                break
            output += ch
            if (output[-1] == ord('}')):
                # Test and see if we have a valid object.
                dat = output.decode('utf-8')
                try:
                    update = json.loads(dat)
                    break
                except:
                    pass
                
        if time.time() >= timeout_time:
            raise Exception('Timed out awaiting output')

        # Parse the update object. This is complicated. For the format,
        # see http://eblong.com/zarf/glk/glkote/docs.html

        if opts.verbose >= 2:
            ObjPrint.pprint(update)
            print()
        if self.tracefile:
            json.dump(update, self.tracefile, indent=2, sort_keys=True)
            self.tracefile.write('\n\n')

        self.generation = update.get('gen')

        inputs = update.get('input')
        self.accept_inputcancel(inputs)

        windows = update.get('windows')
        if windows is not None:
            # Handle all the window changes. The argument lists all windows
            # that should be open. Any unlisted windows, therefore, get
            # closed.
            # (If the update has no windows entry, we make no window changes.)
            for win in self.windowdic.values():
                win.inplace = False
            for win in windows:
                self.accept_one_window(win)
            closewins = [ win for win in self.windowdic.values() if not win.inplace ]
            for win in closewins:
                del self.windowdic[win.id]

        contents = update.get('content')
        if contents is not None:
            for content in contents:
                self.accept_one_content(content)

        self.accept_inputset(inputs)

        ###specialinputs = update.get('specialinput')
        ###timer = update.get('timer')

    def accept_inputcancel(self, arg):
        if arg is None:
            return
        
        hasinput = {}
        for argi in arg:
            if argi.get('type'):
                hasinput[argi['id']] = argi
                
        for (winid, win) in self.windowdic.items():
            if win.input:
                argi = hasinput.get('winid')
                if (argi is None) or (argi['gen'] > win.input.gen):
                    # cancel this input.
                    win.input = None

    def accept_inputset(self, arg):
        if arg is None:
            return
        
        hasinput = {}
        hashyperlink = {}
        hasmouse = {}
        for argi in arg:
            id = argi['id']
            if argi.get('type'):
                hasinput[id] = argi
            if argi.get('hyperlink'):
                hashyperlink[id] = True
            if argi.get('mouse'):
                hasmouse[id] = True
        
        for (winid, win) in self.windowdic.items():
            win.reqhyperlink = hashyperlink.get(winid)
            win.reqmouse = hasmouse.get(winid)

            argi = hasinput.get(winid)
            if argi is None:
                continue
            win.input = GlkWindowInput(argi)

            ### initial, terminators
            
    def accept_one_window(self, arg):
        argid = arg['id']
        win = self.windowdic.get(argid)
        if win is None:
            # The window must be created.
            win = GlkWindow(argid, arg['type'], arg['rock'])
            self.windowdic[argid] = win

        win.inplace = True

        win.posleft = int(arg['left'])
        win.postop = int(arg['top'])
        win.poswidth = int(arg['width'])
        win.posheight = int(arg['height'])
        
        if win.type == 'grid':
            # Make sure we have the correct number of lines.
            argheight = arg['gridheight']
            argwidth = arg['gridwidth']
            if argheight > win.gridheight:
                for ix in range(win.gridheight, argheight):
                    win.gridlines.append([])
            if argheight < win.gridheight:
                del win.gridlines[ argheight : ]
            win.gridheight = argheight
            win.gridwidth = argwidth
                    
        if win.type == 'graphics':
            pass  ### set up array

    def accept_one_content(self, arg):
        id = arg.get('id')
        win = self.windowdic.get(id)
        if not win:
            raise Exception('No such window')

        if win.input and win.input.type == 'line':
            raise Exception('Window is awaiting line input.')

        if win.type == 'grid':
            # Modify the given lines of the grid window
            for (ix, linearg) in enumerate(arg['lines']):
                linenum = linearg['line']
                linels = win.gridlines[linenum]
                linels.clear()
                content = linearg.get('content')
                if content:
                    sx = 0
                    while sx < len(content):
                        rdesc = content[sx]
                        sx += 1
                        if type(rdesc) is dict:
                            if rdesc.get('special') is not None:
                                continue
                            rstyle = rdesc['style']
                            rtext = rdesc['text']
                            rlink = rdesc.get('hyperlink')
                        else:
                            rstyle = rdesc
                            rtext = content[sx]
                            sx += 1
                            rlink = None
                        el = (rstyle, rtext, rlink)
                        linels.append(el)
            #print('###', win, win.gridlines)

        if win.type == 'buffer':
            # Append the given lines onto the end of the buffer window
            text = arg.get('text', [])

            if arg.get('clear'):
                win.buflines.clear()

            # Each line we receive has a flag indicating whether it *starts*
            # a new paragraph. (If the flag is false, the line gets appended
            # to the previous paragraph.)
                
            for textarg in text:
                content = textarg.get('content')
                linels = None
                if textarg.get('append'):
                    if content is None or not len(content):
                        continue
                    if len(win.buflines):
                        linels = win.buflines[-1]
                if linels is None:
                    linels = GlkBufferLine()
                    win.buflines.append(linels)
                if textarg.get('flowbreak'):
                    divel.flowbreak = True
                    
                if content is None or not len(content):
                    continue
                
                sx = 0
                while sx < len(content):
                    rdesc = content[sx]
                    sx += 1
                    if type(rdesc) is dict:
                        if rdesc.get('special') is not None:
                            el = GlkSpecialSpan(rdesc)
                            linels.append(el)
                            continue
                        rstyle = rdesc['style']
                        rtext = rdesc['text']
                        rlink = rdesc.get('hyperlink')
                    else:
                        rstyle = rdesc
                        rtext = content[sx]
                        sx += 1
                        rlink = None
                    el = (rstyle, rtext, rlink)
                    linels.append(el)
                        
            ### trim the scrollback
            #print('###', win, win.buflines)
                    
        if win.type == 'graphics':
            draw = arg.get('draw', [])
            pass ###

class ObjPrint:
    NoneType = type(None)
    try:
        UnicodeType = unicode
    except:
        UnicodeType = str
    
    @staticmethod
    def pprint(obj):
        printer = ObjPrint()
        printer.printval(obj, depth=0)
        print(''.join(printer.arr))
    
    def __init__(self):
        self.arr = []

    @staticmethod
    def valislong(val):
        typ = type(val)
        if typ is ObjPrint.NoneType:
            return False
        elif typ is bool or typ is int or typ is float:
            return False
        elif typ is str or typ is ObjPrint.UnicodeType:
            return (len(val) > 16)
        elif typ is list or typ is dict:
            return (len(val) > 0)
        else:
            return True

    def printval(self, val, depth=0):
        typ = type(val)
        
        if typ is ObjPrint.NoneType:
            self.arr.append('None')
        elif typ is bool or typ is int or typ is float:
            self.arr.append(str(val))
        elif typ is str:
            self.arr.append(repr(val))
        elif typ is ObjPrint.UnicodeType:
            st = repr(val)
            if st.startswith('u'):
                st = st[1:]
            self.arr.append(st)
        elif typ is list:
            if len(val) == 0:
                self.arr.append('[]')
            else:
                anylong = False
                for subval in val:
                    if ObjPrint.valislong(subval):
                        anylong = True
                        break
                self.arr.append('[')
                if anylong:
                    self.arr.append('\n')
                first = True
                for subval in val:
                    if first:
                        if anylong:
                            self.arr.append((depth+1)*'  ')
                    else:
                        if anylong:
                            self.arr.append(',\n')
                            self.arr.append((depth+1)*'  ')
                        else:
                            self.arr.append(', ')
                    self.printval(subval, depth+1)
                    first = False
                if anylong:
                    self.arr.append('\n')
                    self.arr.append(depth*'  ')
                self.arr.append(']')
        elif typ is dict:
            if len(val) == 0:
                self.arr.append('{}')
            else:
                anylong = False
                for subval in val.values():
                    if ObjPrint.valislong(subval):
                        anylong = True
                        break
                self.arr.append('{')
                if anylong:
                    self.arr.append('\n')
                first = True
                keyls = sorted(val.keys())
                for subkey in keyls:
                    subval = val[subkey]
                    if first:
                        if anylong:
                            self.arr.append((depth+1)*'  ')
                    else:
                        if anylong:
                            self.arr.append(',\n')
                            self.arr.append((depth+1)*'  ')
                        else:
                            self.arr.append(', ')
                    self.printval(subkey, depth+1)
                    self.arr.append(':')
                    self.printval(subval, depth+1)
                    first = False
                if anylong:
                    self.arr.append('\n')
                    self.arr.append(depth*'  ')
                self.arr.append('}')
        else:
            raise Exception('unknown type: %r' % (val,))


def append_to_file(path, ln):
    if not os.path.exists(path):
        fl = open(path, 'w')
    else:
        fl = open(path, 'a')
    fl.write(ln + '\n')
    fl.close()
    
def escape_json(val):
    res = ['"']
    for ch in val:
        if ch == '"' or ch == '\\':
            res.append('\\' + ch)
        else:
            och = ord(ch)
            if och < 128:
                res.append(chr(och))
            else:
                res.append('\\u%04x' % (och,))
    res.append('"')
    return ''.join(res)

def escape_html(val, quotes=False):
    """Apply &-escapes to render arbitrary strings in ASCII-clean HTML.
    This is miserably inefficient -- I'm sure there's a built-in Python
    function which does it, but I haven't looked it up.
    """
    res = []
    for ch in val:
        if ch == '&':
            res.append('&amp;')
        elif ch == '>':
            res.append('&gt;')
        elif ch == '<':
            res.append('&lt;')
        elif quotes and ch == '"':
            res.append('&quot;')
        else:
            och = ord(ch)
            if och < 128:
                res.append(chr(och))
            else:
                res.append('&#'+str(och)+';')
    return ''.join(res)

def write_contents(ifid, gamefile, metadata, dirpath):
    fl = open(os.path.join(dirpath, 'contents'), 'w')
    fl.write('IFID: %s\n' % (ifid,))
    fl.write('file: %s\n' % (os.path.abspath(gamefile),))
    fl.write('created: %s\n' % (datetime.datetime.now(),))
    if 'title' in metadata:
        fl.write('title: %s\n' % (metadata['title'],))
    fl.close()

def write_html_window(win, state, fl):
    """Write the contents of one Glk window in screen.html.
    """
    if win.type == 'grid':
        cssclass = 'GridWindow'
    elif win.type == 'buffer':
        cssclass = 'BufferWindow'
    else:
        cssclass = 'UnknownWindow'

    posright = state.winwidth - (win.posleft + win.poswidth)
    posbottom = state.winheight - (win.postop + win.posheight)
    
    fl.write('<div id="window%d" class="WindowFrame %s WindowRock_%d" style="left: %dpx; top: %dpx; right: %dpx; bottom: %dpx">\n' % (win.id, cssclass, win.rock, win.posleft, win.postop, posright, posbottom,))

    if win.type == 'grid':
        for line in win.gridlines:
            fl.write('<div class="GridLine">')
            for span in line:
                (rstyle, rtext, rlink) = span
                fl.write('<span class="Style_%s">%s</span>' % (rstyle, escape_html(rtext)))
            fl.write('</div>\n')
            
    if win.type == 'buffer':
        for line in win.buflines:
            fl.write('<div class="BufferLine">')
            for span in line.ls:
                if isinstance(span, GlkSpecialSpan):
                    if span.type == 'image':
                        image = state.resourcemap.get(span.image)
                        if image:
                            srcval = os.path.join(state.resourcemap.dir, image.filename)
                            srcval = escape_html(srcval, quotes=True)
                        
                            altval = span.alttext
                            if not altval:
                                altval = image.alttext
                            if not altval:
                                altval = 'Image %d' % (span.image,)
                            altval = escape_html(altval, quotes=True)
                        
                            fl.write('<img src="%s" alt="%s" width="%d" height="%d">' % (srcval, altval, span.width, span.height,))
                    continue
                
                (rstyle, rtext, rlink) = span
                fl.write('<span class="Style_%s">%s</span>' % (rstyle, escape_html(rtext)))
            if not line.ls:
                fl.write('&nbsp;');
            fl.write('</div>\n')
            
    fl.write('</div>\n')
    
def write_html(ifid, gamefile, metadata, state, dirpath, fileindex=None):
    """Write out the screen.html file in the game directory. We could
    also be writing a screen-N.html intermediate file.

    If the --image option is given, we then convert the HTML file to
    a PNG file.
    """
    if (fileindex is not None) and (not opts.staged):
        # If this is an intermediate file and the option for that isn't
        # set, skip this file.
        return
    
    window_title = metadata.get('title', 'Game Screenshot')
    
    filename = 'screen.html'
    if fileindex is not None:
        filename = 'screen-%d.html' % (fileindex,)
    fl = open(os.path.join(dirpath, filename), 'w')

    for ln in htmllines:
        if ln == '$WINDOWPORT$':
            fl.write('<div id="windowport">\n')
            winls = list(state.windowdic.values())
            winls.sort(key=lambda win: win.id)
            for win in winls:
                write_html_window(win, state, fl)
            fl.write('</div>\n')
        elif '$' in ln:
            ln = ln.replace('$TITLE$', window_title)
            ln = ln.replace('$WINWIDTH$', str(state.winwidth))
            ln = ln.replace('$WINHEIGHT$', str(state.winheight))
            fl.write(ln)
            fl.write('\n')
        else:
            fl.write(ln)
            fl.write('\n')

    fl.close()

    if opts.image:
        genimage = os.path.join(opts.dir, 'genimage.js')
        ifilename = re.sub('[.]html$', '.png', filename)
        size = '%dx%d' % (state.winwidth, state.winheight,)
        subprocess.run(['phantomjs', genimage, os.path.join(dirpath, filename), os.path.join(dirpath, ifilename), size], check=True)

def clear_html(dirpath):
    """Remove the screen.html file from the game directory. Actually
    we remove all the screen-N.html files that we find. Also the
    screen*.png files.
    """
    filename = 'screen.html'
    try:
        os.remove(os.path.join(dirpath, filename))
    except:
        pass
    
    fileindex = 0
    while True:
        filename = 'screen-%d.html' % (fileindex,)
        try:
            os.remove(os.path.join(dirpath, filename))
        except:
            break
        fileindex += 1
    
    filename = 'screen.png'
    try:
        os.remove(os.path.join(dirpath, filename))
    except:
        pass
    
    fileindex = 0
    while True:
        filename = 'screen-%d.png' % (fileindex,)
        try:
            os.remove(os.path.join(dirpath, filename))
        except:
            break
        fileindex += 1

zip_map_path = None
zip_map = {}   # maps pathnames of zip files to directory names

def read_zip_mapping(dir=dir):
    global zip_map_path
    zip_map_path = os.path.join(dir, 'zipmap')
    if not os.path.exists(zip_map_path):
        return
    fl = open(zip_map_path)
    for ln in fl.readlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith('#'):
            continue
        path, dummy, dir = ln.partition('\t')
        if path and dummy and dir:
            zip_map[path] = dir

def add_zip_mapping(zippath, dirpath):
    zip_map[zippath] = dirpath
    val = zippath + '\t' + dirpath
    append_to_file(zip_map_path, val)

def find_in_zip(file):
    """Unpack the zip file (if necessary) and locate a game file in it.
    
    We keep track of a list of previously-unpacked zip files.
    """
    if file in zip_map:
        zipdir = zip_map[file]
    else:
        zipdir = choose_unzip_dir(file)
        add_zip_mapping(file, zipdir)

    # If the directory does not exist, create it and unzip.
    # (We assume that if the directory exists, it contains a complete
    # extraction.)
    unzipdir = os.path.join(opts.dir, 'unzip')
    if not os.path.exists(unzipdir):
        os.mkdir(unzipdir)
        
    if not os.path.exists(zipdir):
        if opts.verbose >= 1:
            print('unzipping', file, 'to', zipdir)
        os.mkdir(zipdir)
        zipfl = zipfile.ZipFile(file)
        zipfl.extractall(zipdir)
        zipfl.close()

    # Search the directory for anything that looks like a game file.
    # We do this with a crude suffix check -- babel would be smarter,
    # maybe.
    res = None
    
    for (dirpath, dirnames, filenames) in os.walk(zipdir):
        for path in filenames:
            (_, suffix) = os.path.splitext(path)
            if suffix.lower() in all_game_suffixes:
                if res is None or len(dirpath) < len(res[0]):
                    res = (dirpath, path)

    if res:
        return os.path.join(res[0], res[1])
    return None


def choose_unzip_dir(file):
    unzipdir = os.path.join(opts.dir, 'unzip')
    if not os.path.exists(unzipdir):
        os.mkdir(unzipdir)
    
    val = os.path.basename(file)
    val = re.sub('[^a-zA-Z0-9]+', '-', val)
    index = 0
    while True:
        dir = os.path.join(unzipdir, val)
        if index:
            dir = dir + '-%d' % (index,)
        if not os.path.exists(dir):
            break
        index += 1
        
    return dir

all_game_suffixes = set([
    '.ulx',
    '.z3', '.z4', '.z5', '.z8',
    '.blb', '.blorb', '.zblorb', '.gblorb',
])

re_ifid = re.compile('^[A-Z0-9-]+$')
re_ifidline = re.compile('^IFID: ([A-Z0-9-]+)$')
re_formatline = re.compile('^Format: ([A-Za-z0-9 _-]+)$')

def get_ifid(file):
    """Figure out the IFID of this file. (By asking the Babel tool.)
    """
    res = subprocess.check_output([opts.babel, '-ifid', file])
    res = res.decode('utf-8')
    res = res.strip()
    match = re_ifidline.match(res)
    if match:
        return match.group(1)
    raise Exception('Babel tool did not return an IFID')

def get_format(file):
    """Figure out what kind of IF file this is. (By asking the Babel
    tool.)
    """
    res = subprocess.check_output([opts.babel, '-format', file])
    res = res.decode('utf-8')
    res = res.strip()
    match = re_formatline.match(res)
    if match:
        val = match.group(1)
        blorbed = False
        if val.startswith('blorbed '):
            val = val[8:]
            blorbed = True
        return (val, blorbed)
    raise Exception('Babel tool did not return a format')

def get_metadata(file):
    """Extract the metadata from a game (typically a blorb file)
    by asking the Babel tool.
    
    This does some very simple processing on the XML metadata chunk
    to pull out all the subtags of the <bibliographic> tag and return
    them as a dict.
    """
    res = subprocess.check_output([opts.babel, '-meta', file])
    map = {}
    if res.startswith(b'<?'):
        dat = xml.dom.minidom.parseString(res)
        for nod in dat.firstChild.childNodes:
            if nod.nodeType == nod.ELEMENT_NODE and nod.nodeName == 'story':
                for nod2 in nod.childNodes:
                    if nod2.nodeType == nod2.ELEMENT_NODE and nod2.nodeName =='bibliographic':
                        for nod3 in nod2.childNodes:
                            if nod3.nodeType == nod3.ELEMENT_NODE:
                                valls = []
                                for nod4 in nod3.childNodes:
                                    if nod4.nodeType == nod4.TEXT_NODE:
                                        valls.append(nod4.nodeValue)
                                map[nod3.nodeName] = ''.join(valls).strip()
    return map

def extract_blorb_data(file, dir):
    """Extract the contents of a blorb file into a blorbdata subdir.
    (By asking the blorbtool.py tool.)
    This will be needed to link images into the static HTML output.
    """
    if not os.path.exists(dir):
        os.mkdir(dir)
        
    subprocess.run(['python3', opts.blorbtool, file, 'giload', dir], check=True)
    if not os.path.exists(os.path.join(dir, 'resourcemap.json')):
        raise Exception('Could not find resourcemap.json in deblorbed directory')

def run(gamefile):
    """Process one game (presented as a pathname or IFID string).
    """
    if not os.path.exists(gamesdir):
        os.mkdir(gamesdir)

    (_, suffix) = os.path.splitext(os.path.basename(gamefile))
    if suffix == '.zip':
        # This is a zip file. We must unpack it to find the *real* filename.
        res = find_in_zip(gamefile)
        if not res:
            print('%s: unable to find game file' % (gamefile,))
            return
        if opts.verbose >= 1:
            print('found %s in %s' % (res, gamefile,))
        gamefile = res

    if re_ifid.match(gamefile):
        # This is an IFID, not a filename. Pull the filename out of
        # the previously-parsed contents info.
        ifid = gamefile
        dir = os.path.join(gamesdir, ifid)
        if not os.path.exists(dir):
            print('%s: no IFID directory (%s)' % (ifid, dir))
            return
        try:
            gamefile = None
            fl = open(os.path.join(dir, 'contents'))
            for ln in fl.readlines():
                tag, dummy, body = ln.partition(':')
                tag, body = tag.strip(), body.strip()
                if tag == 'file':
                    gamefile = body
            fl.close()
            if not gamefile:
                print('%s: no file listed in contents file in %s' % (ifid, dir))
                return
        except IOError:
            print('%s: cannot read contents file in %s' % (ifid, dir))
            return

    if not os.path.exists(gamefile):
        print('%s: no such file' % (gamefile,))
        return

    # Check the format.
    try:
        (format, blorbed) = get_format(gamefile)
    except Exception as ex:
        print('%s: unable to get format: %s: %s' % (gamefile, ex.__class__.__name__, ex))
        return
    if format not in ['zcode', 'glulx']:
        print('%s: format is not zcode/glulx: %s' % (gamefile, format))
        return

    # Check the IFID.
    try:
        ifid = get_ifid(gamefile)
    except Exception as ex:
        print('%s: unable to get IFID: %s: %s' % (gamefile, ex.__class__.__name__, ex))
        return

    # Pull the metadata if available.
    try:
        metadata = get_metadata(gamefile)
    except Exception as ex:
        print('%s: unable to get metadata: %s: %s' % (gamefile, ex.__class__.__name__, ex))
        return

    # Create the game dir, which will be ifomat-data/IFID.
    dir = os.path.join(gamesdir, ifid)
    if not os.path.exists(dir):
        os.mkdir(dir)

    # If the game file is a blorb, extract the image and sound files
    # so we can link them into generated HTML.
    # This is only done once -- if the blorbdata directory exists,
    # we don't re-extract. (This optimization could be smarter.)
    blorbdir = None
    if blorbed:
        try:
            blorbdir = os.path.join(dir, 'blorbdata')
            if not os.path.exists(blorbdir):
                extract_blorb_data(gamefile, blorbdir)
        except Exception as ex:
            print('%s: unable to deblorb: %s: %s' % (gamefile, ex.__class__.__name__, ex))
            return

    # Pick an interpreter.
    if format == 'zcode':
        terppath = opts.zterp
    else:
        terppath = opts.gterp
    testterpargs = []
    cmdlist = []

    # Check for an options file. If it exists, it contains ad-hoc
    # extra information about running the game. Currently this means
    # input commands to run before doing the screenshot.
    optfile = os.path.join(dir, 'options')
    if os.path.exists(optfile):
        fl = open(optfile)
        for ln in fl.readlines():
            ln = ln.strip()
            if not ln:
                continue
            if ln.startswith('#'):
                continue
            tag, dummy, body = ln.partition(':')
            tag, body = tag.strip(), body.strip()
            if tag == 'input':
                match = re.match('^%([a-z]+)', body)
                if match:
                    intype = match.group(1)
                    body = body[match.end() : ].strip()
                    cmd = Command(body, type=intype)
                else:
                    cmd = Command(body)
                cmdlist.append(cmd)
            else:
                print('%s: warning: unrecognized line in options: %s' % (gamefile, ln))
        fl.close()

    # Begin running the game!
    
    args = [ terppath ] + testterpargs + [ gamefile ]
    proc = None

    try:
        proc = subprocess.Popen(args,
                                bufsize=0,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    except Exception as ex:
        print('%s: unable to launch interpreter: %s: %s' % (gamefile, ex.__class__.__name__, ex))
        return

    tracefile = None
    
    try:
        write_contents(ifid, gamefile, metadata, dirpath=dir)
        clear_html(dirpath=dir)
        
        tracefile = open(os.path.join(dir, 'trace.json'), 'w')
        gamestate = GameStateRemGlk(proc.stdin, proc.stdout, tracefile)
    
        gamestate.initialize(blorbdir)
        gamestate.accept_output()
        outindex = 0
        val = len(cmdlist) - outindex
        write_html(ifid, gamefile, metadata, gamestate, dirpath=dir, fileindex=(outindex if val else None))
        for cmd in cmdlist:
            gamestate.perform_input(cmd)
            gamestate.accept_output()
            outindex += 1
            val = len(cmdlist) - outindex
            write_html(ifid, gamefile, metadata, gamestate, dirpath=dir, fileindex=(outindex if val else None))
        print('%s: (IFID %s): done' % (gamefile, ifid))
    except Exception as ex:
        print('%s: unable to run: %s: %s' % (gamefile, ex.__class__.__name__, ex))

    if tracefile:
        tracefile.close()
    gamestate = None
    proc.stdin.close()
    proc.stdout.close()
    proc.kill()
    proc.poll()
    proc = None
    
    return ifid

if not args:
    print('usage: ifomatic.py [options] files or ifids ...')
    sys.exit(-1)

htmlblock = ''
if opts.htmlfile:
    fl = open(opts.htmlfile)
    htmlblock = fl.read()
    fl.close()
htmllines = htmlblock.split('\n')
htmllines = [ ln.rstrip() for ln in htmllines ]

gamesdir = os.path.join(opts.dir, 'games')

read_zip_mapping(opts.dir)

for arg in args:
    run(arg)
