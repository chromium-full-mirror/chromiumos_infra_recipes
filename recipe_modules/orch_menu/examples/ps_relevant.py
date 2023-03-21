# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'orch_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  relevant = [common_pb2.StringPair(key='relevance', value='relevant')]
  irrelevant = [common_pb2.StringPair(key='relevance', value='not relevant')]
  unspecified = [common_pb2.StringPair(key='some other key', value='somevalue')]
  api.assertions.assertTrue(api.orch_menu.ps_relevant(relevant))
  api.assertions.assertFalse(api.orch_menu.ps_relevant(irrelevant))
  api.assertions.assertTrue(api.orch_menu.ps_relevant(unspecified))


def GenTests(api):
  yield api.test('basic')
