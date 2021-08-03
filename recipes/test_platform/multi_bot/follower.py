# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.test_platform.multibot.requests import FollowerRequest

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
    'ipc',
]

PROPERTIES = FollowerRequest


# pylint: disable=unused-argument
def RunSteps(api, properties):
  # Properties is a FollowerRequest object.

  # CI steps here
  with api.step.nest('prejob step'):
    api.step('execute prejob', ['echo', 'prejob task'])
    api.step('prejob coordination', ['ipc.make_subscription'])
  api.step('send info step', ["ipc.send"])
  api.step('wait to start step', ["ipc.receive"])
  api.step('wait to finish step', ["ipc.receive"])
  api.step('cleanup step', ['echo', 'cleanup tasks'])


def GenTests(api):
  yield api.test('basic')
