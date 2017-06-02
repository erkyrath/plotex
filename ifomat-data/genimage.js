/* This script must be run in phantomjs. The arguments (all required)
   are source HTML pathname, destination PNG pathname, and window size
   in pixels. E.g.:

   phantomjs ifomat-data/genimage.js file.html output.png 800x600
 */

var system = require('system');
var page = require('webpage').create();

var infile = system.args[1];
var outfile = system.args[2];
var size = system.args[3].split('x');

page.viewportSize = { width: 1*size[0], height: 1*size[1] };
page.clipRect = { top: 0, left: 0, width: page.viewportSize.width, height: page.viewportSize.height };

page.open(infile, function() {
    page.render(outfile);
    phantom.exit();
});
