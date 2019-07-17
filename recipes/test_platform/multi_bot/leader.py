# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.test_platform.multibot.common import MultiBotConfig, HostInfoStore
from PB.test_platform.multibot.leader_transitions import (
    FollowersState, LeaderTransitionMessage)
from PB.test_platform.multibot.requests import LeaderRequest

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',

    'ipc',
]

PROPERTIES = LeaderRequest

def RunSteps(api, properties):
  # Properties is a LeaderRequest object.

  # CI steps here
  with api.step.nest('scheduling step'):
    api.step('prejob coordination', ['echo', 'create subscription'])
    api.step('schedule children', ['echo', 'schedule children',
                                   str(properties.fanout - 1)])
  api.step('prejob step', ['echo', 'local prejob task'])
  with api.step.nest('waiting steps'):
    api.step('wait for children', ["ipc.receive"])
    api.step('notify ready', ["ipc.send_string"])
  api.step('payload step', ['echo', 'execute payload'])
  api.step('cleanup step', ['echo', 'cleanup tasks'])

def GenTests(api):
  yield api.test('basic')
