import sys
import os
import optparse
import subprocess
import select

popt = optparse.OptionParser()

(opts, args) = popt.parse_args()

class Command:
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

    @staticmethod
    def extract_text(line):
        con = line.get('content')
        if not con:
            return []
        return [ (run.get('text', ''), run.get('style', 'normal')) for run in con ]
    
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
                            datls = self.extract_text(line)
                            if line.get('append') and len(self.storywin):
                                self.storywin[-1] += datls
                            else:
                                self.storywin.append(datls)
                elif win.get('type') == 'grid':
                    lines = content.get('lines')
                    for line in lines:
                        linenum = line.get('line')
                        datls = self.extract_text(line)
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

def escape_html(val):
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
        res.append('&nbsp;' * (spaces-1))
        res.append(' ')
    return ''.join(res)

styleblock = '''
<style type="text/css">
body {
  font-family: "Georgia", serif;
  font-size: 12pt;
  line-height: 1.25em;
}
.StatusWindow {
  background: #EDC;
  font-family: monospace;
  font-size: 11pt;
  line-height: 1.4em;
}
.StatusLine {
  margin-left: 2em;
  margin-right: 2em;
}
.StoryPara {
  margin-left: 2em;
  margin-right: 2em;
}
.Style_emphasized {
  font-style: italic;
}
.Style_preformatted {
  font-family: monospace;
  font-size: 11pt;
  line-height: 1.25em;
}
.Style_header {
  font-size: 1.2em;
  line-height: 1.25em;
  font-weight: bold;
}
.Style_subheader {
  font-weight: bold;
}
.Style_alert {
  font-style: italic;
}
.Style_note {
  font-style: italic;
}
.Style_input {
  font-weight: bold;
  color: #080;
}
</style>
'''

def write_html(statuswin, storywin):
    fl = open('test.html', 'w')

    fl.write('<!doctype HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">\n')
    fl.write('<html>\n')
    fl.write('<head>\n')
    fl.write('<title>Game Dump</title>\n')
    fl.write(styleblock)
    fl.write('</head>\n')
    fl.write('<body>\n')
    fl.write('<div class="StatusWindow">\n')
    for line in statuswin:
        fl.write('<div class="StatusLine">')
        if not line:
            fl.write('&nbsp;')
        for span in line:
            fl.write('<span class="Style_%s">%s</span>' % (span[1], escape_html(span[0])))
        fl.write('</div>\n')
    fl.write('</div>\n')
    for line in storywin:
        fl.write('<div class="StoryPara">')
        if not line:
            fl.write('&nbsp;')
        for span in line:
            fl.write('<span class="Style_%s">%s</span>' % (span[1], escape_html(span[0])))
        fl.write('</div>\n')
    fl.write('</body>\n')
    fl.write('</html>\n')

    fl.close()
    
def run():
    testterppath = 'glulxer'
    testterpargs = []
    testgamefile = '/Users/zarf/src/glk-dev/unittests/Advent.ulx'
    testgamefile = '/Users/zarf/src/if/hadean/releases/rel4/HadeanLands.ulx'
    
    args = [ testterppath ] + testterpargs + [ testgamefile ]
    proc = subprocess.Popen(args,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    cmdlist = [ Command('yes') ]
    
    gamestate = GameStateRemGlk(proc.stdin, proc.stdout)
    
    try:
        gamestate.initialize()
        gamestate.accept_output()
        for cmd in cmdlist:
            gamestate.perform_input(cmd)
            gamestate.accept_output()
        write_html(gamestate.statuswin, gamestate.storywin)
        print '%s: wrote file.' % (testgamefile,)
    except Exception, ex:
        print '%s: unable to run: %s: %s' % (testgamefile, ex.__class__.__name__, ex)
    
    gamestate = None
    proc.stdin.close()
    proc.stdout.close()
    proc.kill()
    proc.poll()

run()
