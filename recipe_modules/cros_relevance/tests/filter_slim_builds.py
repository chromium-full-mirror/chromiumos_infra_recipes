# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import common as bbcommon_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_relevance',
    'git_footers',
]



def RunSteps(api):
  builders = ['a-slim-cq', 'b-slim-cq', 'c-cq']
  gc = [
      bbcommon_pb2.GerritChange(change=123, host='cr.googlesource.com'),
  ]
  api.assertions.assertEqual(
      api.cros_relevance._filter_slim_builders(builders, gc),
      list(api.properties['expected_builders']))


def GenTests(api):

  yield api.test(
      'none',
      api.git_footers.simulated_get_footers(
          [], parent_step_name='check disallow slim builds'),
      api.properties(
          expected_builders=['a-slim-cq', 'b-slim-cq', 'c-cq'],
      ))

  yield api.test(
      'all',
      api.git_footers.simulated_get_footers(
          ['all'], parent_step_name='check disallow slim builds'),
      api.properties(
          expected_builders=['a-cq', 'b-cq', 'c-cq'],
      ))

  yield api.test(
      'relevant-builder',
      api.git_footers.simulated_get_footers(
          ['a-cq'], parent_step_name='check disallow slim builds'),
      api.properties(
          expected_builders=['a-cq', 'b-slim-cq', 'c-cq'],
      ))

  yield api.test(
      'irrelevant-builder',
      api.git_footers.simulated_get_footers(
          ['d-cq'], parent_step_name='check disallow slim builds'),
      api.properties(
          expected_builders=['a-slim-cq', 'b-slim-cq', 'c-cq'],
      ))
