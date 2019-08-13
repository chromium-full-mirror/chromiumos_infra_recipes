# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'skylab_local_state',
]

from PB.test_platform.skylab_local_state.load import LoadRequest, LoadResponse
from PB.test_platform.skylab_local_state.save import SaveRequest

def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.skylab_local_state.load(None)

  load_req = LoadRequest()
  load_resp = api.skylab_local_state.load(load_req)
  api.assertions.assertEqual(load_resp, LoadResponse())

  with api.assertions.assertRaises(ValueError):
    api.skylab_local_state.save(None)

  save_req = SaveRequest()
  api.skylab_local_state.save(save_req)

def GenTests(api):
  yield api.test('basic')
