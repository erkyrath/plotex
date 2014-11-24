import sys
import os, os.path
import optparse
import subprocess
import select
import re
import datetime

popt = optparse.OptionParser(usage='ifomatic.py [options] files or ifids ...')

popt.add_option('--dir',
                action='store', dest='shotdir',
                default='screenshots',
                help='directory to write screenshots to')
popt.add_option('--css',
                action='store', dest='cssfile',
                default='ifomatic.css',
                help='CSS file to include')
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

(opts, args) = popt.parse_args()

class Command:
    glkkeyset = set(['left', 'right', 'up', 'down',
                     'return', 'delete', 'escape', 'tab',
                     'pageup', 'pagedown', 'home', 'end',
                     'func1', 'func2', 'func3', 'func4', 'func5', 'func6',
                     'func7', 'func8', 'func9', 'func10', 'func11', 'func12'])
    
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
            elif cmd.lower().startswith('0x'):
                self.cmd = unichr(int(cmd[2:], 16))
            elif cmd == 'space':
                self.cmd = ' '
            elif cmd in Command.glkkeyset:
                self.cmd = cmd
            else:
                try:
                    self.cmd = unichr(int(cmd))
                except:
                    pass
            if self.cmd is None:
                raise Exception('Unable to interpret char "%s"' % (cmd,))
        elif self.type == 'include':
            self.cmd = cmd
        elif self.type == 'fileref_prompt':
            self.cmd = cmd
        else:
            raise Exception('Unknown command type: %s' % (type,))
    def __repr__(self):
        return '<Command "%s">' % (self.cmd,)

class GameState:
    """The GameState class wraps the connection to the interpreter subprocess
    (the pipe in and out streams). It's responsible for sending commands
    to the interpreter, and receiving the game output back.

    Currently this class is set up to manage exactly one story window
    and exactly one status window. (A missing window is treated as blank.)
    This is not very general -- we should understand the notion of multiple
    windows -- but it's adequate for now.

    This is a virtual base class. Subclasses should customize the
    initialize, perform_input, and accept_output methods.
    """
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

class GameStateRemGlk(GameState):
    """Wrapper for a RemGlk-based interpreter. This can in theory handle
    any I/O supported by Glk. But the current implementation is limited
    to line and char input, and no more than one status (grid) window.
    Multiple story (buffer) windows are accepted, but their output for
    a given turn is agglomerated.
    """

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
        self.specialinput = None
        
    def perform_input(self, cmd):
        import json
        if cmd.type == 'line':
            if not self.lineinputwin:
                raise Exception('Game is not expecting line input')
            update = { 'type':'line', 'gen':self.generation,
                       'window':self.lineinputwin, 'value':cmd.cmd
                       }
        elif cmd.type == 'char':
            if not self.charinputwin:
                raise Exception('Game is not expecting char input')
            val = cmd.cmd
            if val == '\n':
                val = 'return'
            # We should handle arrow keys, too
            update = { 'type':'char', 'gen':self.generation,
                       'window':self.charinputwin, 'value':val
                       }
        elif cmd.type == 'fileref_prompt':
            if self.specialinput != 'fileref_prompt':
                raise Exception('Game is not expecting a fileref_prompt')
            update = { 'type':'specialresponse', 'gen':self.generation,
                       'response':'fileref_prompt', 'value':cmd.cmd
                       }
        else:
            raise Exception('Rem mode does not recognize command type: %s' % (cmd.type))
        cmd = json.dumps(update)
        self.infile.write(cmd+'\n')
        self.infile.flush()
        
    def accept_output(self):
        import json
        output = []
        update = None

        # Read until a complete JSON object comes through the pipe.
        # We sneakily rely on the fact that RemGlk always uses dicts
        # as the JSON object, so it always ends with "}".
        while (select.select([self.outfile],[],[])[0] != []):
            ch = self.outfile.read(1)
            if ch == '':
                # End of stream. Hopefully we have a valid object.
                dat = ''.join(output)
                update = json.loads(dat)
                break
            output.append(ch)
            if (output[-1] == '}'):
                # Test and see if we have a valid object.
                dat = ''.join(output)
                try:
                    update = json.loads(dat)
                    break
                except:
                    pass

        # Parse the update object. This is complicated. For the format,
        # see http://eblong.com/zarf/glk/glkote/docs.html

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
                    text = content.get('text')
                    if text:
                        for line in text:
                            datls = line.get('content')
                            if not datls:
                                datls = []
                            if line.get('append') and len(self.storywin):
                                self.storywin[-1] += datls
                            else:
                                self.storywin.append(datls)
                elif win.get('type') == 'grid':
                    lines = content.get('lines')
                    for line in lines:
                        linenum = line.get('line')
                        datls = line.get('content')
                        if not datls:
                            datls = []
                        if linenum >= 0 and linenum < len(self.statuswin):
                            self.statuswin[linenum] = datls

        inputs = update.get('input')
        specialinputs = update.get('specialinput')
        if specialinputs is not None:
            self.specialinput = specialinputs.get('type')
            self.lineinputwin = None
            self.charinputwin = None
        elif inputs is not None:
            self.specialinput = None
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
                res.append('\u%04x' % (och,))
    res.append('"')
    return ''.join(res)

def escape_html(val, lastspan=False):
    res = []
    spaces = 0
    for ch in val:
        if ch == ' ':
            spaces += 1
            continue
        if spaces > 0:
            res.append('&nbsp;' * (spaces-1))
            res.append(' ')
            spaces = 0
        if ch == '&':
            res.append('&amp;')
        elif ch == '>':
            res.append('&gt;')
        elif ch == '<':
            res.append('&lt;')
        else:
            och = ord(ch)
            if och < 128:
                res.append(chr(och))
            else:
                res.append('&#'+str(och)+';')
    if spaces > 0:
        if not lastspan:
            res.append('&nbsp;' * (spaces-1))
            res.append(' ')
        else:
            res.append(' ')
            res.append('&nbsp;' * (spaces-1))
    return ''.join(res)

def write_html(ifid, gamefile, statuswin, storywin, dirpath):
    fl = open(os.path.join(dirpath, 'contents'), 'w')
    fl.write('IFID: %s\n' % (ifid,))
    fl.write('file: %s\n' % (os.path.abspath(gamefile),))
    fl.write('created: %s\n' % (datetime.datetime.now(),))
    fl.close()
    
    fl = open(os.path.join(dirpath, 'screen.json'), 'w')
    fl.write('{\n')
    fl.write(' "status": {\n')
    fl.write('  "lines": [\n')
    for ix in range(len(statuswin)):
        line = statuswin[ix]
        line = [ '{"text": %s, "style": %s}' % (escape_json(span.get('text', '')), escape_json(span.get('style', 'normal'))) for span in line ]
        line = '[' + ', '.join(line) + ']'
        comma = '' if (ix+1 == len(statuswin)) else ','
        fl.write('   { "line": %d, "content": %s }%s\n' % (ix, line, comma))
    fl.write('  ] },\n')
    fl.write(' "story": {\n')
    fl.write('  "text": [\n')
    for ix in range(len(storywin)):
        line = storywin[ix]
        line = [ '{"text": %s, "style": %s}' % (escape_json(span.get('text', '')), escape_json(span.get('style', 'normal'))) for span in line ]
        line = '[' + ', '.join(line) + ']'
        comma = '' if (ix+1 == len(storywin)) else ','
        fl.write('   { "content": %s }%s\n' % (line, comma))
    fl.write('  ] }\n')
    fl.write('}\n')
    fl.close()
    
    fl = open(os.path.join(dirpath, 'screen.html'), 'w')

    fl.write('<!doctype HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">\n')
    fl.write('<html>\n')
    fl.write('<head>\n')
    fl.write('<title>Game Dump</title>\n')
    fl.write('<style type="text/css">\n')
    fl.write(styleblock)
    fl.write('</style>\n')
    fl.write('</head>\n')
    fl.write('<body>\n')
    fl.write('<div class="StatusWindow">\n')
    for line in statuswin:
        fl.write('<div class="StatusLine">')
        spans = len(line)
        if spans == 0:
            fl.write('&nbsp;')
        else:
            for ix in range(spans):
                span = line[ix]
                spantext = span.get('text', '')
                spanstyle = span.get('style', 'normal')
                islast = (ix+1 == spans)
                fl.write('<span class="Style_%s">%s</span>' % (spanstyle, escape_html(spantext, islast)))
        fl.write('</div>\n')
    fl.write('</div>\n')
    for line in storywin:
        fl.write('<div class="StoryPara">')
        spans = len(line)
        if spans == 0:
            fl.write('&nbsp;')
        else:
            for ix in range(spans):
                span = line[ix]
                spantext = span.get('text', '')
                spanstyle = span.get('style', 'normal')
                islast = (ix+1 == spans)
                fl.write('<span class="Style_%s">%s</span>' % (spanstyle, escape_html(spantext)))
        fl.write('</div>\n')
    fl.write('</body>\n')
    fl.write('</html>\n')

    fl.close()

re_ifid = re.compile('^[A-Z0-9-]+$')
re_ifidline = re.compile('^IFID: ([A-Z0-9-]+)$')
re_formatline = re.compile('^Format: ([A-Za-z0-9 _-]+)$')

def get_ifid(file):
    res = subprocess.check_output([opts.babel, '-ifid', file])
    res = res.strip()
    match = re_ifidline.match(res)
    if match:
        return match.group(1)
    raise Exception('Babel tool did not return an IFID')

def get_format(file):
    res = subprocess.check_output([opts.babel, '-format', file])
    res = res.strip()
    match = re_formatline.match(res)
    if match:
        val = match.group(1)
        if val.startswith('blorbed '):
            val = val[8:]
        return val
    raise Exception('Babel tool did not return a format')

def run(gamefile):
    if re_ifid.match(gamefile):
        # This is an IFID, not a filename.
        ifid = gamefile
        dir = os.path.join(opts.shotdir, ifid)
        if not os.path.exists(dir):
            print '%s: no IFID directory (%s)' % (ifid, dir)
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
                print '%s: no file listed in contents file in %s' % (ifid, dir)
                return
        except IOError:
            print '%s: cannot read contents file in %s' % (ifid, dir)
            return

    if not os.path.exists(gamefile):
        print '%s: no such file' % (gamefile,)
        return
    
    try:
        ifid = get_ifid(gamefile)
    except Exception, ex:
        print '%s: unable to get IFID: %s: %s' % (gamefile, ex.__class__.__name__, ex)
        return

    try:
        format = get_format(gamefile)
    except Exception, ex:
        print '%s: unable to get format: %s: %s' % (gamefile, ex.__class__.__name__, ex)
        return
    if format not in ['zcode', 'glulx']:
        print '%s: format is not zcode/glulx: %s' % (gamefile, format)
        return

    dir = os.path.join(opts.shotdir, ifid)
    if not os.path.exists(dir):
        os.mkdir(dir)

    if format == 'zcode':
        terppath = opts.zterp
    else:
        terppath = opts.gterp
    testterpargs = []
    cmdlist = []
    
    args = [ terppath ] + testterpargs + [ gamefile ]
    proc = None

    try:
        proc = subprocess.Popen(args,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        gamestate = GameStateRemGlk(proc.stdin, proc.stdout)
    
        gamestate.initialize()
        gamestate.accept_output()
        for cmd in cmdlist:
            gamestate.perform_input(cmd)
            gamestate.accept_output()
        write_html(ifid, gamefile, gamestate.statuswin, gamestate.storywin, dirpath=dir)
        print '%s: (IFID %s): done' % (gamefile, ifid)
    except Exception, ex:
        print '%s: unable to run: %s: %s' % (gamefile, ex.__class__.__name__, ex)
    
    gamestate = None
    if proc is not None:
        proc.stdin.close()
        proc.stdout.close()
        proc.kill()
        proc.poll()
        proc = None
    
    return ifid

if not args:
    print 'usage: ifomatic.py [options] files or ifids ...'
    sys.exit(-1)

styleblock = ''
if opts.cssfile:
    fl = open(opts.cssfile)
    styleblock = fl.read()
    fl.close()

for arg in args:
    run(arg)
