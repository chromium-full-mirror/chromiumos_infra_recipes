# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'orch_menu',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  relevant_build = build_pb2.Build()
  relevant_build.critical = common_pb2.YES
  relevant_tag = relevant_build.tags.add()
  relevant_tag.key = 'relevance'
  relevant_tag.value = 'relevant'
  api.assertions.assertTrue(api.orch_menu.ps_critical_relevant(relevant_build))
  irrelevant_build = build_pb2.Build()
  irrelevant_build.critical = common_pb2.YES
  irrelevant_tag = irrelevant_build.tags.add()
  irrelevant_tag.key = 'relevance'
  irrelevant_tag.value = 'not relevant'
  api.assertions.assertFalse(
      api.orch_menu.ps_critical_relevant(irrelevant_build))
  unspecified_build = build_pb2.Build()
  unspecified_build.critical = common_pb2.YES
  api.assertions.assertTrue(
      api.orch_menu.ps_critical_relevant(unspecified_build))
  unspecified_build.critical = common_pb2.NO
  api.assertions.assertFalse(
      api.orch_menu.ps_critical_relevant(unspecified_build))


def GenTests(api):
  yield api.test('basic')
