# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'phosphorus',
]

from PB.test_platform.phosphorus.prejob import PrejobRequest
from PB.test_platform.phosphorus.runtest import RunTestRequest
from PB.test_platform.phosphorus.upload_to_tko import UploadToTkoRequest

def RunSteps(api):
  with api.assertions.assertRaises(ValueError):
    api.phosphorus.prejob(None)
  prejob_req = PrejobRequest()
  api.phosphorus.prejob(prejob_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.run_test(None)
  run_test_req = RunTestRequest()
  api.phosphorus.run_test(run_test_req)

  with api.assertions.assertRaises(ValueError):
    api.phosphorus.upload_to_tko(None)
  upload_to_tko_req = UploadToTkoRequest()
  api.phosphorus.upload_to_tko(upload_to_tko_req)


def GenTests(api):
  yield api.test('basic')
