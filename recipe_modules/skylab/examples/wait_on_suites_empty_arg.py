# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from google.protobuf import duration_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  responses = api.skylab.wait_on_suites(
      [], timeout=duration_pb2.Duration(seconds=3600))
  api.assertions.assertEqual(len(responses), 0)


def GenTests(api):
  yield api.test('basic')
