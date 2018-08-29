# -*- coding: utf-8 -*-
import logging
import time
import threading

from logging_helpers import _L
from microdrop.interfaces import IPlugin
from microdrop.plugin_helpers import hub_execute_async
from microdrop.plugin_manager import PluginGlobals, Plugin, implements
import asyncio_helpers as ah
import blinker
import deepdiff
import trollius as asyncio

from ._version import get_versions
from .windows_joypad_interface import joyGetPos, joyGetDevCaps, get_state


@asyncio.coroutine
def check_joypad(signals, joy_id, poll_interval=.001, settle_duration=.010, **kwargs):
    caps = joyGetDevCaps(joy_id)
    info = joyGetPos(joy_id)

    start = time.time()
    steady_state = {}

    while True:
        try:
            new_state = get_state(joy_id, info=info, caps=caps)
        except IOError:
            continue
        now = time.time()
        if new_state == steady_state:
            start = now
        else:
            if (now - start) > settle_duration:
                # State has stablized.
                message = {'old': steady_state, 'new': new_state,
                           'diff': deepdiff.DeepDiff(steady_state, new_state)}
                signals.signal('state-changed').send(message)
                steady_state = new_state
        yield asyncio.From(asyncio.sleep(poll_interval))


__version__ = get_versions()['version']
del get_versions

logger = logging.getLogger(__name__)

PluginGlobals.push_env('microdrop.managed')


class JoypadControlPlugin(Plugin):
    '''
    Trigger electrode state directional controls using a joypad.

     - Up, down, left, and right: corresponding directional control
     - Button 0: clear all electrode states
     - Button 3: actuate electrodes where liquid is detected
    '''
    implements(IPlugin)
    version = __version__
    plugin_name = 'microdrop.joypad_control_plugin'

    def __init__(self):
        self.name = self.plugin_namet
        self._electrode_states = iter([])
        self.plugin = None
        self.signals = blinker.Namespace()
        self.task = None
        self._most_recent_message = {}

    def on_plugin_enable(self):
        # Start joypad listener.
        self.task = ah.cancellable(check_joypad)
        self.signals.clear()

        def _on_changed(message):
            self._most_recent_message = message

            if ((abs(message['new']['axes']['x']) > .4)  ^
                (abs(message['new']['axes']['y']) > .4)):

                # Either **x** or **y** (_not_ both) is pressed.
                if message['new']['axes']['x'] > .4:
                    # Right.
                    direction = 'right'
                elif message['new']['axes']['x'] < -.4:
                    # Left.
                    direction = 'left'
                if message['new']['axes']['y'] > .4:
                    # Down.
                    direction = 'down'
                elif message['new']['axes']['y'] < -.4:
                    # Up.
                    direction = 'up'

                hub_execute_async('microdrop.electrode_controller_plugin',
                                  'set_electrode_direction_states',
                                  direction=direction)
            elif message['diff'] == {'values_changed':
                                     {"root['button_states'][0]":
                                      {'new_value': True,
                                       'old_value': False}}}:
                _L().info('Button 0 was pressed.')
                hub_execute_async('microdrop.electrode_controller_plugin',
                                  'clear_electrode_states')
            elif message['diff'] == {'values_changed':
                                     {"root['button_states'][3]":
                                      {'new_value': True,
                                       'old_value': False}}}:
                _L().info('Button 3 was pressed.')
                hub_execute_async('dropbot_plugin', 'find_liquid')
            else:
                _L().info('%s', message)


        self.signals.signal('state-changed').connect(_on_changed, weak=False)
        thread = threading.Thread(target=self.task, args=(self.signals, 0))
        thread.daemon = True
        thread.start()

    def on_plugin_disable(self):
        # Stop joypad listener.
        if self.task is not None:
            self.task.cancel()
            self.task = None
        self.signals.clear()


PluginGlobals.pop_env()
