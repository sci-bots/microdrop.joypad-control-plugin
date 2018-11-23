# -*- coding: utf-8 -*-
import logging
import re
import time
import threading

from logging_helpers import _L
from microdrop.interfaces import IPlugin
from microdrop.plugin_helpers import hub_execute_async
from microdrop.plugin_manager import PluginGlobals, Plugin, implements
from zmq_plugin.schema import decode_content_data
import asyncio_helpers as ah
import blinker
import deepdiff
import pandas as pd
import trollius as asyncio

from ._version import get_versions
from .windows_joypad_interface import get_state


@asyncio.coroutine
def check_joypad(signals, joy_id, poll_interval=.001, settle_duration=.010, **kwargs):
    start = time.time()
    steady_state = {}
    cre_button = re.compile(r"root\['button_states'\]\[(?P<button>\d+)\]")

    while True:
        try:
            new_state = get_state(joy_id)
        except IOError:
            continue
        now = time.time()
        if new_state == steady_state:
            start = now
        else:
            if (now - start) > settle_duration:
                # State has stablized.
                diff = deepdiff.DeepDiff(steady_state, new_state)
                message = {'old': steady_state, 'new': new_state, 'diff': diff}

                try:
                    signals.signal('state-changed').send(message)
                    # Send `buttons-changed` signal if buttons have changed state.
                    # `buttons` property is a dictionary of new button states
                    # (i.e., `<new_value>`) keyed by button number (old value not
                    # included because it is implied by the fact that a state
                    # changed occurred and the value is boolean).
                    buttons = {int(cre_button.match(k).group('button')):
                               v['new_value']
                            for k, v in diff.get('values_changed', {}).items()
                            if cre_button.match(k)}
                    if buttons:
                        message['buttons'] = buttons
                        signals.signal('buttons-changed').send(message)
                except Exception:
                    _L().info('Error sending signals.', exc_info=True)
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
    plugin_name = 'joypad_control_plugin'

    def __init__(self):
        self.name = self.plugin_name
        self.signals = blinker.Namespace()
        self.task = None
        self._most_recent_message = {}

    def on_plugin_enable(self):
        # Start joypad listener.
        self.task = ah.cancellable(check_joypad)
        self.signals.clear()

        liquid_state = {}

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

                if all((direction in ('right', 'left'), liquid_state,
                        message['new']['button_states'][3])):
                    electrodes = liquid_state['electrodes']

                    if 'i' in liquid_state:
                        i = liquid_state['i'] + (1 if direction == 'right'
                                                 else -1)
                    else:
                        i = (0 if direction == 'right'
                             else len(electrodes) - 1)
                    i = i % len(electrodes)
                    hub_execute_async('dropbot_plugin', 'identify_electrode',
                                      electrode_id=electrodes[i])
                    liquid_state['i'] = i
                else:
                    hub_execute_async('microdrop.electrode_controller_plugin',
                                      'set_electrode_direction_states',
                                      direction=direction)

        def _on_buttons_changed(message):
            if message['buttons'] == {0: True}:
                # Button 0 was pressed.
                hub_execute_async('microdrop.electrode_controller_plugin',
                                  'clear_electrode_states')
            elif message['buttons'] == {3: True}:
                # Button 3 was pressed.
                i = liquid_state.get('i')
                liquid_state.clear()

                def _on_found(zmq_response):
                    data = decode_content_data(zmq_response)
                    liquid_state['electrodes'] = data
                    if i is not None and i < len(liquid_state['electrodes']):
                        liquid_state['i'] = i

                hub_execute_async('dropbot_plugin', 'find_liquid',
                                  callback=_on_found)
            elif message['buttons'] == {3: False}:
                # Button 3 was released.
                _L().info('Button 3 was released. `%s`', liquid_state)
                i = liquid_state.get('i')
                if i is not None:
                    selected_electrode = liquid_state['electrodes'][i]
                    electrode_states = pd.Series(1, index=[selected_electrode])
                    hub_execute_async('microdrop.electrode_controller_plugin',
                                      'clear_electrode_states')
                    hub_execute_async('microdrop.electrode_controller_plugin',
                                      'set_electrode_states',
                                      electrode_states=electrode_states)
            elif message['buttons'] == {4: True}:
                # Button 4 was pressed.
                if message['new']['button_states'][8]:
                    # Button 8 was also held down.
                    hub_execute_async('microdrop.gui.protocol_controller',
                                      'first_step')
                else:
                    hub_execute_async('microdrop.gui.protocol_controller',
                                      'prev_step')
            elif message['buttons'] == {5: True}:
                # Button 5 was pressed.
                if message['new']['button_states'][8]:
                    # Button 8 was also held down.
                    hub_execute_async('microdrop.gui.protocol_controller',
                                      'last_step')
                else:
                    hub_execute_async('microdrop.gui.protocol_controller',
                                      'next_step')
            elif message['buttons'] == {9: True}:
                # Button 9 was pressed.
                hub_execute_async('microdrop.gui.protocol_controller',
                                  'run_protocol')
            elif all(message['buttons'].values()):
                _L().info('%s', message)

        self.signals.signal('state-changed').connect(_on_changed, weak=False)
        self.signals.signal('buttons-changed').connect(_on_buttons_changed,
                                                       weak=False)
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
