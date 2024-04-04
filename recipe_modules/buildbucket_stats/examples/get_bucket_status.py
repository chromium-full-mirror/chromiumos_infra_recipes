# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'buildbucket_stats',
]



def RunSteps(api):
  status_map = api.buildbucket_stats.get_bucket_status('bucket_name')
  api.assertions.assertEqual(status_map['STARTED'], 0)
  api.assertions.assertEqual(status_map['SCHEDULED'], 3)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.simulated_multi_predicates_search_results([
          build_pb2.Build(id=123),
          build_pb2.Build(id=321),
          build_pb2.Build(id=231),
      ], 'buildbucket.search'),
  )
