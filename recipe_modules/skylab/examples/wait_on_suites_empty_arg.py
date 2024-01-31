# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf import duration_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'skylab',
]



def RunSteps(api):
  responses = api.skylab.wait_on_suites(
      [], timeout=duration_pb2.Duration(seconds=3600))
  api.assertions.assertEqual(len(responses), 0)


def GenTests(api):
  yield api.test('basic')
