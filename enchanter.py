# Plot constraint logic for Infocom's _Enchanter_
#   Andrew Plotkin <erkyrath@eblong.com>
#   This script is in the public domain.
#
# This is not a complete analysis of the game, but it covers all of the
# important actions, the winning path, and three interesting failures:
# frotzing yourself (so you can't find the ozmoo spell), wasting
# KULCAD on the jeweled box, and wasting KULCAD on the guarded door.
#
# On the other hand, it does not represent the hunger/thirst/sleep timers.
# It also has no notion of getting trapped in areas, so it does not cover
# the failures where you enter Krill's tower without enough spells to
# defeat him.
#
# C.E.Forman's diagram at http://www.xyzzynews.com/xyzzy.4e.html was
# helpful in constructing this script.
#
# For a full description, see <http://eblong.com/zarf/plotex/>
#
# (Update June 2012: Added a requirement: you can't open the egg until
# you've gained entry to the castle.)

from plotex import *

class Scenario(ScenarioClass):
    
    # The starting state: player has nothing. (We omit frotz, gnusto, etc
    # for simplicity.)
    
    Start = State()

    
    # The actions:
    
    OpenOven = Once(Set(bread=True))
    FillJug = Set(water=True)

    GetRezrov = Set(rezrov=True)

    FrotzItem = Set(light=True)
    FrotzSelf = Set(light=True, _selfglow=True)

    OpenGate = Chain(Has(rezrov=True), Set(incourtyard=True))
    ExploreCastle = Chain(Has(incourtyard=True), Has(light=True), Set(incastle=True))
    
    SleepInBed = Chain(Has(incastle=True), Set(vaxum=True))
    OpenNorthGate = Chain(Has(incastle=True, rezrov=True), Set(krebf=True))

    OpenEgg = Chain(Has(incastle=True), Once(Set(shredscroll=True)))
    FixScroll = Chain(Has(shredscroll=True, krebf=True), Set(zifmia=True))

    SummonAdventurer = Chain(Has(incastle=True, zifmia=True), Set(adventurer=True))
    FriendlyAdventurer = Chain(Has(adventurer=True, vaxum=True), Once(Set(mappencil=True)))
    SpellOpenDoor = Chain(Lose('kulcad'), Once(Set(mappencil=True)))
    SolveTerror = Chain(Has(incastle=True, mappencil=True), Set(guncho=True, mappencil=False))

    FindGondar = Chain(Has(incastle=True), Set(gondar=True))

    FindPortrait = Chain(Has(incastle=True, _selfglow=False), Set(ozmoo=True))
    GetKnife = Chain(Has(ozmoo=True), Set(knife=True))

    CutOpenBox = Chain(Has(knife=True), Set(melbor=True))
    SpellOpenBox = Chain(Lose('kulcad'), Set(melbor=True))

    SearchCell = Chain(Has(incastle=True), Set(exex=True))
    TalkToTurtle = Chain(Has(incastle=True), Set(friendlyturtle=True))
    GetKulcad = Chain(Has(friendlyturtle=True, exex=True), Once(Set(kulcad=True)))

    PassStairs = Chain(Has(incastle=True, melbor=True), Lose('kulcad'), Set(intower=True))

    MeetKrill = Chain(Has(intower=True), Has(gondar=True), HasAny(vaxum=True, cleesh=True), Set(krill=True))
    Win = Chain(Has(krill=True), Lose('guncho'), Set(win=True))

    
    # Some unit tests for the scenario:

    TestWinnable = Test(can=Has(win=True))
    TestMustNotFrotzSelf = Test(block=FrotzItem, cannot=Has(win=True))
    TestMustNotKulcadBox = Test(includes=SpellOpenBox, cannot=Has(win=True))


# This parses and carries out the command-line options, using the Scenario.
shell(Scenario)
