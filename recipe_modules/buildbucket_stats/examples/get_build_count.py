# -*- coding: utf-8 -*-

# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'buildbucket_stats',
]



def RunSteps(api):
  build_count = api.buildbucket_stats.get_build_count('bucket_name',
                                                      common_pb2.STARTED)
  api.assertions.assertEqual(build_count, 3)


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.simulated_search_results([
          build_pb2.Build(id=123),
          build_pb2.Build(id=321),
          build_pb2.Build(id=231),
      ], 'buildbucket.search'),
  )
